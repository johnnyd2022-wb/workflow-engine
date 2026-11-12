"""Switch live cost on for an organisation (roadmap 8.1; first used for Whistlebird).

One idempotent step that does what an owner's "turn costing on" means in the spec (Q9):
the ``costing`` feature, new purchases counted from today, stock-flow history rebuilt for lots
made before the cost engine, and, if asked, purchases loaded from Xero back to a date. It
reports what's costed afterwards, so the owner knows where to start.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.features.costing import FEATURE_KEY
from app.features.costing.models import CostingSettings
from app.features.costing.service import CostingError


def _three_years_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 3)
    except ValueError:  # 29 Feb
        return day.replace(year=day.year - 3, day=28)


def enable_costing(db: Session, org_id: UUID, *, history_from: date | None = None, today: date | None = None) -> dict:
    """Idempotent. Commits as it goes: the feature and the history rebuild stand even if loading
    purchases from Xero then fails (that part is reported, not raised)."""
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.costing.backfill import backfill_flows
    from app.features.costing.purchase_sources import nz_today

    today = today or nz_today()
    if history_from is not None:
        if history_from > today:
            raise CostingError("history_from can't be in the future")
        if history_from <= _three_years_before(today):
            raise CostingError("Load at most 3 years of purchases at a time")

    FeatureSubscriptionRepository(db).grant(org_id, FEATURE_KEY, notes="live cost switched on")
    db.execute(
        insert(CostingSettings.__table__)
        .values(id=uuid4(), org_id=org_id, use_last_known_price=True)
        .on_conflict_do_nothing(index_elements=["org_id"])
    )
    settings = db.query(CostingSettings).filter(CostingSettings.org_id == org_id).with_for_update().one()
    if settings.start_date is None:
        settings.start_date = today  # "new purchases from today" (spec Q9); never moved after
    start_date = settings.start_date
    db.commit()

    flows = backfill_flows(db, org_id)
    db.commit()

    history = {"status": "not_requested"}
    if history_from is not None:
        history = _load_history(db, org_id, history_from, today)

    return {
        "org_id": str(org_id),
        "start_date": start_date.isoformat(),
        "flows_added": flows["inserted"],
        "inputs_skipped": flows["skipped_inputs"],
        "history": history,
        **_summary(db, org_id),
    }


def _load_history(db: Session, org_id: UUID, history_from: date, today: date) -> dict:
    from app.features.crm.services.xero_sync_service import PurchasesNeedReconnectError, XeroSyncService
    from app.observability import get_logger

    try:
        stats = XeroSyncService(db).historical_purchases(org_id, history_from, today)
        db.commit()
    except PurchasesNeedReconnectError as error:
        db.rollback()
        return {"status": "needs_reconnect", "message": str(error)}
    except Exception:  # noqa: BLE001 - reported, never echoing Xero/SQL internals
        db.rollback()
        ref = uuid4().hex[:12]
        get_logger(__name__).exception("costing_enable_history_failed", org_id=str(org_id), ref=ref)
        return {"status": "failed", "message": f"Loading purchases from Xero failed (ref {ref})"}
    return {
        "status": "loaded",
        "from": history_from.isoformat(),
        "to": today.isoformat(),
        "documents": stats["documents"],
        "lines": stats["lines"],
    }


def _summary(db: Session, org_id: UUID) -> dict:
    from app.features.costing import actions, readiness

    products = readiness.list_products(db, org_id)
    new = actions.list_purchases(db, org_id, "to_record", None, None)["counts"]["to_record"]
    everything = actions.list_purchases(db, org_id, "to_record", None, None, historical=True)["counts"]["to_record"]
    return {
        "products": len(products),
        "products_ready": sum(1 for p in products if p["ready"]),
        "not_ready": [
            {"name": p["name"], "costed": p["materials_costed"], "of": p["materials_total"]}
            for p in products
            if not p["ready"]
        ],
        "purchases_to_record": new,
        "earlier_purchases_to_record": max(everything - new, 0),
    }
