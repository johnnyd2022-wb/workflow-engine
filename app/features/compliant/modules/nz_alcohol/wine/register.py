"""Wine compliance register (docs/wine-compliance-plan.md §6): the WSMP checklist, problem
reports, label approvals and the export register, all as ordinary compliance records.

No new tables: every entry is a `ComplianceRecord` under its framework and control, so it
gets the evidence files, owners, due dates and audit history Customs and NP already use.
Where production already holds the fact (intake declarations, the trace, recall drills,
label checks), the checklist reads it live instead of asking for a record.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.features.compliant.models import ComplianceRecord
from app.features.compliant.modules.nz_alcohol.catalogue import framework_applies, framework_by_slug

WINE_FRAMEWORKS: Final = ("wine-standards", "wine-export", "swnz", "organic-wine")
LIVE_CONTROLS: Final = {
    "grape-intake",
    "inputs-processing-aids",
    "lab-release",
    "trace-mass-balance",
    "recall",
    "label-claims",
    "wsmp-registration",
    "small-winemaker-exemption",
}
SETTING_FLAGS: Final = ("wine_exporter", "wine_swnz", "wine_organic")
EXPORT_LEVY_PER_L: Final = Decimal("0.0037")  # Wine Amendment Regulations 2026, from 1 Jul 2026
EXPORT_LEVY_FREE_L: Final = Decimal(200000)
TRADE_SAMPLE_MAX_L: Final = Decimal(110)
SMALL_TRADE_MAX_L: Final = Decimal(27)
ELIGIBLE_FOR: Final = {"packaged": timedelta(days=730), "bulk": timedelta(days=91)}
DUE_SOON_DAYS: Final = 30
CONSIGNMENT_KINDS: Final = ("commercial", "trade_sample", "small_trade")
RELEASED: Final = "Yes, analysis checked"


class RegisterError(ValueError):
    """A refusal with a message the page can show as-is."""


def _text(data: dict, key: str, label: str, *, required: bool = True, max_len: int = 200) -> str | None:
    value = str((data or {}).get(key) or "").strip()
    if required and not value:
        raise RegisterError(f"{label} is required")
    if len(value) > max_len:
        raise RegisterError(f"{label} is too long")
    return value or None


def _day(data: dict, key: str, label: str, *, required: bool = False) -> date | None:
    raw = (data or {}).get(key)
    if not raw:
        if required:
            raise RegisterError(f"{label} is required")
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise RegisterError(f"{label} must be a date") from None


def _litres(data: dict, key: str, label: str) -> Decimal:
    try:
        value = Decimal(str((data or {}).get(key)).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise RegisterError(f"{label} must be a number of litres") from None
    if not value.is_finite() or value <= 0 or value > Decimal(10_000_000):
        raise RegisterError(f"{label} must be more than 0 litres")
    return value


def _records(session: Session, org_id: UUID, framework: str, control: str | None = None) -> list[ComplianceRecord]:
    query = session.query(ComplianceRecord).filter(
        ComplianceRecord.org_id == org_id, ComplianceRecord.framework_slug == framework
    )
    if control:
        query = query.filter(ComplianceRecord.control_id == control)
    return query.order_by(ComplianceRecord.created_at.desc()).all()


def _add(session: Session, org_id: UUID, user_id, **fields) -> ComplianceRecord:
    record = ComplianceRecord(org_id=org_id, created_by_user_id=user_id, owner_user_id=user_id, **fields)
    session.add(record)
    session.flush()
    return record


def record_dict(row: ComplianceRecord) -> dict:
    return {
        "id": str(row.id),
        "framework": row.framework_slug,
        "control": row.control_id,
        "type": row.record_type,
        "status": row.status,
        "title": row.title,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "evidence_reference": row.evidence_reference,
        "details": row.details or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------------------


def applicable_frameworks(settings: dict) -> list[dict]:
    out = []
    for slug in WINE_FRAMEWORKS:
        framework = framework_by_slug(slug)
        if framework and framework_applies(framework["applies_to"], settings, None):
            out.append(framework)
    return out


def _record_status(rows: list[ComplianceRecord], today: date) -> tuple[str, str, ComplianceRecord | None]:
    live = [r for r in rows if r.status != "superseded"]
    if not live:
        return "missing", "Nothing recorded yet", None
    latest = live[0]
    if latest.status == "open":
        due = latest.due_date
        if due and due < today:
            return "overdue", f"Open, was due {due:%-d %b %Y}", latest
        return "due", f"Open{f', due {due:%-d %b %Y}' if due else ''}", latest
    due = latest.due_date
    if due and due < today:
        return "overdue", f"Next one was due {due:%-d %b %Y}", latest
    if due and (due - today).days <= DUE_SOON_DAYS:
        return "due", f"Next due {due:%-d %b %Y}", latest
    when = latest.created_at.date() if latest.created_at else today
    return "ok", f"Recorded {when:%-d %b %Y}" + (f", next due {due:%-d %b %Y}" if due else ""), latest


def checklist(session: Session, org_id: UUID, settings: dict, live: dict, today: date) -> list[dict]:
    """One group per applicable framework; each control says where it stands and why."""
    plan_mode = ((settings.get("wine_plan") or {}).get("mode")) or None
    groups = []
    for framework in applicable_frameworks(settings):
        rows_by_control: dict[str, list[ComplianceRecord]] = {}
        for row in _records(session, org_id, framework["slug"]):
            rows_by_control.setdefault(row.control_id, []).append(row)
        items = []
        for control_id, text in framework["controls"]:
            if framework["slug"] == "wine-standards":
                if control_id == "small-winemaker-exemption" and plan_mode != "exempt":
                    continue
                if control_id in ("wsmp-registration", "wsmp-verification", "wsmp-changes") and plan_mode == "exempt":
                    continue
            if framework["slug"] == "wine-standards" and control_id in live:
                status, detail = live[control_id]
                source = "production"
                latest = None
            else:
                status, detail, latest = _record_status(rows_by_control.get(control_id, []), today)
                # Checks with their own form: the export register and the problem report.
                source = {
                    ("wine-export", "batch-eligibility"): "eligibility",
                    ("wine-export", "customs-export-clearance"): "consignment",
                    ("wine-standards", "nonconformance"): "problem",
                }.get((framework["slug"], control_id), "record")
                if source == "problem" and status == "missing":
                    status, detail = "ok", "No problems reported"
            items.append(
                {
                    "framework": framework["slug"],
                    "control": control_id,
                    "text": text,
                    "status": status,
                    "detail": detail,
                    "source": source,
                    "latest": record_dict(latest) if latest else None,
                }
            )
        order = {"overdue": 0, "missing": 1, "due": 2, "review": 3, "ok": 4}
        items.sort(key=lambda i: order.get(i["status"], 5))
        groups.append(
            {
                "framework": framework["slug"],
                "name": framework["name"],
                "source_url": framework["source_url"],
                "items": items,
            }
        )
    return groups


def add_control_record(session: Session, org_id: UUID, user_id, settings: dict, data: dict) -> ComplianceRecord:
    framework_slug = _text(data, "framework", "Framework")
    framework = next((f for f in applicable_frameworks(settings) if f["slug"] == framework_slug), None)
    if framework is None:
        raise RegisterError("That framework doesn't apply to your business")
    control = _text(data, "control", "Check")
    if control not in {c for c, _ in framework["controls"]}:
        raise RegisterError("Unknown check for this framework")
    record_type = {
        "staff-hygiene": "competency",
        "nonconformance": "incident",
        "wsmp-changes": "lodgement",
        "nzw-levy": "lodgement",
    }.get(control, "attestation")
    return _add(
        session,
        org_id,
        user_id,
        framework_slug=framework_slug,
        control_id=control,
        record_type=record_type,
        status="complete",
        title=_text(data, "title", "What was done", max_len=255),
        period_start=_day(data, "done_on", "Date") or date.today(),
        due_date=_day(data, "next_due", "Next due"),
        evidence_reference=_text(data, "evidence_reference", "Evidence", required=False, max_len=1024),
        source_refs=[],
        details={},
    )


# ---------------------------------------------------------------------------------------
# Problems: CNC / ENC / recall decision -> 24-hour clock and a hold on the wine
# ---------------------------------------------------------------------------------------

PROBLEM_KINDS: Final = {
    "critical": "Critical non-compliance",
    "export": "Export non-compliance",
    "recall": "Decision to recall",
}


def report_problem(session: Session, org_id: UUID, user_id, data: dict, *, now: datetime | None = None) -> dict:
    """Records the problem with a 24-hour MPI notification due, and holds the lot so it can't
    be used, sold or dispatched until someone releases it with a reason."""
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.services import lot_holds

    now = now or datetime.now(UTC)
    kind = (data or {}).get("kind")
    if kind not in PROBLEM_KINDS:
        raise RegisterError("Choose what kind of problem this is")
    what = _text(data, "description", "What happened", max_len=500)
    lot = None
    if (data or {}).get("lot_id"):
        try:
            lot_id = UUID(str(data["lot_id"]))
        except ValueError:
            raise RegisterError("Choose the wine lot affected") from None
        lot = (
            session.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id, InventoryItem.id == lot_id)
            .one_or_none()
        )
        if lot is None:
            raise RegisterError("Choose the wine lot affected")
    record = _add(
        session,
        org_id,
        user_id,
        framework_slug="wine-standards",
        control_id="nonconformance",
        record_type="incident",
        status="open",
        title=f"{PROBLEM_KINDS[kind]}: {what}"[:255],
        period_start=now.date(),
        due_date=(now + timedelta(hours=24)).date(),
        source_refs=[str(lot.id)] if lot else [],
        details={
            "kind": kind,
            "notify_mpi_by": (now + timedelta(hours=24)).isoformat(),
            "lot_id": str(lot.id) if lot else None,
        },
    )
    hold = None
    if lot is not None:
        try:
            hold = lot_holds.place_hold(session, org_id, lot.id, f"{PROBLEM_KINDS[kind]}: {what}"[:300], user_id)
        except ValueError:
            hold = None  # already held: the existing hold keeps it out of use
    return {
        "record": record_dict(record),
        "notify_mpi_by": (now + timedelta(hours=24)).isoformat(),
        "held": bool(hold),
        "lot": {"id": str(lot.id), "name": lot.name} if lot else None,
    }


# ---------------------------------------------------------------------------------------
# Label approval: fingerprinted, lapses when the facts behind it change
# ---------------------------------------------------------------------------------------


def label_fingerprint(preflight: dict) -> str:
    facts = sorted(
        (i["key"], i["status"], i["detail"]) for i in preflight.get("items", []) if i["key"] != "label-approval"
    )
    return hashlib.sha256(json.dumps(facts, ensure_ascii=False).encode()).hexdigest()[:20]


def latest_label_approvals(session: Session, org_id: UUID) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in _records(session, org_id, "wine-standards", "label-claims"):
        lot = (row.details or {}).get("lot_id")
        if lot and lot not in out:
            out[lot] = {"fingerprint": (row.details or {}).get("fingerprint"), "at": row.created_at, "title": row.title}
    return out


def approve_label(session: Session, org_id: UUID, user_id, lot: dict, preflight: dict, data: dict) -> ComplianceRecord:
    if preflight.get("status") == "missing":
        raise RegisterError("Fill in the missing records before approving this label")
    version = _text(data, "label_version", "Label artwork version", max_len=120)
    return _add(
        session,
        org_id,
        user_id,
        framework_slug="wine-standards",
        control_id="label-claims",
        record_type="attestation",
        status="complete",
        title=f"Label {version} approved for {lot['name']}"[:255],
        period_start=date.today(),
        evidence_reference=_text(data, "evidence_reference", "Artwork file", required=False, max_len=1024),
        source_refs=[lot["id"]],
        details={"lot_id": lot["id"], "fingerprint": label_fingerprint(preflight), "label_version": version},
    )


# ---------------------------------------------------------------------------------------
# Export register: eligibility per batch, consignments against it, levy for the year
# ---------------------------------------------------------------------------------------


def _levy_year(day: date) -> tuple[date, date]:
    start = date(day.year if day.month >= 7 else day.year - 1, 7, 1)
    return start, date(start.year + 1, 6, 30)


def export_register(session: Session, org_id: UUID, today: date) -> dict:
    eligibilities = [
        r for r in _records(session, org_id, "wine-export", "batch-eligibility") if r.status != "superseded"
    ]
    consignments = [
        r for r in _records(session, org_id, "wine-export", "customs-export-clearance") if r.status != "superseded"
    ]
    shipped: dict[str, Decimal] = {}
    for row in consignments:
        key = (row.details or {}).get("eligibility_id")
        if key and (row.details or {}).get("kind") != "trade_sample":
            shipped[key] = shipped.get(key, Decimal(0)) + Decimal(str((row.details or {}).get("litres") or 0))
    rows = []
    for row in eligibilities:
        d = row.details or {}
        eligible = Decimal(str(d.get("eligible_litres") or 0))
        used = shipped.get(str(row.id), Decimal(0))
        expires = date.fromisoformat(d["expires_on"]) if d.get("expires_on") else None
        rows.append(
            {
                **record_dict(row),
                "lot_id": d.get("lot_id"),
                "lot_name": d.get("lot_name"),
                "eligible_litres": float(eligible),
                "exported_litres": float(used),
                "remaining_litres": float(max(Decimal(0), eligible - used)),
                "expires_on": expires.isoformat() if expires else None,
                "current": bool(expires and expires >= today and eligible > used),
            }
        )
    start, end = _levy_year(today)
    year_l = sum(
        (
            Decimal(str((r.details or {}).get("litres") or 0))
            for r in consignments
            if r.period_start and start <= r.period_start <= end and (r.details or {}).get("kind") == "commercial"
        ),
        Decimal(0),
    )
    levy = max(Decimal(0), year_l - EXPORT_LEVY_FREE_L) * EXPORT_LEVY_PER_L
    return {
        "eligibilities": rows,
        "consignments": [record_dict(r) for r in consignments[:100]],
        "levy": {
            "year_start": start.isoformat(),
            "year_end": end.isoformat(),
            "litres_exported": float(year_l),
            "levy_free_litres": float(EXPORT_LEVY_FREE_L),
            "levy_due": float(levy.quantize(Decimal("0.01"))),
            "rate_per_litre": float(EXPORT_LEVY_PER_L),
        },
    }


def add_eligibility(
    session: Session, org_id: UUID, user_id, settings: dict, lot: dict, data: dict, today: date
) -> ComplianceRecord:
    if ((settings.get("wine_plan") or {}).get("mode")) == "exempt":
        raise RegisterError("Wine made under the small winemaker exemption can't be exported")
    if not settings.get("wine_exporter"):
        raise RegisterError("Turn on exporting in your wine plan first")
    if lot.get("role") == "bottle" and lot.get("released") is False:
        raise RegisterError("Release this lot for sale at bottling before applying for export eligibility")
    form = (data or {}).get("form")
    if form not in ELIGIBLE_FOR:
        raise RegisterError("Say whether the wine is packaged or bulk")
    granted = _day(data, "granted_on", "Eligibility date", required=True)
    if granted > today:
        raise RegisterError("Eligibility can't be dated in the future")
    reference = _text(data, "ees_reference", "MPI eligibility (EES) reference", max_len=120)
    litres = _litres(data, "eligible_litres", "Eligible volume")
    markets = [m.strip() for m in str((data or {}).get("markets") or "").split(",") if m.strip()][:20]
    expires = granted + ELIGIBLE_FOR[form]
    return _add(
        session,
        org_id,
        user_id,
        framework_slug="wine-export",
        control_id="batch-eligibility",
        record_type="attestation",
        status="complete",
        title=f"Export eligibility {reference} for {lot['name']}"[:255],
        period_start=granted,
        due_date=expires,
        evidence_reference=reference,
        source_refs=[lot["id"]],
        details={
            "lot_id": lot["id"],
            "lot_name": lot["name"],
            "form": form,
            "eligible_litres": str(litres),
            "expires_on": expires.isoformat(),
            "markets": markets,
        },
    )


def add_consignment(
    session: Session, org_id: UUID, user_id, settings: dict, data: dict, today: date
) -> ComplianceRecord:
    if ((settings.get("wine_plan") or {}).get("mode")) == "exempt":
        raise RegisterError("Wine made under the small winemaker exemption can't be exported")
    kind = (data or {}).get("kind")
    if kind not in CONSIGNMENT_KINDS:
        raise RegisterError("Choose the kind of consignment")
    litres = _litres(data, "litres", "Volume")
    shipped_on = _day(data, "shipped_on", "Ship date", required=True)
    market = _text(data, "market", "Destination market", max_len=80)
    consignee = _text(data, "consignee", "Consignee", max_len=200)
    if kind == "trade_sample" and litres > TRADE_SAMPLE_MAX_L:
        raise RegisterError("Trade samples are exempt only up to 110 L in one consignment")
    if kind == "small_trade" and litres > SMALL_TRADE_MAX_L:
        raise RegisterError("The small trade consignment exemption is up to 27 L")
    customs_ref = _text(data, "customs_entry", "Customs export entry", required=kind == "commercial", max_len=120)
    eligibility = None
    if kind != "trade_sample":
        try:
            eligibility_id = UUID(str((data or {}).get("eligibility_id")))
        except ValueError:
            raise RegisterError("Choose the export eligibility this wine ships under") from None
        register = {row["id"]: row for row in export_register(session, org_id, today)["eligibilities"]}
        eligibility = register.get(str(eligibility_id))
        if eligibility is None:
            raise RegisterError("Choose the export eligibility this wine ships under")
        if eligibility["expires_on"] and shipped_on > date.fromisoformat(eligibility["expires_on"]):
            raise RegisterError(f"That eligibility expired on {eligibility['expires_on']}: re-apply before shipping")
        markets = eligibility["details"].get("markets") or []
        if markets and market not in markets:
            raise RegisterError(f"That eligibility doesn't cover {market}")
        if litres > Decimal(str(eligibility["remaining_litres"])):
            raise RegisterError(f"Only {eligibility['remaining_litres']:g} L of that eligibility is left")
    if kind == "trade_sample" and str((data or {}).get("not_for_sale_marked") or "").lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        raise RegisterError("Trade sample bottles must be marked “not for sale”")
    return _add(
        session,
        org_id,
        user_id,
        framework_slug="wine-export",
        control_id="customs-export-clearance",
        record_type="lodgement",
        status="complete",
        title=f"{litres:g} L to {consignee}, {market}"[:255],
        period_start=shipped_on,
        evidence_reference=customs_ref,
        source_refs=[eligibility["lot_id"]] if eligibility and eligibility.get("lot_id") else [],
        details={
            "kind": kind,
            "litres": str(litres),
            "market": market,
            "consignee": consignee,
            "eligibility_id": eligibility["id"] if eligibility else None,
        },
    )
