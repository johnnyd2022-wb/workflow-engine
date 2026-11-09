"""The Wine page's data: plan status, this vintage, label claims and bottling pre-flight."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.features.compliant.models import ComplianceProfile

from . import composition as comp_mod
from . import label, roles, rules

PLAN_SETTING: Final = "wine_plan"
EXEMPTION_LIMIT_L: Final = Decimal(20000)  # Wine Regulations 2021 reg 19: < 20,000 L over 2 years
EXEMPTION_YEARS: Final = 2
_MODES: Final = ("registered", "exempt")
_PLAN_FIELDS: Final = ("mode", "plan_reference", "verifier", "next_verification", "exemption_start")
_LOT_LIMIT: Final = 60


def _profile(session: Session, org_id: UUID) -> ComplianceProfile | None:
    return session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()


def _litres(entry: dict) -> Decimal:
    qty = comp_mod._num(entry.get("quantity")) or Decimal(0)
    unit = str(entry.get("unit") or "").strip().lower()
    if unit in {"l", "litre", "litres", "liter", "liters"}:
        return qty
    if unit in {"ml", "millilitre", "millilitres"}:
        return qty / 1000
    return Decimal(0)


def _delivered_kg(step: ExecutionStep) -> Decimal:
    total = Decimal(0)
    for entry in step.actual_outputs or []:
        if isinstance(entry, dict) and str(entry.get("unit") or "").strip().lower() == "kg":
            total += comp_mod._num(entry.get("quantity")) or Decimal(0)
        elif isinstance(entry, dict) and str(entry.get("unit") or "").strip().lower() in {"t", "tonne", "tonnes"}:
            total += (comp_mod._num(entry.get("quantity")) or Decimal(0)) * 1000
    return total


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def validate_plan(data: dict) -> dict:
    """Clean a plan update, or raise ValueError with a message the form can show."""
    if not isinstance(data, dict):
        raise ValueError("Send the plan as an object")
    mode = data.get("mode")
    if mode not in _MODES:
        raise ValueError("Choose a registered plan or the small winemaker exemption")
    out: dict = {"mode": mode}
    for key in ("plan_reference", "verifier"):
        text = str(data.get(key) or "").strip()
        if len(text) > 200:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} is too long")
        if text:
            out[key] = text
    for key in ("next_verification", "exemption_start"):
        if data.get(key):
            parsed = _date(data.get(key))
            if parsed is None:
                raise ValueError(f"{key.replace('_', ' ').capitalize()} must be a date")
            out[key] = parsed.isoformat()
    if mode == "exempt" and "exemption_start" not in out:
        raise ValueError("Enter the date your exemption started")
    return out


def plan_status(session: Session, org_id: UUID, settings: dict, role_map: dict[UUID, str], today: date) -> dict:
    plan = {k: v for k, v in (settings.get(PLAN_SETTING) or {}).items() if k in _PLAN_FIELDS}
    start = _date(plan.get("exemption_start")) if plan.get("mode") == "exempt" else None
    window_start = start or (today - timedelta(days=365 * EXEMPTION_YEARS))
    window_end = date(start.year + EXEMPTION_YEARS, start.month, min(start.day, 28)) if start else today
    ferment_steps = [sid for sid, role in role_map.items() if role == "ferment"]
    made = Decimal(0)
    if ferment_steps:
        rows = (
            session.query(ExecutionStep.actual_outputs)
            .filter(
                ExecutionStep.org_id == org_id,
                ExecutionStep.step_id.in_(ferment_steps),
                ExecutionStep.completed_at.isnot(None),
                ExecutionStep.completed_at >= datetime.combine(window_start, datetime.min.time(), UTC),
                ExecutionStep.completed_at < datetime.combine(window_end + timedelta(days=1), datetime.min.time(), UTC),
            )
            .all()
        )
        for (outputs,) in rows:
            made += sum((_litres(o) for o in outputs or [] if isinstance(o, dict)), Decimal(0))
    share = float(made / EXEMPTION_LIMIT_L) if EXEMPTION_LIMIT_L else 0.0
    next_verification = _date(plan.get("next_verification"))
    return {
        **plan,
        "configured": plan.get("mode") in _MODES,
        "litres_made": float(round(made, 1)),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "exemption_limit_l": float(EXEMPTION_LIMIT_L),
        "exemption_share": round(share, 4),
        "exemption_expires": window_end.isoformat() if start else None,
        "exemption_days_left": (window_end - today).days if start else None,
        "exemption_warning": bool(start) and (share >= 0.8 or (window_end - today).days <= 60),
        "verification_due_days": (next_verification - today).days if next_verification else None,
    }


def _last_drill(session: Session, org_id: UUID) -> str | None:
    from app.features.recalls.models import Recall

    row = session.query(Recall.opened_at).filter(Recall.org_id == org_id).order_by(Recall.opened_at.desc()).first()
    return row[0].isoformat() if row else None


def overview(session: Session, org_id: UUID, today: date | None = None) -> dict:
    today = today or date.today()
    profile = _profile(session, org_id)
    settings = dict((profile.settings if profile else None) or {})
    enabled = bool(profile and profile.enabled and rules.wine_enabled(settings))
    if not enabled:
        return {"enabled": False}
    role_map = roles.roles_for_org(session, org_id, settings)
    by_role: dict[str, list[UUID]] = {}
    for step_id, role in role_map.items():
        by_role.setdefault(role, []).append(step_id)

    vintage = rules.current_vintage(today)
    produced = (
        session.query(InventoryItem, ExecutionStep)
        .join(
            ExecutionStep,
            (ExecutionStep.id == InventoryItem.source_execution_step_id) & (ExecutionStep.org_id == org_id),
        )
        .filter(InventoryItem.org_id == org_id, ExecutionStep.step_id.in_(list(role_map) or [UUID(int=0)]))
        .order_by(InventoryItem.created_at.desc())
        .limit(500)
        .all()
    )
    intake_lots = [(i, s) for i, s in produced if role_map.get(s.step_id) == "intake"]
    this_vintage = [
        (i, s)
        for i, s in intake_lots
        if str((s.execution_data or {}).get(rules.VINTAGE) or "").startswith(str(vintage))
    ]
    in_tank = sum(
        (
            _litres({"quantity": i.quantity, "unit": i.unit})
            for i, s in produced
            if role_map.get(s.step_id) in {"crush", "ferment", "blend", "cellar"} and (i.quantity or 0) > 0
        ),
        Decimal(0),
    )
    bottled = [(i, s) for i, s in produced if role_map.get(s.step_id) == "bottle"]

    lots, preflights = [], []
    # Wine that exists now: a consumed juice or young-wine lot is history, already part of
    # whatever it became. Bottled lots stay while any stock is left.
    current = [p for p in produced if role_map.get(p[1].step_id) != "intake" and (p[0].quantity or 0) > 0]
    for item, step in current[:_LOT_LIMIT]:
        comp = comp_mod.composition(session, org_id, item.id, role_map)
        role = role_map.get(step.step_id)
        entry = {
            "id": str(item.id),
            "name": item.name,
            "quantity": float(item.quantity or 0),
            "unit": item.unit,
            "role": role,
            "stage": roles.ROLE_LABELS.get(role or "", ""),
            "made_at": step.completed_at.isoformat() if step.completed_at else None,
            "composition": comp.as_dict() if comp else None,
        }
        lots.append(entry)
        if role == "bottle":
            preflights.append({"lot": entry, **label.preflight(step.execution_data or {}, comp)})

    return {
        "enabled": True,
        "plan": plan_status(session, org_id, settings, role_map, today),
        "vintage": {
            "year": vintage,
            "intake_lots": len(this_vintage),
            # What was delivered (the intake step's output), not what's left after crushing.
            "intake_kg": float(round(sum((_delivered_kg(s) for _, s in this_vintage), Decimal(0)), 1)),
            "litres_in_tank": float(round(in_tank, 1)),
            "bottled_lots": len(bottled),
        },
        "steps": [
            {"step_id": str(sid), "role": role}
            for sid, role in sorted(role_map.items(), key=lambda kv: (roles.ROLES.index(kv[1]), str(kv[0])))
        ],
        "lots": lots,
        "preflight": preflights,
        "last_recall": _last_drill(session, org_id),
    }


def update_plan(session: Session, org_id: UUID, data: dict) -> dict:
    from app.features.compliant.service import ComplianceService

    clean = validate_plan(data)
    service = ComplianceService(session)
    profile = service.get_profile(org_id)
    if profile is None or not profile.enabled:
        raise ValueError("Switch on Compliance first")
    settings = dict(profile.settings or {})
    settings[PLAN_SETTING] = clean
    service.upsert_profile(org_id, {"settings": settings})
    return clean
