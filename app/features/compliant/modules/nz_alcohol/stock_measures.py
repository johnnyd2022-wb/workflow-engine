"""Excise measures on stock (plans 2.1 and 2.6): LAL, duty, removals and lodged entries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.compliant.models.excise import ExciseLodgement
from app.features.compliant.modules.nz_alcohol import excise
from app.features.compliant.platform.stock_measures import StockFlow
from app.features.compliant.service import ComplianceService


class NZAlcoholStockMeasures:
    labels = {
        "measure": "LAL",
        "measure_long": "litres of alcohol (LAL)",
        "cost": "duty",
        "declared": "Lodged LAL",
        "declared_long": "lodged excise entries",
        "authority": "Customs",
        "controlled_area": "licensed area",
        "flows": "Removals are the same records your excise entries use",
    }

    def applies(self, session: Session, org_id: UUID) -> bool:
        profile = ComplianceService(session).get_profile(org_id)
        return bool(profile is not None and profile.enabled)

    def measure(self, session: Session, org_id: UUID, pairs: list, on: date) -> list[dict]:
        out = []
        for m in excise.measure(session, org_id, pairs, on):
            detail = None
            if m["litres"] is not None and m["abv_percent"] is not None:
                detail = f"{m['litres'].lstrip('-')} L at {m['abv_percent']}%"
            out.append({"measure": m["lal"], "cost": m["duty"], "detail": detail})
        return out

    def flows(self, session: Session, org_id: UUID, start: date, end: date) -> list[StockFlow]:
        return [
            StockFlow(item=r.item, quantity=Decimal(r.quantity), direction="in" if r.kind == "returned" else "out")
            for r in excise.removals_between(session, org_id, start, end)
        ]

    def declared(self, session: Session, org_id: UUID, start: date | None, end: date) -> dict[str, str]:
        return excise.lodged_between(session, org_id, start, end)

    def declared_periods(self, session: Session, org_id: UUID, limit: int) -> list[dict]:
        rows = (
            session.query(ExciseLodgement)
            .filter(ExciseLodgement.org_id == org_id)
            .order_by(ExciseLodgement.period_start.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "period_start": x.period_start.isoformat(),
                "period_end": x.period_end.isoformat(),
                "declared_on": x.lodged_on.isoformat(),
                "reference": x.entry_reference,
                "measure": (x.snapshot or {}).get("total_lal") or "0",
                "cost": (x.snapshot or {}).get("total_duty") or "0",
                "nil": bool(x.nil_return),
            }
            for x in rows
        ]

    def product_key(self, name: str) -> str:
        return excise._base_name(name)
