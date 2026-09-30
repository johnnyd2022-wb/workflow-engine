"""Liquor licensing register (plan 2.5): licences, managers, checks and the refusal log.

Obligations under the Sale and Supply of Alcohol Act 2012 that this tracks:

- A licence renewal must be filed at least 20 working days before the licence expires
  (s 127(2)); a late renewal needs a waiver, and none can be filed once the licence has
  expired. Working days are counted as the Act defines them (``nz_calendar``).
- A manager's certificate renewal must be filed before the certificate expires.
- Annual fees fall due each year the licence is held (Sale and Supply of Alcohol (Fees)
  Regulations 2013); councils invoice them, so the date is whatever the invoice says.
- Special licences cover a named event on set dates, with a manager on duty.

The licence's own conditions (sale and delivery hours, displays) come from the DLC and
are recorded as given. Nothing here is legal advice; each org confirms its obligations
against its licence and the DLC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.user import User
from app.features.compliant.models import ComplianceRecord
from app.features.compliant.models.licensing import LicensingLogEntry, LiquorLicence, ManagerCertificate
from app.features.compliant.modules.nz_alcohol.catalogue import framework_by_slug
from app.features.compliant.modules.nz_alcohol.nz_calendar import working_days_before

FRAMEWORK = "liquor-licence"
KINDS = {"on": "On-licence", "off": "Off-licence", "club": "Club licence", "special": "Special licence"}
ENDORSEMENTS = {"s40_remote_sales": "Remote sales (s 40)"}
LOG_KINDS = {
    "id_refusal": "Refused: no acceptable ID / under 18",
    "intoxication_refusal": "Refused: intoxicated",
    "incident": "Incident",
    "controlled_purchase": "Controlled purchase operation",
}
RENEWAL_WORKING_DAYS = 20
RENEWAL_REMIND_DAYS = 60  # before the last day to file
MANAGER_REMIND_DAYS = 60
FEE_REMIND_DAYS = 30
EVENT_REMIND_DAYS = 14
CHECK_REVIEW_SOON_DAYS = 30
REGISTER_CONTROLS = ("licence-scope", "licence-renewal", "certified-manager")


def _clean(value, limit: int) -> str | None:
    text = str(value or "").strip()[:limit]
    return text or None


def _date(value, field: str, required: bool = False) -> date | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is required")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{field} must be a date (YYYY-MM-DD)") from None


def _time(value, field: str) -> time | None:
    if value in (None, ""):
        return None
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{field} must be a time (HH:MM)") from None


# --- licences -----------------------------------------------------------------------------------


def assign_licence_site(session, licence, data):
    """Premises are explicit registrations; free-text addresses never establish scope."""
    org = (
        session.query(Organisation)
        .filter(Organisation.id == licence.org_id)
        .with_for_update(read=True)
        .populate_existing()
        .one()
    )
    if "site_id" not in data:
        if org.multiple_sites_enabled and licence.site_id is None:
            raise ValueError("Choose the site covered by this liquor licence")
        return
    value = data["site_id"]
    if value in (None, ""):
        if org.multiple_sites_enabled:
            raise ValueError("Choose the site covered by this liquor licence")
        licence.site_id = None
        return
    try:
        site_id = UUID(str(value))
    except (ValueError, TypeError):
        raise ValueError("Invalid licence site") from None
    site = (
        session.query(Site)
        .filter(Site.org_id == licence.org_id, Site.id == site_id)
        .with_for_update(read=True)
        .populate_existing()
        .one_or_none()
    )
    if site is None or not site.is_active:
        raise ValueError("Choose an active site belonging to this business")
    if not org.multiple_sites_enabled and not site.is_default:
        raise ValueError("Multiple sites must be switched on to select an additional site")
    licence.site_id = site.id


def apply_licence(licence: LiquorLicence, data: dict) -> LiquorLicence:
    kind = data.get("kind", licence.kind)
    if kind not in KINDS:
        raise ValueError("kind must be on, off, club or special")
    licence.kind = kind
    endorsements = data.get("endorsements", licence.endorsements or [])
    if not isinstance(endorsements, list) or any(e not in ENDORSEMENTS for e in endorsements):
        raise ValueError("Unknown endorsement")
    licence.endorsements = sorted(set(endorsements))
    for field, limit in (("licence_number", 100), ("issuing_dlc", 255), ("premises", 500), ("sale_hours", 255)):
        if field in data:
            setattr(licence, field, _clean(data[field], limit))
    if "conditions" in data:
        licence.conditions = _clean(data["conditions"], 4000)
    for field in ("issued_on", "expires_on", "annual_fee_due_on", "event_starts_on", "event_ends_on"):
        if field in data:
            setattr(licence, field, _date(data[field], field))
    for field in ("delivery_hours_start", "delivery_hours_end"):
        if field in data:
            setattr(licence, field, _time(data[field], field))
    for field in ("event_name", "manager_on_duty"):
        if field in data:
            setattr(licence, field, _clean(data[field], 255))
    if (licence.delivery_hours_start is None) != (licence.delivery_hours_end is None):
        raise ValueError("Give both the start and end of the delivery hours")
    if licence.issued_on and licence.expires_on and licence.expires_on <= licence.issued_on:
        raise ValueError("The expiry date must be after the issue date")
    if kind == "special":
        if not licence.event_name or not licence.event_starts_on:
            raise ValueError("A special licence needs the event and its first day")
        licence.event_ends_on = licence.event_ends_on or licence.event_starts_on
        if licence.event_ends_on < licence.event_starts_on:
            raise ValueError("The event can't end before it starts")
        licence.expires_on = licence.expires_on or licence.event_ends_on
    elif not licence.expires_on:
        raise ValueError("Add the licence's expiry date")
    return licence


def renewal_file_by(licence: LiquorLicence) -> date | None:
    if licence.kind == "special" or licence.expires_on is None:
        return None
    return working_days_before(licence.expires_on, RENEWAL_WORKING_DAYS)


def licence_state(licence: LiquorLicence, today: date) -> dict:
    """Where the licence stands, and the next date that matters."""
    if licence.status != "current":
        return {"state": "ended", "label": "Ended", "next_date": None}
    if licence.kind == "special":
        if licence.event_ends_on and today > licence.event_ends_on:
            return {"state": "ended", "label": "Event over", "next_date": None}
        if licence.event_starts_on and licence.event_starts_on <= today:
            return {"state": "in_use", "label": "Event on now", "next_date": licence.event_ends_on}
        if not licence.manager_on_duty:
            return {"state": "attention", "label": "Name the manager on duty", "next_date": licence.event_starts_on}
        return {"state": "ok", "label": "Ready for the event", "next_date": licence.event_starts_on}
    file_by = renewal_file_by(licence)
    if licence.renewal_lodged_on:
        if today > licence.expires_on:
            return {
                "state": "ok",
                "label": "Renewal lodged; the licence continues until it's decided",
                "next_date": None,
            }
        return {"state": "ok", "label": f"Renewal lodged {licence.renewal_lodged_on.isoformat()}", "next_date": None}
    if today > licence.expires_on:
        return {"state": "expired", "label": "Expired: selling alcohol now needs a new licence", "next_date": None}
    if today > file_by:
        return {
            "state": "late",
            "label": "Past the 20-working-day renewal deadline: file now with a waiver request",
            "next_date": licence.expires_on,
        }
    if today >= file_by - timedelta(days=RENEWAL_REMIND_DAYS):
        return {"state": "due", "label": "Renewal due", "next_date": file_by}
    return {"state": "ok", "label": "Current", "next_date": file_by}


def licence_json(licence: LiquorLicence, today: date) -> dict:
    fee_due = licence.annual_fee_due_on
    return {
        "id": str(licence.id),
        "site_id": str(licence.site_id) if licence.site_id else None,
        "kind": licence.kind,
        "kind_label": KINDS[licence.kind],
        "licence_number": licence.licence_number,
        "issuing_dlc": licence.issuing_dlc,
        "premises": licence.premises,
        "endorsements": list(licence.endorsements or []),
        "endorsement_labels": [ENDORSEMENTS[e] for e in licence.endorsements or [] if e in ENDORSEMENTS],
        "issued_on": _iso(licence.issued_on),
        "expires_on": _iso(licence.expires_on),
        "renewal_file_by": _iso(renewal_file_by(licence)),
        "renewal_lodged_on": _iso(licence.renewal_lodged_on),
        "sale_hours": licence.sale_hours,
        "delivery_hours_start": licence.delivery_hours_start.strftime("%H:%M")
        if licence.delivery_hours_start
        else None,
        "delivery_hours_end": licence.delivery_hours_end.strftime("%H:%M") if licence.delivery_hours_end else None,
        "conditions": licence.conditions,
        "annual_fee_due_on": _iso(fee_due),
        "annual_fee_overdue": bool(fee_due and today > fee_due),
        "event_name": licence.event_name,
        "event_starts_on": _iso(licence.event_starts_on),
        "event_ends_on": _iso(licence.event_ends_on),
        "manager_on_duty": licence.manager_on_duty,
        "status": licence.status,
        **{f"state_{k}": v for k, v in _state_json(licence_state(licence, today)).items()},
    }


def _state_json(state: dict) -> dict:
    return {"code": state["state"], "label": state["label"], "next_date": _iso(state["next_date"])}


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def lodge_renewal(licence: LiquorLicence, lodged_on: date, today: date) -> None:
    if licence.kind == "special":
        raise ValueError("Special licences aren't renewed; add one for the next event")
    if lodged_on > today:
        raise ValueError("The renewal can't be lodged in the future")
    if lodged_on > licence.expires_on:
        raise ValueError("A renewal can't be filed once the licence has expired")
    licence.renewal_lodged_on = lodged_on


def renewal_granted(licence: LiquorLicence, new_expiry: date) -> None:
    if new_expiry <= licence.expires_on:
        raise ValueError("The renewed licence must expire after the current one")
    licence.expires_on = new_expiry
    licence.renewal_lodged_on = None


def pay_annual_fee(licence: LiquorLicence) -> None:
    if licence.annual_fee_due_on is None:
        raise ValueError("Add the annual fee's due date first")
    due = licence.annual_fee_due_on
    try:
        licence.annual_fee_due_on = due.replace(year=due.year + 1)
    except ValueError:  # 29 February
        licence.annual_fee_due_on = due.replace(year=due.year + 1, day=28)


# --- managers ----------------------------------------------------------------------------------


def apply_manager(session: Session, org_id: UUID, cert: ManagerCertificate, data: dict) -> ManagerCertificate:
    if data.get("user_id"):
        try:
            user_id = UUID(str(data["user_id"]))
        except ValueError:
            raise ValueError("Unknown person") from None
        user = session.query(User).filter(User.id == user_id, User.org_id == org_id).one_or_none()
        if user is None:
            raise ValueError("The certificate holder must be someone in this organisation, or give a name")
        cert.user_id = user.id
        cert.holder_name = " ".join(p for p in (user.first_name, user.last_name) if p) or user.email
    elif "holder_name" in data:
        cert.user_id = None
        cert.holder_name = _clean(data.get("holder_name"), 255)
    if not cert.holder_name:
        raise ValueError("Whose certificate is it?")
    if "certificate_number" in data:
        cert.certificate_number = _clean(data["certificate_number"], 100)
    if not cert.certificate_number:
        raise ValueError("Add the certificate number")
    if "issuing_dlc" in data:
        cert.issuing_dlc = _clean(data["issuing_dlc"], 255)
    if "issued_on" in data:
        cert.issued_on = _date(data["issued_on"], "issued_on")
    if "expires_on" in data or cert.expires_on is None:
        cert.expires_on = _date(data.get("expires_on"), "expires_on", required=True)
    if cert.issued_on and cert.expires_on <= cert.issued_on:
        raise ValueError("The expiry date must be after the issue date")
    return cert


def manager_state(cert: ManagerCertificate, today: date) -> dict:
    if not cert.active:
        return {"state": "ended", "label": "No longer with us", "next_date": None}
    if cert.renewal_lodged_on:
        return {"state": "ok", "label": f"Renewal lodged {cert.renewal_lodged_on.isoformat()}", "next_date": None}
    if today > cert.expires_on:
        return {"state": "expired", "label": "Expired: can't act as a duty manager", "next_date": None}
    if today >= cert.expires_on - timedelta(days=MANAGER_REMIND_DAYS):
        return {"state": "due", "label": "Renewal due: file before it expires", "next_date": cert.expires_on}
    return {"state": "ok", "label": "Current", "next_date": cert.expires_on}


def manager_json(cert: ManagerCertificate, today: date) -> dict:
    return {
        "id": str(cert.id),
        "user_id": str(cert.user_id) if cert.user_id else None,
        "holder_name": cert.holder_name,
        "certificate_number": cert.certificate_number,
        "issuing_dlc": cert.issuing_dlc,
        "issued_on": _iso(cert.issued_on),
        "expires_on": _iso(cert.expires_on),
        "renewal_lodged_on": _iso(cert.renewal_lodged_on),
        "active": cert.active,
        **{f"state_{k}": v for k, v in _state_json(manager_state(cert, today)).items()},
    }


def lodge_manager_renewal(cert: ManagerCertificate, lodged_on: date, today: date) -> None:
    if lodged_on > today:
        raise ValueError("The renewal can't be lodged in the future")
    if lodged_on > cert.expires_on:
        raise ValueError("A certificate renewal must be filed before it expires")
    cert.renewal_lodged_on = lodged_on


def manager_renewed(cert: ManagerCertificate, new_expiry: date) -> None:
    if new_expiry <= cert.expires_on:
        raise ValueError("The renewed certificate must expire after the current one")
    cert.expires_on = new_expiry
    cert.renewal_lodged_on = None


# --- log -----------------------------------------------------------------------------------------


def new_log_entry(org_id: UUID, data: dict, user_id, now: datetime) -> LicensingLogEntry:
    kind = data.get("kind")
    if kind not in LOG_KINDS:
        raise ValueError("kind must be id_refusal, intoxication_refusal, incident or controlled_purchase")
    raw = data.get("occurred_at")
    try:
        occurred = datetime.fromisoformat(str(raw)) if raw else now
    except ValueError:
        raise ValueError("occurred_at must be a date and time") from None
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=now.tzinfo or UTC)
    if occurred > now + timedelta(minutes=5):
        raise ValueError("That hasn't happened yet")
    description = _clean(data.get("description"), 4000)
    if not description:
        raise ValueError("Say what happened")
    return LicensingLogEntry(
        org_id=org_id,
        kind=kind,
        occurred_at=occurred,
        location=_clean(data.get("location"), 255),
        description=description,
        action_taken=_clean(data.get("action_taken"), 4000),
        staff_name=_clean(data.get("staff_name"), 255),
        reference=_clean(data.get("reference"), 255),
        created_by_user_id=user_id,
    )


def log_json(entry: LicensingLogEntry) -> dict:
    return {
        "id": str(entry.id),
        "kind": entry.kind,
        "kind_label": LOG_KINDS.get(entry.kind, entry.kind),
        "occurred_at": entry.occurred_at.isoformat(),
        "location": entry.location,
        "description": entry.description,
        "action_taken": entry.action_taken,
        "staff_name": entry.staff_name,
        "reference": entry.reference,
    }


# --- checks with evidence ----------------------------------------------------------------------


def derived_control_state(session: Session, org_id: UUID, control_id: str, today: date) -> dict | None:
    """Controls the registers prove: the licence scope, its renewal, and certified managers."""
    if control_id not in REGISTER_CONTROLS:
        return None
    licences = session.query(LiquorLicence).filter(LiquorLicence.org_id == org_id).limit(100).all()
    live = [lic for lic in licences if licence_state(lic, today)["state"] not in ("ended",)]
    if control_id == "licence-scope":
        if not live:
            return {"state": "setup", "reason": "Add your licence to the licensing register"}
        return {"state": "compliant", "reason": f"{len(live)} licence(s) in the register"}
    if control_id == "licence-renewal":
        standing = [lic for lic in live if lic.kind != "special"]
        if not standing:
            return None
        bad = [lic for lic in standing if licence_state(lic, today)["state"] in ("late", "expired")]
        if bad:
            return {"state": "attention", "reason": licence_state(bad[0], today)["label"]}
        return {"state": "compliant", "reason": "Renewal dates tracked in the licensing register"}
    managers = (
        session.query(ManagerCertificate)
        .filter(ManagerCertificate.org_id == org_id, ManagerCertificate.active.is_(True))
        .limit(200)
        .all()
    )
    if not managers:
        return None
    current = [m for m in managers if manager_state(m, today)["state"] != "expired"]
    if not current:
        return {"state": "attention", "reason": "Every manager's certificate in the register has expired"}
    return {"state": "compliant", "reason": f"{len(current)} current manager's certificate(s)"}


def checks(session: Session, org_id: UUID, today: date) -> list[dict]:
    """Each licensing check with its latest record, review date and state."""
    framework = framework_by_slug(FRAMEWORK)
    records = (
        session.query(ComplianceRecord)
        .filter(ComplianceRecord.org_id == org_id, ComplianceRecord.framework_slug == FRAMEWORK)
        .order_by(ComplianceRecord.created_at.desc())
        .limit(500)
        .all()
    )
    latest: dict = {}
    for record in records:
        if record.status == "superseded":
            continue
        latest.setdefault(record.control_id, record)
    out = []
    for control_id, description in framework["controls"]:
        derived = derived_control_state(session, org_id, control_id, today)
        record = latest.get(control_id)
        if derived is not None:  # the register is the proof
            state, reason = derived["state"], derived["reason"]
        elif record is None:
            state, reason = "missing", "No record yet"
        elif record.status in ("open", "failed"):
            state, reason = "attention", "Open or failed record"
        elif record.due_date and record.due_date < today:
            state, reason = "overdue", f"Review overdue since {record.due_date.isoformat()}"
        elif record.due_date and record.due_date <= today + timedelta(days=CHECK_REVIEW_SOON_DAYS):
            state, reason = "due", f"Review due {record.due_date.isoformat()}"
        else:
            state, reason = "current", "Current"
        out.append(
            {
                "control_id": control_id,
                "description": description,
                "from_register": control_id in REGISTER_CONTROLS,
                "state": state,
                "reason": reason,
                "latest": {
                    "title": record.title,
                    "recorded_on": record.created_at.date().isoformat(),
                    "evidence_reference": record.evidence_reference,
                    "review_due": _iso(record.due_date),
                    "status": record.status,
                }
                if record
                else None,
            }
        )
    return out


# --- overview, alerts and the inspector pack ----------------------------------------------------


def overview(session: Session, org_id: UUID, today: date, now: datetime | None = None) -> dict:
    licences = (
        session.query(LiquorLicence)
        .filter(LiquorLicence.org_id == org_id)
        .order_by(LiquorLicence.status.asc(), LiquorLicence.expires_on.asc())
        .limit(100)
        .all()
    )
    managers = (
        session.query(ManagerCertificate)
        .filter(ManagerCertificate.org_id == org_id)
        .order_by(ManagerCertificate.active.desc(), ManagerCertificate.expires_on.asc())
        .limit(200)
        .all()
    )
    log = (
        session.query(LicensingLogEntry)
        .filter(LicensingLogEntry.org_id == org_id)
        .order_by(LicensingLogEntry.occurred_at.desc())
        .limit(200)
        .all()
    )
    staff = [
        {"id": str(u.id), "name": " ".join(p for p in (u.first_name, u.last_name) if p) or u.email}
        for u in session.query(User)
        .filter(User.org_id == org_id, User.is_active.is_(True))
        .order_by(User.first_name, User.last_name, User.email)
        .limit(200)
        .all()
    ]
    sites = session.query(Site).filter(Site.org_id == org_id).order_by(Site.name).all()
    names = {site.id: site.name for site in sites}
    org = session.query(Organisation).filter(Organisation.id == org_id).one()
    return {
        "multiple_sites_enabled": bool(org.multiple_sites_enabled),
        "sites": [
            {"id": str(site.id), "name": site.name}
            for site in sites
            if site.is_active and (org.multiple_sites_enabled or site.is_default)
        ],
        "licences": [{**licence_json(lic, today), "site_name": names.get(lic.site_id)} for lic in licences],
        "managers": [manager_json(m, today) for m in managers],
        "log": [log_json(e) for e in log],
        "checks": checks(session, org_id, today),
        "staff": staff,
        # lists, not objects: JSON responses sort keys, and the order matters in a picker
        "kinds": [{"value": k, "label": v} for k, v in KINDS.items()],
        "endorsements": [{"value": k, "label": v} for k, v in ENDORSEMENTS.items()],
        "log_kinds": [{"value": k, "label": v} for k, v in LOG_KINDS.items()],
    }


def alerts(session: Session, org_id: UUID, today: date) -> list[dict]:
    """Nothing lapses unnoticed: renewals, certificates, annual fees, events and check reviews."""
    out = []
    href = "/compliant/nz-alcohol/licensing"
    licences = (
        session.query(LiquorLicence)
        .filter(LiquorLicence.org_id == org_id, LiquorLicence.status == "current")
        .limit(100)
        .all()
    )
    for lic in licences:
        st = licence_state(lic, today)
        name = f"{KINDS[lic.kind]} {lic.licence_number or ''}".strip()
        if st["state"] in ("due", "late", "expired"):
            file_by = renewal_file_by(lic)
            out.append(
                {
                    "id": f"licence-renewal-{lic.id}-{lic.expires_on}",
                    "title": f"{name}: file the renewal by {file_by.strftime('%-d %b %Y')}"
                    if st["state"] == "due"
                    else f"{name}: {st['label']}",
                    "description": f"Expires {lic.expires_on.strftime('%-d %b %Y')}. Renewals are due at least 20 "
                    "working days before expiry.",
                    "due_date": _iso(file_by),
                    "href": href,
                    "action_label": "Open licensing",
                }
            )
        if lic.annual_fee_due_on and today >= lic.annual_fee_due_on - timedelta(days=FEE_REMIND_DAYS):
            out.append(
                {
                    "id": f"licence-fee-{lic.id}-{lic.annual_fee_due_on}",
                    "title": f"{name}: annual fee due {lic.annual_fee_due_on.strftime('%-d %b %Y')}",
                    "description": ("Overdue. " if today > lic.annual_fee_due_on else "")
                    + "Pay the council's annual fee invoice, then mark it paid.",
                    "due_date": _iso(lic.annual_fee_due_on),
                    "href": href,
                    "action_label": "Open licensing",
                }
            )
        if (
            st["state"] == "attention"
            and lic.event_starts_on
            and today >= lic.event_starts_on - timedelta(days=EVENT_REMIND_DAYS)
        ):
            out.append(
                {
                    "id": f"special-licence-manager-{lic.id}",
                    "title": f"{lic.event_name}: name the manager on duty",
                    "description": f"The event starts {lic.event_starts_on.strftime('%-d %b %Y')}.",
                    "due_date": _iso(lic.event_starts_on),
                    "href": href,
                    "action_label": "Open licensing",
                }
            )
    managers = (
        session.query(ManagerCertificate)
        .filter(ManagerCertificate.org_id == org_id, ManagerCertificate.active.is_(True))
        .limit(200)
        .all()
    )
    for cert in managers:
        st = manager_state(cert, today)
        if st["state"] in ("due", "expired"):
            out.append(
                {
                    "id": f"manager-certificate-{cert.id}-{cert.expires_on}",
                    "title": f"{cert.holder_name}'s manager's certificate "
                    + (
                        "has expired"
                        if st["state"] == "expired"
                        else f"expires {cert.expires_on.strftime('%-d %b %Y')}"
                    ),
                    "description": st["label"] + ".",
                    "due_date": _iso(cert.expires_on),
                    "href": href,
                    "action_label": "Open licensing",
                }
            )
    for check in checks(session, org_id, today):
        if check["state"] in ("due", "overdue") and not check["from_register"]:
            out.append(
                {
                    "id": f"licensing-check-{check['control_id']}-{check['latest']['review_due']}",
                    "title": f"Licensing check: {check['description'][:90]}",
                    "description": check["reason"] + ".",
                    "due_date": check["latest"]["review_due"],
                    "href": href,
                    "action_label": "Open licensing",
                }
            )
    return out


def training_records(session: Session, org_id: UUID) -> list[ComplianceRecord]:
    """The shared staff training register (competency records, including NP3's)."""
    return (
        session.query(ComplianceRecord)
        .filter(ComplianceRecord.org_id == org_id, ComplianceRecord.record_type == "competency")
        .order_by(ComplianceRecord.created_at.desc())
        .limit(500)
        .all()
    )
