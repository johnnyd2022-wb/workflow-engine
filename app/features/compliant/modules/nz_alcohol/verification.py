"""Food-safety verification lifecycle for NZ national programmes (plan 2.2).

MPI's verification frequency rules for national programmes (Food Regulations 2015,
reg 94; MPI guidance "Determining verification frequency: national programmes",
October 2019):

- Steps set the time between verifications: 1 = 3 months, 2 = 6, 3 = 9, 4 = 12,
  5 = 18, 6 = 2 years, 7 = 3 years, 8 = no further verification.
- Initial verification is due within 6 weeks of registering for a new business; for an
  existing business within 1 year (NP1, NP2) or 6 months (NP3).
- Acceptable initial verification sets NP1 to step 8, NP2 to step 7, NP3 to step 6.
- Unacceptable initial verification: NP1/NP2/NP3 to step 6/5/4 if willing and able to
  comply, 4/3/2 if unwilling or unable, step 1 if there's an immediate risk to public
  health.
- Later verifications: acceptable moves up one step (NP1 up to 8, NP2 up to 7, NP3 up
  to 6); unacceptable moves down one step (willing and able) or two (unwilling or
  unable), or to step 1 (immediate risk), within NP1 1-7, NP2 1-6, NP3 1-5.

The verifier decides the step. The app suggests the one the rules give and records what
the verifier actually set, so the next verification date is always known.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.user import User
from app.features.compliant.models.verification import ComplianceVerification, ComplianceVerificationAction

PROGRAMMES = ("np1", "np2", "np3")
OUTCOMES = ("acceptable", "unacceptable")
ATTITUDES = ("willing", "unwilling", "immediate_risk")
STEP_MONTHS = {1: 3, 2: 6, 3: 9, 4: 12, 5: 18, 6: 24, 7: 36, 8: None}
MAX_STEP = {"np1": 8, "np2": 7, "np3": 6}  # after acceptable outcomes
MAX_STEP_UNACCEPTABLE = {"np1": 7, "np2": 6, "np3": 5}
INITIAL_UNACCEPTABLE = {"willing": {"np1": 6, "np2": 5, "np3": 4}, "unwilling": {"np1": 4, "np2": 3, "np3": 2}}
REMIND_DAYS = 60
ACTION_REMIND_DAYS = 7


def step_label(step: int) -> str:
    months = STEP_MONTHS[step]
    if months is None:
        return "no further verification"
    if months % 12 == 0:
        years = months // 12
        return "every year" if years == 1 else f"every {years} years"
    return f"every {months} months"


def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(day.day, days[month - 1]))


def allowed_steps(programme: str, outcome: str, initial: bool) -> range:
    if outcome == "acceptable":
        return range(MAX_STEP[programme], MAX_STEP[programme] + 1) if initial else range(2, MAX_STEP[programme] + 1)
    return range(1, MAX_STEP_UNACCEPTABLE[programme] + 1)


def suggest_step(programme: str, outcome: str, initial: bool, attitude: str | None, previous: int | None) -> int:
    """The frequency step the regulations give for this outcome."""
    if outcome == "acceptable":
        if initial:
            return MAX_STEP[programme]
        return min((previous or MAX_STEP[programme]) + 1, MAX_STEP[programme])
    if attitude == "immediate_risk":
        return 1
    if initial:
        return INITIAL_UNACCEPTABLE["unwilling" if attitude == "unwilling" else "willing"][programme]
    current = previous or MAX_STEP[programme]
    return max(1, min(current - (2 if attitude == "unwilling" else 1), MAX_STEP_UNACCEPTABLE[programme]))


def initial_due(programme: str, registered_on: date | None, registered_as: str | None) -> date | None:
    if registered_on is None:
        return None
    if registered_as == "new":
        return registered_on + timedelta(weeks=6)
    return add_months(registered_on, 6 if programme == "np3" else 12)


def settings_for(profile) -> dict:
    settings = (getattr(profile, "settings", None) or {}) if profile is not None else {}
    programme = settings.get("food_control_programme", "np3")
    try:
        registered_on = date.fromisoformat(settings["np_registered_on"]) if settings.get("np_registered_on") else None
    except ValueError:
        registered_on = None
    return {
        "programme": programme if programme in PROGRAMMES else None,
        "registered_on": registered_on,
        "registered_as": settings.get("np_registered_as")
        if settings.get("np_registered_as") in ("new", "existing")
        else None,
    }


def _last(session: Session, org_id: UUID, programme: str) -> ComplianceVerification | None:
    return (
        session.query(ComplianceVerification)
        .filter(ComplianceVerification.org_id == org_id, ComplianceVerification.programme == programme)
        .order_by(ComplianceVerification.verified_on.desc(), ComplianceVerification.created_at.desc())
        .first()
    )


def _clean(value, limit: int) -> str | None:
    text = str(value or "").strip()[:limit]
    return text or None


def record(session: Session, org_id: UUID, profile, data: dict, user_id, today: date) -> ComplianceVerification:
    """Record a verification visit, its outcome, frequency step and corrective actions."""
    cfg = settings_for(profile)
    programme = cfg["programme"]
    if programme is None:
        raise ValueError("Select a national programme in Configuration first")
    try:
        verified_on = date.fromisoformat(str(data.get("verified_on") or ""))
    except ValueError:
        raise ValueError("verified_on must be a date (YYYY-MM-DD)") from None
    if verified_on > today:
        raise ValueError("Record a verification once it has happened")
    verifier = _clean(data.get("verifier_name"), 255)
    if not verifier:
        raise ValueError("Who verified you?")
    outcome = data.get("outcome")
    if outcome not in OUTCOMES:
        raise ValueError("outcome must be acceptable or unacceptable")
    attitude = data.get("attitude") or None
    if outcome == "unacceptable" and attitude not in ATTITUDES:
        raise ValueError("For an unacceptable outcome, say whether the business is willing and able to comply")
    if outcome == "acceptable":
        attitude = None
    last = _last(session, org_id, programme)
    if last is not None and verified_on < last.verified_on:
        raise ValueError(f"A later verification ({last.verified_on.isoformat()}) is already recorded")
    initial = bool(data.get("initial")) if last is None else False
    previous = last.step if last is not None else _int(data.get("previous_step"))
    if previous is not None and previous not in STEP_MONTHS:
        raise ValueError("previous_step must be 1 to 8")
    suggested = suggest_step(programme, outcome, initial, attitude, previous)
    step = _int(data.get("step")) or suggested
    if step not in allowed_steps(programme, outcome, initial):
        allowed = allowed_steps(programme, outcome, initial)
        raise ValueError(f"For this outcome the step must be {allowed.start} to {allowed.stop - 1}")
    months = STEP_MONTHS[step]
    next_due = add_months(verified_on, months) if months else None
    if data.get("next_due"):
        try:
            next_due = date.fromisoformat(str(data["next_due"]))  # the date in the verifier's report
        except ValueError:
            raise ValueError("next_due must be a date (YYYY-MM-DD)") from None
        if next_due <= verified_on:
            raise ValueError("The next verification must be after this one")

    verification = ComplianceVerification(
        org_id=org_id,
        programme=programme,
        verified_on=verified_on,
        verifier_name=verifier,
        verifier_agency=_clean(data.get("verifier_agency"), 255),
        report_reference=_clean(data.get("report_reference"), 255),
        outcome=outcome,
        initial=initial,
        attitude=attitude,
        step=step,
        next_due=next_due,
        notes=_clean(data.get("notes"), 4000),
        created_by_user_id=user_id,
    )
    session.add(verification)
    session.flush()
    staff = {u.id for u in session.query(User.id).filter(User.org_id == org_id, User.is_active.is_(True))}
    for raw in data.get("actions") or []:
        description = _clean(raw.get("description"), 500)
        if not description:
            raise ValueError("Each corrective action needs a description")
        try:
            due_on = date.fromisoformat(str(raw.get("due_on") or ""))
        except ValueError:
            raise ValueError("Each corrective action needs a due date") from None
        owner_id = None
        if raw.get("owner_user_id"):
            try:
                owner_id = UUID(str(raw["owner_user_id"]))
            except ValueError:
                owner_id = None
            if owner_id not in staff:
                raise ValueError("A corrective action's owner must be someone in this organisation")
        owner_name = _clean(raw.get("owner_name"), 255)
        if owner_id is None and owner_name is None:
            raise ValueError("Each corrective action needs an owner")
        session.add(
            ComplianceVerificationAction(
                org_id=org_id,
                verification_id=verification.id,
                description=description,
                owner_user_id=owner_id,
                owner_name=None if owner_id else owner_name,
                due_on=due_on,
            )
        )
    session.flush()
    return verification


def _int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def complete_action(session: Session, org_id: UUID, action_id: UUID, note, user_id, today: date):
    action = (
        session.query(ComplianceVerificationAction)
        .filter(ComplianceVerificationAction.id == action_id, ComplianceVerificationAction.org_id == org_id)
        .one_or_none()
    )
    if action is None:
        return None
    if action.status == "done":
        raise ValueError("This corrective action is already done")
    action.status = "done"
    action.done_on = today
    action.done_note = _clean(note, 500)
    action.done_by_user_id = user_id
    session.flush()
    return action


def status(session: Session, org_id: UUID, profile, today: date) -> dict:
    """Current verification status, next due date and corrective actions."""
    cfg = settings_for(profile)
    programme = cfg["programme"]
    base = {
        "programme": programme,
        "registered_on": cfg["registered_on"].isoformat() if cfg["registered_on"] else None,
        "registered_as": cfg["registered_as"],
        "steps": {str(k): step_label(k) for k in STEP_MONTHS},
    }
    if programme is None:
        return {**base, "state": "not_applicable", "verifications": [], "actions": []}
    rows = (
        session.query(ComplianceVerification)
        .filter(ComplianceVerification.org_id == org_id, ComplianceVerification.programme == programme)
        .order_by(ComplianceVerification.verified_on.desc(), ComplianceVerification.created_at.desc())
        .limit(50)
        .all()
    )
    actions = (
        session.query(ComplianceVerificationAction)
        .join(ComplianceVerification, ComplianceVerification.id == ComplianceVerificationAction.verification_id)
        .filter(ComplianceVerificationAction.org_id == org_id, ComplianceVerification.programme == programme)
        .order_by(ComplianceVerificationAction.status.desc(), ComplianceVerificationAction.due_on.asc())
        .limit(200)
        .all()
    )
    owner_ids = {a.owner_user_id for a in actions if a.owner_user_id}
    names = (
        {
            u.id: " ".join(p for p in (u.first_name, u.last_name) if p) or u.email
            for u in session.query(User).filter(User.org_id == org_id, User.id.in_(owner_ids)).all()
        }
        if owner_ids
        else {}
    )
    staff = [
        {"id": str(u.id), "name": " ".join(p for p in (u.first_name, u.last_name) if p) or u.email}
        for u in session.query(User)
        .filter(User.org_id == org_id, User.is_active.is_(True))
        .order_by(User.first_name, User.last_name, User.email)
        .limit(200)
        .all()
    ]
    last = rows[0] if rows else None
    if last is None:
        next_due = initial_due(programme, cfg["registered_on"], cfg["registered_as"])
        state = "initial_due" if next_due else "not_recorded"
        step = None
    else:
        next_due = last.next_due
        step = last.step
        state = "no_further" if next_due is None else "scheduled"
    overdue = bool(next_due and today > next_due)
    open_actions = [a for a in actions if a.status == "open"]
    return {
        **base,
        "state": "overdue" if overdue else state,
        "current_step": step,
        "frequency": step_label(step) if step else None,
        "next_due": next_due.isoformat() if next_due else None,
        "days_until": (next_due - today).days if next_due else None,
        "overdue": overdue,
        "last": _verification_json(last) if last else None,
        "staff": staff,
        "open_actions": len(open_actions),
        "overdue_actions": sum(1 for a in open_actions if a.due_on < today),
        "verifications": [_verification_json(v) for v in rows],
        "actions": [
            {
                "id": str(a.id),
                "verification_id": str(a.verification_id),
                "description": a.description,
                "owner": names.get(a.owner_user_id) if a.owner_user_id else a.owner_name,
                "due_on": a.due_on.isoformat(),
                "status": a.status,
                "overdue": a.status == "open" and a.due_on < today,
                "done_on": a.done_on.isoformat() if a.done_on else None,
                "done_note": a.done_note,
            }
            for a in actions
        ],
    }


def _verification_json(v: ComplianceVerification) -> dict:
    return {
        "id": str(v.id),
        "verified_on": v.verified_on.isoformat(),
        "verifier_name": v.verifier_name,
        "verifier_agency": v.verifier_agency,
        "report_reference": v.report_reference,
        "outcome": v.outcome,
        "initial": v.initial,
        "attitude": v.attitude,
        "step": v.step,
        "frequency": step_label(v.step),
        "next_due": v.next_due.isoformat() if v.next_due else None,
        "notes": v.notes,
    }


def alerts(current: dict, today: date) -> list[dict]:
    """Next verification coming up (60 days) or overdue; corrective actions due within a week."""
    out = []
    label = (current.get("programme") or "").upper()
    if current.get("next_due"):
        due = date.fromisoformat(current["next_due"])
        if today >= due - timedelta(days=REMIND_DAYS):
            first = current.get("last") is None
            out.append(
                {
                    "id": f"verification-due-{current['next_due']}",
                    "title": f"{label} {'initial ' if first else ''}verification due {due.strftime('%-d %b %Y')}",
                    "description": (
                        f"{'Overdue: ' if today > due else ''}Book your verifier and check your evidence is current."
                    ),
                    "due_date": current["next_due"],
                    "href": "/compliant/nz-alcohol/food-safety#verification",
                    "action_label": "Open verification",
                }
            )
    for action in current.get("actions", []):
        if action["status"] != "open":
            continue
        due = date.fromisoformat(action["due_on"])
        if today >= due - timedelta(days=ACTION_REMIND_DAYS):
            out.append(
                {
                    "id": f"verification-action-{action['id']}",
                    "title": f"Corrective action due {due.strftime('%-d %b %Y')}: {action['description'][:80]}",
                    "description": f"{'Overdue. ' if today > due else ''}Owner: {action['owner'] or 'unassigned'}.",
                    "due_date": action["due_on"],
                    "href": "/compliant/nz-alcohol/food-safety#verification",
                    "action_label": "Open verification",
                }
            )
    return out


def milestone(current: dict) -> dict | None:
    """The always-on-screen line for the shared Dashboard's module summary."""
    if current.get("state") in (None, "not_applicable", "not_recorded"):
        return None
    detail = []
    if current.get("frequency"):
        detail.append(current["frequency"])
    if current.get("open_actions"):
        n = current["open_actions"]
        detail.append(f"{n} open corrective action{'s' if n != 1 else ''}")
    return {
        "label": "Next verification" if current.get("state") != "initial_due" else "Initial verification",
        "date": current.get("next_due"),
        "overdue": bool(current.get("overdue")),
        "detail": " · ".join(detail) or None,
    }
