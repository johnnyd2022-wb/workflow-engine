"""Capture reviewed LAL movement facts without a stock write or a lodgement claim.

Callers must supply the trusted locked movement context and same-org product/CCA.
This first basis supports tested spirits over23% ABV and configured LAL rates only.
It does not open a removal route or change the legacy excise draft.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from app.core.utils.unit_conversion import normalize_unit
from app.features.compliant.models.excise import ExciseRate
from app.features.compliant.modules.nz_alcohol.excise import _base_name
from app.features.compliant.modules.nz_alcohol.premises import licence_for_area


@dataclass(frozen=True)
class CapturedRemovalBasis:
    valid: bool
    reason: str
    evidence: str = "{}"


def prepare_dispatch_duty(session, org_id, source_item_id):
    """Lock a source's Step → Execution → Order before Core locks Org/Site/Inventory.

    The item read is only a locator. The policy must compare this result with the
    later locked stock snapshot before it trusts any order or payer fact.
    """
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.features.contract_manufacturing.models.orders import ContractOrder, ContractOrderExecution

    item = (
        session.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id, InventoryItem.id == source_item_id)
        .one_or_none()
    )
    if item is None:
        return {"source_item_id": str(source_item_id), "found": False}
    step_id = item.source_execution_step_id
    execution_id = item.source_execution_id
    if step_id:
        step = (
            session.query(ExecutionStep)
            .filter(ExecutionStep.org_id == org_id, ExecutionStep.id == step_id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if step is None or (execution_id and step.execution_id != execution_id):
            raise ValueError("Source production provenance is unresolved")
        execution_id = step.execution_id
    if execution_id:
        execution = (
            session.query(Execution)
            .filter(Execution.org_id == org_id, Execution.id == execution_id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if execution is None:
            raise ValueError("Source production provenance is unresolved")
    prepared = {
        "source_item_id": str(item.id),
        "found": True,
        "source_execution_step_id": str(step_id) if step_id else None,
        "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
        "contract_order_id": None,
        "duty_responsibility": "producer_licensee",
        "customer_cca_reference": None,
    }
    if not execution_id:
        return prepared
    assignment = (
        session.query(ContractOrderExecution)
        .filter(ContractOrderExecution.org_id == org_id, ContractOrderExecution.execution_id == execution_id)
        .populate_existing()
        .one_or_none()
    )
    if assignment is None:
        return prepared
    order = (
        session.query(ContractOrder)
        .filter(ContractOrder.org_id == org_id, ContractOrder.id == assignment.order_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if order is None or order.status != "confirmed":
        raise ValueError("Contract duty responsibility needs a confirmed order")
    prepared.update(
        contract_order_id=str(order.id),
        duty_responsibility=order.duty_responsibility,
        customer_cca_reference=order.customer_cca_reference,
    )
    return prepared


def _positive(value):
    if isinstance(value, bool):
        raise ValueError("A positive finite decimal is required")
    if len(str(value)) > 100:
        raise ValueError("A bounded decimal is required")
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise ValueError("A positive finite decimal is required") from None
    if (
        not result.is_finite()
        or result <= 0
        or not -12 <= result.adjusted() <= 20
        or len(result.as_tuple().digits) > 24
    ):
        raise ValueError("A positive finite decimal is required")
    return result


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("Record a bounded documentary reference")
    return value.strip()


def capture_spirits_removal_basis(session, org_id, context, product, source_licence):
    """Build immutable producer-owned physical-removal evidence; never commit."""
    try:
        if context.operation != "dispatch" or type(context.occurred_on) is not date:
            raise ValueError("Physical removals need a dated dispatch")
        if product.org_id != org_id or source_licence.org_id != org_id:
            raise ValueError("Product and source CCA must belong to this business")
        coverage = licence_for_area(
            session, org_id, context.source_site_id, context.source_location_id, context.occurred_on
        )
        if coverage is None or coverage.id != source_licence.id or source_licence.kind not in {"lma", "oss"}:
            raise ValueError("The physical source needs this exact dated LMA/OSS coverage")
        if product.inventory_name.casefold() != _base_name(context.product_name).casefold():
            raise ValueError("Product classification must match the physical stock")
        source = context.source_snapshot
        if (
            not isinstance(source, Mapping)
            or "contract_customer_id" not in source
            or source["contract_customer_id"] is not None
        ):
            raise ValueError("A trusted producer-owner snapshot is required; contract duty needs its own adapter")
        if str(context.inventory_type).casefold() != "final_product" or product.product_type != "spirits":
            raise ValueError("This removal basis supports classified finished spirits only")
        if not product.is_active or not product.customs_product_code:
            raise ValueError("Record the active product's excise tariff before removal")
        data = context.approval
        if not isinstance(data, Mapping):
            raise ValueError("Record the measurement evidence before removal")
        abv = _positive(data.get("measured_abv_percent"))
        if abv <= 23 or abv > 100:
            raise ValueError("This LAL basis supports tested spirits over23% and no more than100% ABV")
        method = data.get("measurement_method")
        if not isinstance(method, str) or method not in {"analysis", "hydrometric"}:
            raise ValueError("Record analysis or hydrometric testing for these spirits")
        measured_on = date.fromisoformat(data.get("measured_on"))
        if measured_on > context.occurred_on:
            raise ValueError("Strength testing must precede the physical removal")
        measurement_reference = _text(data.get("measurement_reference"))
        volume_reference = _text(data.get("volume_reference"))
        quantity = _positive(context.quantity)
        unit = normalize_unit(context.unit)
        pack_ml = None
        if unit == "l":
            litres = quantity
        elif unit == "ml":
            litres = quantity / 1000
        elif unit in {"bottles", "cans", "kegs"}:
            if quantity != quantity.to_integral_value():
                raise ValueError("Counted removals require whole packs")
            pack_ml = _positive(product.pack_volume_ml)
            litres = quantity * pack_ml / 1000
        else:
            raise ValueError("The product's removal volume basis is unresolved")
        rate = (
            session.query(ExciseRate)
            .filter(
                ExciseRate.org_id == org_id,
                ExciseRate.tariff_item == product.customs_product_code,
                ExciseRate.effective_from <= context.occurred_on,
            )
            .order_by(ExciseRate.effective_from.desc())
            .first()
        )
        if rate is None:
            raise ValueError("Configure the LAL rate in force on the removal date")
        per_lal = _positive(rate.rate_per_lal)
        with localcontext() as arithmetic:
            arithmetic.prec = 60
            lal = litres * abv / 100
            duty = (lal * per_lal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fact = {
            "version": "nz_spirits_lal_removal_1",
            "treatment": "home_consumption",
            "duty_basis": "lal",
            "transfer_id": str(context.transfer_id),
            "source_item_id": str(context.source_item_id),
            "source_site_id": str(context.source_site_id),
            "destination_site_id": str(context.destination_site_id),
            "source_location_id": str(context.source_location_id) if context.source_location_id else None,
            "destination_location_id": str(context.destination_location_id)
            if context.destination_location_id
            else None,
            "source_cca": {
                "id": str(source_licence.id),
                "number": source_licence.number,
                "legal_entity_reference": source_licence.legal_entity_reference,
                "document_reference": source_licence.evidence_reference,
            },
            "product_id": str(product.id),
            "product_name": context.product_name,
            "tariff_item": product.customs_product_code,
            "occurred_on": context.occurred_on.isoformat(),
            "quantity": str(quantity),
            "unit": context.unit,
            "pack_volume_ml": str(pack_ml) if pack_ml else None,
            "litres": str(litres),
            "measured_abv_percent": str(abv),
            "lal": str(lal),
            "measurement_method": method,
            "measured_on": measured_on.isoformat(),
            "measurement_reference": measurement_reference,
            "volume_reference": volume_reference,
            "rate": {"id": str(rate.id), "effective_from": rate.effective_from.isoformat(), "per_lal": str(per_lal)},
            "excise_duty_only": str(duty),
            "levy": None,
            "gst": None,
            "accountable_business": str(org_id),
            "contract_order_id": None,
            "duty_payer": None,
            "authorises_physical_removal": False,
            "recorded_by": str(context.actor_id),
        }
        return CapturedRemovalBasis(True, "Recorded tested spirits LAL removal basis", json.dumps(fact, sort_keys=True))
    except (ValueError, TypeError) as exc:
        return CapturedRemovalBasis(False, str(exc) or "Removal evidence is incomplete")


def cca_movement_register(session, org_id, start, end):
    """Observed transfer facts only; never a complete entry or a nil-return verdict."""
    from app.core.db.models.site_transfer import SiteStockTransfer

    if type(start) is not date or type(end) is not date or end <= start or (end - start).days > 366:
        raise ValueError("Choose a movement period of one to366 days")
    groups, unresolved = {}, []
    rows = (
        session.query(SiteStockTransfer)
        .filter(
            SiteStockTransfer.org_id == org_id,
            SiteStockTransfer.occurred_on >= start,
            SiteStockTransfer.occurred_on < end,
        )
        .order_by(SiteStockTransfer.occurred_on, SiteStockTransfer.id)
    )
    for transfer in rows:
        evidence = transfer.decision_snapshot or {}
        source = evidence.get("source_licence") if isinstance(evidence, dict) else None
        if (
            not isinstance(source, dict)
            or evidence.get("policy") != "nz_alcohol_cca_1"
            or not isinstance(source.get("id"), str)
            or not source["id"]
        ):
            unresolved.append({"transfer_id": str(transfer.id), "reason": "Recorded source CCA decision is unresolved"})
            continue
        group = groups.setdefault(
            source["id"],
            {"source_cca": dict(source), "movements": [], "observed_excise_duty": "0", "complete_lodgement": False},
        )
        binding = evidence.get("binding") or {}
        try:
            valid_quantity = _positive(evidence.get("dispatched_quantity")) == transfer.quantity
        except ValueError:
            valid_quantity = False
        if (
            not valid_quantity
            or evidence.get("dispatched_on") != transfer.occurred_on.isoformat()
            or not isinstance(binding, dict)
            or binding.get("transfer_id") != str(transfer.id)
            or binding.get("source_item_id") != str(transfer.source_item_id)
            or binding.get("source_site_id") != str(transfer.source_site_id)
            or binding.get("destination_site_id") != str(transfer.destination_site_id)
            or binding.get("source_location_id")
            != (str(transfer.source_location_id) if transfer.source_location_id else None)
            or binding.get("destination_location_id")
            != (str(transfer.destination_location_id) if transfer.destination_location_id else None)
            or binding.get("unit") != transfer.unit
        ):
            unresolved.append(
                {
                    "transfer_id": str(transfer.id),
                    "reason": "Recorded movement identity does not match its physical ledger",
                }
            )
            continue
        entry = {
            "transfer_id": str(transfer.id),
            "occurred_on": transfer.occurred_on.isoformat(),
            "quantity": str(transfer.quantity),
            "unit": transfer.unit,
            "source_site_id": str(transfer.source_site_id),
            "destination_site_id": str(transfer.destination_site_id),
            "consignment_reference": transfer.consignment_reference,
        }
        # Existing accepted CCA-to-CCA decisions explicitly contain both licences.
        # Their authorisation is captured by the policy; no rate/ABV guess is needed.
        authority = evidence.get("authority")
        destination = evidence.get("destination_licence")
        if isinstance(authority, dict) and authority.get("authority") == "home_consumption":
            basis = evidence.get("removal_basis")
            try:
                duty = _positive(basis["excise_duty_only"])
                basis_quantity = _positive(basis["quantity"])
            except (TypeError, KeyError, ValueError):
                duty, basis_quantity = None, None
            if (
                not isinstance(basis, dict)
                or duty is None
                or basis_quantity != transfer.quantity
                or evidence.get("tax_status") != "home_consumption_excise_due"
                or evidence.get("duty_responsibility") != "producer_licensee"
                or destination is not None
                or basis.get("transfer_id") != str(transfer.id)
                or basis.get("source_item_id") != str(transfer.source_item_id)
                or not isinstance(basis.get("source_cca"), dict)
                or basis["source_cca"].get("id") != source["id"]
                or basis.get("occurred_on") != transfer.occurred_on.isoformat()
                or basis.get("unit") != transfer.unit
            ):
                unresolved.append(
                    {"transfer_id": str(transfer.id), "reason": "Recorded home-consumption duty basis is unresolved"}
                )
                continue
            entry["treatment"] = "recorded_producer_home_consumption"
            entry["removal_basis"] = dict(basis)
            group["observed_excise_duty"] = str(Decimal(group["observed_excise_duty"]) + duty)
            group["movements"].append(entry)
        elif (
            isinstance(destination, dict)
            and isinstance(authority, dict)
            and authority.get("authority")
            in {
                "same_legal_entity",
                "prior_customs_approval",
            }
        ):
            entry["treatment"] = "recorded_excise_unpaid_transfer"
            entry["destination_cca"] = dict(evidence["destination_licence"])
            group["movements"].append(entry)
        else:
            unresolved.append(
                {"transfer_id": str(transfer.id), "reason": "Removal accounting adapter is not yet integrated"}
            )
    return {
        "period_start": start.isoformat(),
        "period_end_exclusive": end.isoformat(),
        "licences": list(groups.values()),
        "unresolved_movements": unresolved,
        "complete_lodgement": False,
        "nil_return": None,
        "total_duty": None,
        "remaining_sources": [
            "Taxable removals and duty status",
            "Sales and in-CCA uses",
            "Losses/destruction",
            "Corrections",
            "Levies/GST",
        ],
    }
