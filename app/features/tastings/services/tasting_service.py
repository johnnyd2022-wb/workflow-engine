"""Atomic event scheduling, physical dispatch, and conserved tasting-pool outcomes.

No external I/O and no commits here: the HTTP boundary owns the transaction.
"""

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_

from app.core.backend.event_writer import EventWriter
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.stock_location import StockLocation, StockTransfer
from app.core.db.models.user import User
from app.core.db.repositories.inventory_repo import _item_snapshot
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.utils.time import utc_now
from app.core.utils.unit_conversion import normalize_unit
from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.models.customs_premises import CustomsCoverage
from app.features.compliant.models.excise import ExciseRate
from app.features.compliant.modules.nz_alcohol import excise, excise_tariff
from app.features.compliant.modules.nz_alcohol.movement_excise import prepare_dispatch_duty
from app.features.compliant.modules.nz_alcohol.premises import licence_for_area
from app.features.crm.models.crm_task import CRMTask
from app.features.crm.models.xero_contact import XeroContact
from app.features.tastings.models import Tasting, TastingAllocation, TastingStockLot
from app.features.tastings.repositories.tasting_repo import TastingRepository

NZ = ZoneInfo("Pacific/Auckland")
Q4 = Decimal("0.0001")


class TastingError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def uid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise TastingError("A valid UUID is required") from None


def amount(value, *, zero=False):
    if isinstance(value, bool) or len(str(value)) > 40:
        raise TastingError("Record a bounded decimal quantity")
    try:
        result = Decimal(str(value))
        if (
            not result.is_finite()
            or result < 0
            or (not zero and result == 0)
            or result > Decimal("999999999999")
            or result != result.quantize(Q4)
        ):
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise TastingError(
            "Record a positive quantity with at most four decimal places"
            if not zero
            else "Record a nonnegative quantity with at most four decimal places"
        ) from None


def text(value, limit, *, optional=False):
    if value is None and optional:
        return ""
    if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
        raise TastingError(f"Record text of at most {limit} characters")
    return value.strip()


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() != result.astimezone(NZ).utcoffset():
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise TastingError("Use an ISO timestamp with the Pacific/Auckland offset at that instant") from None


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def get_event(db, org_id, event_id, *, lock=False):
    event = TastingRepository(db).get(org_id, uid(event_id), lock=lock)
    if event is None:
        raise TastingError("Tasting not found", 404)
    return event


def _eligible(item):
    return bool(
        item
        and item.inventory_type == "final_product"
        and item.contract_customer_id is None
        and item.transfer_receipt_id is None
        and "contract_customer_id" not in (item.extra_data or {})
        and not item.name.casefold().endswith("library stock")
        and not (item.extra_data or {}).get("library_stock")
        and (item.source_execution_id or item.source_execution_step_id or (item.extra_data or {}).get("opening_stock"))
    )


def save_event(db, org_id, actor_id, data, event_id=None):
    allowed = {
        "title",
        "venue_name",
        "venue_address",
        "venue_type",
        "licence_reference",
        "starts_at",
        "ends_at",
        "rep_id",
        "contact_id",
        "notes",
        "allocations",
    }
    if not isinstance(data, dict) or set(data) - allowed:
        raise TastingError("Unknown tasting fields")
    creating = event_id is None
    event = get_event(db, org_id, event_id, lock=True) if event_id else None
    if event and event.status != "planned":
        raise TastingError("Only a planned tasting can be rescheduled; use outcomes or cancellation", 409)

    def value(key, default=None):
        return data.get(key, getattr(event, key, default))

    fields = {
        key: text(value(key), limit, optional=key in {"licence_reference", "notes"})
        for key, limit in [
            ("title", 160),
            ("venue_name", 160),
            ("venue_address", 500),
            ("licence_reference", 160),
            ("notes", 4000),
        ]
    }
    fields["venue_type"] = value("venue_type")
    if fields["venue_type"] not in {"own", "external"}:
        raise TastingError("Choose own or external venue")
    fields["starts_at"] = (
        timestamp(data["starts_at"]) if "starts_at" in data else (event.starts_at if event else timestamp(None))
    )
    fields["ends_at"] = (
        timestamp(data["ends_at"]) if "ends_at" in data else (event.ends_at if event else timestamp(None))
    )
    if not timedelta(0) < fields["ends_at"] - fields["starts_at"] <= timedelta(days=7):
        raise TastingError("End must follow start, within seven days")
    fields["rep_id"] = uid(value("rep_id"))
    if (
        not db.query(User.id)
        .filter(
            User.org_id == org_id,
            User.id == fields["rep_id"],
            User.is_active.is_(True),
            or_(User.access_expires_at.is_(None), User.access_expires_at > utc_now()),
        )
        .first()
    ):
        raise TastingError("Choose an active rep in this business")
    contact = value("contact_id")
    fields["contact_id"] = uid(contact) if contact else None
    if (
        contact
        and not db.query(XeroContact.id)
        .filter(XeroContact.org_id == org_id, XeroContact.id == fields["contact_id"])
        .first()
    ):
        raise TastingError("Choose a customer in this business")
    allocations = None
    if "allocations" in data or event is None:
        raw = data.get("allocations", [])
        if not isinstance(raw, list) or not 0 <= len(raw) <= 20:
            raise TastingError("Choose at most twenty stock lines")
        allocations, seen, parsed = [], set(), []
        for line in raw:
            if (
                not isinstance(line, dict)
                or set(line) - {"source_item_id", "source_pool_id", "quantity"}
                or bool(line.get("source_item_id")) == bool(line.get("source_pool_id"))
            ):
                raise TastingError("Each line needs exactly one warehouse or tasting-pool source")
            key = "source_item_id" if line.get("source_item_id") else "source_pool_id"
            source_id = uid(line[key])
            quantity = amount(line.get("quantity"))
            if (key, source_id) in seen:
                raise TastingError("Combine duplicate stock sources into one line")
            seen.add((key, source_id))
            parsed.append((key, source_id, quantity))
        item_ids = [source for key, source, _ in parsed if key == "source_item_id"]
        pool_ids = [source for key, source, _ in parsed if key == "source_pool_id"]
        sources = (
            {
                row.id: row
                for row in db.query(InventoryItem).filter(
                    InventoryItem.org_id == org_id, InventoryItem.id.in_(item_ids)
                )
            }
            if item_ids
            else {}
        )
        pools = (
            {
                row.id
                for row in db.query(TastingStockLot.id).filter(
                    TastingStockLot.org_id == org_id, TastingStockLot.id.in_(pool_ids)
                )
            }
            if pool_ids
            else set()
        )
        for key, source_id, quantity in parsed:
            if key == "source_item_id":
                source = sources.get(source_id)
                if not _eligible(source):
                    raise TastingError(
                        "Choose producer-owned finished stock with production or opening-balance provenance"
                    )
                if (
                    normalize_unit(source.unit) in {"bottles", "cans", "kegs"}
                    and quantity != quantity.to_integral_value()
                ):
                    raise TastingError("Counted packs must be whole")
            elif source_id not in pools:
                raise TastingError("Tasting stock not found")
            allocations.append(TastingAllocation(org_id=org_id, **{key: source_id}, quantity=quantity))
    if event is None:
        task = CRMTask(org_id=org_id, title=fields["title"], created_by_user_id=actor_id)
        db.add(task)
        db.flush()
        event = Tasting(org_id=org_id, task_id=task.id, created_by=actor_id, **fields)
        db.add(event)
        db.flush()
    else:
        for key, val in fields.items():
            setattr(event, key, val)
        task = db.query(CRMTask).filter(CRMTask.org_id == org_id, CRMTask.id == event.task_id).with_for_update().one()
    task.title = fields["title"]
    task.due_date = fields["starts_at"].astimezone(NZ).date()
    task.assigned_to_user_id = fields["rep_id"]
    task.contact_id = fields["contact_id"]
    task.description = f"Tasting at {fields['venue_name']} · {fields['starts_at'].astimezone(NZ).isoformat()}"
    if allocations is not None:
        db.query(TastingAllocation).filter(
            TastingAllocation.org_id == org_id, TastingAllocation.tasting_id == event.id
        ).delete(synchronize_session=False)
        for line in allocations:
            line.tasting_id = event.id
            db.add(line)
    db.flush()
    _emit_lifecycle(db, event, actor_id, "created" if creating else "updated", task_created=creating)
    return event


def _source_basis(db, org_id, item, quantity, on, prepared):
    if (
        not _eligible(item)
        or prepared.get("contract_order_id")
        or not prepared.get("found")
        or prepared.get("source_execution_id") != (str(item.source_execution_id) if item.source_execution_id else None)
        or prepared.get("source_execution_step_id")
        != (str(item.source_execution_step_id) if item.source_execution_step_id else None)
    ):
        raise TastingError("Stock ownership or production provenance is unresolved")
    org = db.query(Organisation).filter(Organisation.id == org_id).one()
    site = db.query(Site).filter(Site.org_id == org_id, Site.id == item.site_id).one_or_none() if item.site_id else None
    location = (
        db.query(StockLocation)
        .filter(StockLocation.org_id == org_id, StockLocation.id == item.location_id)
        .with_for_update(read=True)
        .one_or_none()
        if item.location_id
        else None
    )
    if (item.site_id and (site is None or not site.is_active)) or (
        item.location_id and (location is None or not location.is_active or location.site_id != item.site_id)
    ):
        raise TastingError("Stock source must be an active location and site in this business")
    licence = licence_for_area(db, org_id, item.site_id, item.location_id, on) if item.site_id else None
    recorded_coverage = (
        db.query(CustomsCoverage.id)
        .filter(CustomsCoverage.org_id == org_id, CustomsCoverage.site_id == item.site_id)
        .first()
        if item.site_id
        else None
    )
    if (org.multiple_sites_enabled or recorded_coverage) and (licence is None or licence.kind not in {"lma", "oss"}):
        raise TastingError("Record valid dated LMA or OSS coverage for the stock source")
    prior = None
    if location and not location.inside_licensed_area and licence is None:
        candidates = (
            db.query(StockTransfer)
            .filter(
                StockTransfer.org_id == org_id,
                StockTransfer.to_item_id == item.id,
                StockTransfer.direction == "out",
                StockTransfer.occurred_on <= on,
                StockTransfer.unit == item.unit,
            )
            .limit(2)
            .all()
        )
        if len(candidates) != 1 or candidates[0].quantity < item.quantity:
            raise TastingError(
                "Stock outside the licensed area needs one attributable prior removal; review its movement history"
            )
        prior = candidates[0]
    profile = (
        db.query(AlcoholProductProfile)
        .filter(
            AlcoholProductProfile.org_id == org_id,
            func.lower(AlcoholProductProfile.inventory_name) == item.name.lower(),
            AlcoholProductProfile.is_active.is_(True),
        )
        .one_or_none()
    )
    unit = normalize_unit(item.unit)
    if unit in {"bottles", "cans", "kegs"}:
        if (
            quantity != quantity.to_integral_value()
            or profile is None
            or not profile.pack_volume_ml
            or profile.pack_volume_ml <= 0
        ):
            raise TastingError("Whole packs need a configured positive pack size")
        volume = quantity * Decimal(str(profile.pack_volume_ml))
    elif unit in {"ml", "l"}:
        volume = quantity * (1000 if unit == "l" else 1)
    else:
        raise TastingError("Choose bottles, cans, kegs, litres or millilitres")
    if volume > Decimal("99999999999999") or volume != volume.quantize(Q4):
        raise TastingError("Stock volume exceeds supported precision")
    abv = excise._lot_abv(db, item, profile)
    if abv is not None and (not abv.is_finite() or not 0 < abv <= 100):
        abv = None
    rates = db.query(ExciseRate).filter(ExciseRate.org_id == org_id).all()
    tariff = excise.tariff_item_for(profile, abv)
    rate = excise.resolve_rate(rates, tariff, on) if profile and abv is not None else None
    litres = volume / 1000
    lal = litres * abv / 100 if abv is not None else None
    duty = (
        excise.duty_for(
            rate, litres.quantize(Decimal(".001"), ROUND_HALF_UP), lal.quantize(Decimal(".001"), ROUND_HALF_UP)
        )
        if lal is not None and rate
        else None
    )
    levy_rate = excise_tariff.levy_rate(abv, on) if abv is not None else None
    levy = (litres * levy_rate[1] / 100).quantize(Decimal(".01"), ROUND_HALF_UP) if levy_rate else None
    gst = (levy * excise_tariff.GST_RATE).quantize(Decimal(".01"), ROUND_HALF_UP) if levy is not None else None
    problems = []
    if profile is None:
        problems.append("Not set up as an excise product")
    if abv is None:
        problems.append("No valid batch or product ABV recorded")
    if tariff is None:
        problems.append("Excise classification missing")
    if rate is None:
        problems.append("No rate in force on removal date")
    if levy is None:
        problems.append("Alcohol levy rate unresolved")

    def s(x):
        return str(x) if x is not None else None

    basis = {
        "version": "tasting_removal_1",
        "purpose": "tasting",
        "product": item.name,
        "batch": item.supplier_batch_number or (item.extra_data or {}).get("batch_number"),
        "source_item_id": str(item.id),
        "source_execution_id": s(item.source_execution_id),
        "source_execution_step_id": s(item.source_execution_step_id),
        "source_output_id": s(item.source_output_id),
        "source_site_id": s(item.site_id),
        "source_location_id": s(item.location_id),
        "source_location": location.name if location else "Main licensed area",
        "source_site": site.name if site else None,
        "source_cca": {"id": str(licence.id), "number": licence.number, "name": licence.name, "kind": licence.kind}
        if licence
        else None,
        "owner": "producer",
        "quantity": s(quantity),
        "unit": item.unit,
        "pack_volume_ml": s(profile.pack_volume_ml) if profile else None,
        "occurred_on": on.isoformat(),
        "litres": s(litres),
        "abv_percent": s(abv),
        "lal": s(lal),
        "tariff_item": tariff,
        "rate": s(rate[0]) if rate else None,
        "rate_basis": rate[1] if rate else None,
        "rate_date": on.isoformat(),
        "duty": s(duty),
        "levy": s(levy),
        "gst": s(gst),
        "problems": problems,
        "prior_removal_reference": str(prior.id) if prior else None,
        "prior_removal_date": prior.occurred_on.isoformat() if prior else None,
        "abv_source": (
            "inventory_batch"
            if (item.extra_data or {}).get("abv_percent") not in (None, "")
            else "production_step"
            if item.source_execution_step_id
            else "product_profile"
        ),
        "profile_id": s(profile.id) if profile else None,
        "product_type": profile.product_type if profile else None,
        "excise_category": profile.excise_category if profile else None,
        "rate_reference": (
            {
                "id": str(excise._rate_for(rates, tariff, on).id),
                "effective_from": excise._rate_for(rates, tariff, on).effective_from.isoformat(),
                "source": "organisation",
            }
            if excise._rate_for(rates, tariff, on)
            else {"source": "customs_guide", "guide_status": excise_tariff.guide_status(on)}
        )
        if rate
        else None,
        "recorded_at": utc_now().isoformat(),
        "recorded_liability_not_paid": True,
    }
    return volume, basis, not bool(prior)


def dispatch(db, org_id, actor_id, event_id, data, key):
    if not isinstance(data, dict) or set(data) != {"actual_date"}:
        raise TastingError("Record the actual physical dispatch date")
    try:
        on = date.fromisoformat(data["actual_date"])
    except (TypeError, ValueError):
        raise TastingError("Record a valid actual date") from None
    if on > utc_now().astimezone(NZ).date():
        raise TastingError("Physical dispatch cannot be in the future")
    key = text(key, 100)
    digest = fingerprint({"actual_date": on.isoformat()})
    event = get_event(db, org_id, event_id, lock=True)
    if event.dispatch_key:
        if key == event.dispatch_key and digest == event.dispatch_hash:
            return event
        raise TastingError("Dispatch was already recorded with different request details", 409)
    if event.status != "planned":
        raise TastingError("Only planned tastings can dispatch stock", 409)
    if db.query(Tasting.id).filter(Tasting.org_id == org_id, Tasting.dispatch_key == key).first():
        raise TastingError("Dispatch key was already used for another tasting", 409)
    lines = TastingRepository(db).allocations(org_id, event.id)
    if not lines:
        raise TastingError("Allocate stock before dispatch")
    # Use the global provenance-before-stock lock order. Stable source ordering avoids
    # two events acquiring the same inventory/pool rows in opposing order.
    prepared = {
        line.source_item_id: prepare_dispatch_duty(db, org_id, line.source_item_id)
        for line in sorted(lines, key=lambda x: str(x.source_item_id))
        if line.source_item_id
    }
    db.query(Organisation.id).filter(Organisation.id == org_id).with_for_update(read=True).one()
    db.query(Site.id).filter(Site.org_id == org_id).order_by(Site.id).with_for_update(read=True).all()
    items = {
        row.id: row
        for row in db.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(prepared))
        .order_by(InventoryItem.id)
        .with_for_update()
        .populate_existing()
    }
    pool_ids = [line.source_pool_id for line in lines if line.source_pool_id]
    pools = {
        row.id: row
        for row in db.query(TastingStockLot)
        .filter(TastingStockLot.org_id == org_id, TastingStockLot.id.in_(pool_ids))
        .order_by(TastingStockLot.id)
        .with_for_update()
        .populate_existing()
    }
    with allow_inventory_quantity_write(InventoryQuantityWriteReason.TASTING_DISPATCH):
        for line in lines:
            if line.source_item_id:
                item = items.get(line.source_item_id)
                if item is None or item.quantity < line.quantity:
                    raise TastingError("Insufficient warehouse stock", 409)
                volume, basis, new_removal = _source_basis(db, org_id, item, line.quantity, on, prepared[item.id])
                basis["recorded_by"] = str(actor_id)
                lot = TastingStockLot(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    tasting_id=event.id,
                    source_item_id=item.id,
                    quantity=line.quantity,
                    unit=item.unit,
                    initial_volume_ml=volume,
                    remaining_volume_ml=volume,
                    reserved_volume_ml=volume,
                    removed_on=date.fromisoformat(basis["prior_removal_date"])
                    if basis.get("prior_removal_date")
                    else on,
                    creates_removal=int(new_removal),
                    snapshot=basis,
                    recorded_by=actor_id,
                )
                db.add(lot)
                db.flush([lot])  # persist immutable removal before linking the existing allocation
                before = str(item.quantity)
                item.quantity -= line.quantity
                db.add(
                    InventoryMovement(
                        org_id=org_id,
                        inventory_item_id=item.id,
                        movement_type=InventoryMovementType.ADJUSTMENT.value,
                        quantity=-line.quantity,
                        unit=item.unit,
                        movement_metadata={
                            "reason": "tasting_dispatch",
                            "tasting_id": str(event.id),
                            "tasting_stock_lot_id": str(lot.id),
                            "occurred_on": on.isoformat(),
                            "actor_id": str(actor_id),
                        },
                    )
                )
                db.flush()
                EventWriter(db, org_id).emit(
                    event_type="inventory_item.quantity_adjusted",
                    entity_type="inventory_item",
                    entity_id=item.id,
                    actor_id=actor_id,
                    payload={
                        **_item_snapshot(item),
                        "quantity_before": before,
                        "quantity_after": str(item.quantity),
                        "delta": str(-line.quantity),
                        "reason": "tasting_dispatch",
                        "tasting_id": str(event.id),
                        "tasting_stock_lot_id": str(lot.id),
                    },
                    diff={"quantity": {"before": before, "after": str(item.quantity)}},
                )

            else:
                lot = pools.get(line.source_pool_id)
                volume = line.quantity
                if lot is None or lot.remaining_volume_ml - lot.reserved_volume_ml < volume:
                    raise TastingError("Insufficient available tasting-pool stock", 409)
                lot.reserved_volume_ml += volume
            line.stock_lot_id = lot.id
            line.reserved_volume_ml = volume
            line.state = "dispatched"
        event.status = "dispatched"
        event.dispatched_on = on
        event.dispatched_by = actor_id
        event.dispatch_key = key
        event.dispatch_hash = digest
        task = db.query(CRMTask).filter(CRMTask.org_id == org_id, CRMTask.id == event.task_id).with_for_update().one()
        task.status = "in_progress"
        task.board_lane_id = None
        db.flush()
    _emit_lifecycle(db, event, actor_id, "dispatched")
    return event


def finalise(db, org_id, actor_id, event_id, data):
    if not isinstance(data, dict) or set(data) - {"usage", "samples_count", "notes"}:
        raise TastingError("Unknown outcome fields")
    raw = data.get("usage")
    if not isinstance(raw, list) or not 0 <= len(raw) <= 20:
        raise TastingError("Record usage for each allocation")
    usage = {}
    for line in raw:
        if not isinstance(line, dict) or set(line) != {"allocation_id", "used_volume_ml"}:
            raise TastingError("Record allocation and measured used millilitres")
        key = uid(line["allocation_id"])
        if key in usage:
            raise TastingError("Duplicate allocation outcome")
        usage[key] = amount(line["used_volume_ml"], zero=True)
    count = data.get("samples_count")
    if count is not None and (type(count) is not int or not 0 <= count <= 1000000):
        raise TastingError("Samples count must be a nonnegative whole number, at most 1000000")
    notes = text(data.get("notes"), 4000, optional=True)
    digest = fingerprint(
        {
            "usage": sorted((str(k), str(v.normalize())) for k, v in usage.items()),
            "samples_count": count,
            "notes": notes,
        }
    )
    event = get_event(db, org_id, event_id, lock=True)
    if event.status == "completed":
        if event.finalise_hash == digest:
            return event
        raise TastingError("Completed outcomes are immutable; changed replays are rejected", 409)
    if event.status != "dispatched":
        raise TastingError("Dispatch stock before recording usage", 409)
    lines = TastingRepository(db).allocations(org_id, event.id)
    if set(usage) != {line.id for line in lines}:
        raise TastingError("Record measured usage for every allocation")
    pools = {
        row.id: row
        for row in db.query(TastingStockLot)
        .filter(TastingStockLot.org_id == org_id, TastingStockLot.id.in_([line.stock_lot_id for line in lines]))
        .order_by(TastingStockLot.id)
        .with_for_update()
        .populate_existing()
    }
    for line in lines:
        used = usage[line.id]
        if used > line.reserved_volume_ml:
            raise TastingError("Used volume cannot exceed dispatched volume")
        lot = pools[line.stock_lot_id]
        lot.reserved_volume_ml -= line.reserved_volume_ml
        lot.remaining_volume_ml -= used
        line.used_volume_ml = used
        line.state = "completed"
    event.status = "completed"
    event.samples_count = count
    event.outcome_notes = notes
    event.finalise_hash = digest
    event.finalised_by = actor_id
    task = db.query(CRMTask).filter(CRMTask.org_id == org_id, CRMTask.id == event.task_id).with_for_update().one()
    task.status = "completed"
    task.completed_at = utc_now()
    task.board_lane_id = None
    db.flush()
    _emit_lifecycle(db, event, actor_id, "completed")
    return event


def cancel(db, org_id, actor_id, event_id):
    event = get_event(db, org_id, event_id, lock=True)
    if event.status == "cancelled":
        return event
    if event.status == "completed":
        raise TastingError("Completed tasting outcomes cannot be cancelled", 409)
    lines = TastingRepository(db).allocations(org_id, event.id)
    if event.status == "dispatched":
        pools = {
            row.id: row
            for row in db.query(TastingStockLot)
            .filter(TastingStockLot.org_id == org_id, TastingStockLot.id.in_([line.stock_lot_id for line in lines]))
            .order_by(TastingStockLot.id)
            .with_for_update()
            .populate_existing()
        }
        for line in lines:
            pools[line.stock_lot_id].reserved_volume_ml -= line.reserved_volume_ml
    for line in lines:
        line.state = "cancelled"
    event.status = "cancelled"
    event.finalised_by = actor_id
    task = db.query(CRMTask).filter(CRMTask.org_id == org_id, CRMTask.id == event.task_id).with_for_update().one()
    task.status = "cancelled"
    task.board_lane_id = None
    db.flush()
    _emit_lifecycle(db, event, actor_id, "cancelled")
    return event


def pool_dict(lot):
    return {
        "id": str(lot.id),
        "purpose": "tasting",
        "product": lot.snapshot["product"],
        "batch": lot.snapshot.get("batch"),
        "quantity": str(lot.quantity),
        "unit": lot.unit,
        "initial_volume_ml": str(lot.initial_volume_ml),
        "remaining_volume_ml": str(lot.remaining_volume_ml),
        "reserved_volume_ml": str(lot.reserved_volume_ml),
        "available_volume_ml": str(lot.remaining_volume_ml - lot.reserved_volume_ml),
        "removed_on": lot.removed_on.isoformat(),
        "duty_status": "prior_removal_recorded"
        if not lot.creates_removal
        else ("needs_attention" if lot.snapshot.get("problems") else "liability_recorded"),
        "basis": lot.snapshot,
    }


def event_dict(db, event, *, detail=True):
    result = {
        key: getattr(event, key)
        for key in [
            "title",
            "venue_name",
            "venue_address",
            "venue_type",
            "licence_reference",
            "status",
            "notes",
            "samples_count",
            "outcome_notes",
        ]
    }
    result.update(
        {
            key: str(getattr(event, key)) if getattr(event, key) else None
            for key in ["id", "task_id", "rep_id", "contact_id", "created_by", "dispatched_by", "finalised_by"]
        }
    )
    result.update(
        {
            key: getattr(event, key).isoformat() if getattr(event, key) else None
            for key in ["starts_at", "ends_at", "dispatched_on", "created_at", "updated_at"]
        }
    )
    result["href"] = "/crm/tastings?tasting_id=" + str(event.id)
    if detail:
        rep = db.query(User).filter(User.org_id == event.org_id, User.id == event.rep_id).one_or_none()
        result["rep_name"] = ((" ".join(filter(None, [rep.first_name, rep.last_name]))) or rep.email) if rep else None
        lines = TastingRepository(db).allocations(event.org_id, event.id)
        items = {
            x.id: x
            for x in db.query(InventoryItem).filter(
                InventoryItem.org_id == event.org_id,
                InventoryItem.id.in_([line.source_item_id for line in lines if line.source_item_id]),
            )
        }
        pools = {
            x.id: x
            for x in db.query(TastingStockLot).filter(
                TastingStockLot.org_id == event.org_id,
                TastingStockLot.id.in_(
                    [
                        line.stock_lot_id or line.source_pool_id
                        for line in lines
                        if line.stock_lot_id or line.source_pool_id
                    ]
                ),
            )
        }
        result["allocations"] = []
        for line in lines:
            item = items.get(line.source_item_id)
            pool = pools.get(line.stock_lot_id or line.source_pool_id)
            result["allocations"].append(
                {
                    "id": str(line.id),
                    "source_item_id": str(line.source_item_id) if line.source_item_id else None,
                    "source_pool_id": str(line.source_pool_id) if line.source_pool_id else None,
                    "stock_lot_id": str(line.stock_lot_id) if line.stock_lot_id else None,
                    "quantity": str(line.quantity),
                    "reserved_volume_ml": str(line.reserved_volume_ml),
                    "used_volume_ml": str(line.used_volume_ml),
                    "state": line.state,
                    "product": pool.snapshot["product"] if pool else item.name if item else None,
                    "batch": pool.snapshot.get("batch") if pool else item.supplier_batch_number if item else None,
                    "unit": "mL" if line.source_pool_id else item.unit if item else None,
                    "duty_status": pool_dict(pool)["duty_status"] if pool else None,
                    "basis": pool.snapshot if pool else None,
                }
            )
    return result


def _emit_lifecycle(db, event, actor_id, action, *, task_created=False):
    from app.features.crm.services.crm_service import _task_event_snapshot

    writer = EventWriter(db, event.org_id)
    writer.emit(
        event_type="tasting." + action,
        entity_type="tasting",
        entity_id=event.id,
        actor_id=actor_id,
        payload=event_dict(db, event, detail=False),
    )
    task = db.query(CRMTask).filter(CRMTask.org_id == event.org_id, CRMTask.id == event.task_id).one()
    writer.emit(
        event_type="crm_task.created" if task_created else "crm_task.updated",
        entity_type="crm_task",
        entity_id=task.id,
        actor_id=actor_id,
        payload=_task_event_snapshot(task),
    )
