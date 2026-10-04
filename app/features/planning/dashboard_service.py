"""Bounded due-work projection owned by planning; dates remain proposed work dates."""

from app.features.planning.batch_models import PlanningBatch
from app.features.planning.models import PlanningDemand

MAX_DASHBOARD_BATCHES = 20


def today_work(db, org_id, today):
    query = (
        db.query(PlanningBatch)
        .join(PlanningDemand, PlanningBatch.demand_id == PlanningDemand.id)
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningDemand.org_id == org_id,
            PlanningDemand.status == "open",
            PlanningBatch.status.in_(("planned", "blocked")),
            PlanningBatch.proposed_start_date <= today,
        )
    )
    total = query.count()
    rows = (
        query.order_by(
            PlanningBatch.priority.desc(),
            PlanningBatch.proposed_start_date,
            PlanningBatch.batch_number,
            PlanningBatch.id,
        )
        .limit(MAX_DASHBOARD_BATCHES)
        .all()
    )
    return {
        "date": today.isoformat(),
        "total": total,
        "truncated": total > MAX_DASHBOARD_BATCHES,
        "items": [
            {
                "id": str(row.id),
                "reference": (row.snapshot or {}).get("demand_reference", "Production demand"),
                "product_name": (row.snapshot or {}).get("output_name", "Planned product"),
                "site_name": (row.snapshot or {}).get("site_name", "Main site"),
                "batch_number": row.batch_number,
                "quantity": format(row.quantity, "f"),
                "unit": row.unit,
                "priority": row.priority,
                "proposed_start_date": row.proposed_start_date.isoformat(),
                "overdue": row.proposed_start_date < today,
                "pinned": row.pinned,
                "status": row.status,
            }
            for row in rows
        ],
    }
