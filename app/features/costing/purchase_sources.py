"""Purchases from accounting software, normalised (live-cogs 8.1b).

The purchase-side mirror of ``crm/services/sales_sources.py``: the Xero sync hands this module
SDK objects (Accounts, BankTransactions) and it upserts ``xero_accounts`` / ``purchase_documents``
/ ``purchase_lines`` in one shape. Spec .agents/specs/live-cogs.md, "8.1b build contract".
Nothing here commits: the sync owns the unit of work.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.costing.models import PurchaseDocument, PurchaseLine
from app.features.crm.models.xero_account import TREATMENTS, XeroAccount
from app.observability import get_logger

logger = get_logger(__name__)

NZ = ZoneInfo("Pacific/Auckland")
MONEY = Decimal("0.0001")
SOURCE = "xero_bank"
SOURCE_BILL = "xero_bill"  # 8.1f-1
SOURCE_BILL_CREDIT = "xero_bill_credit"
STORED_TYPES = {"SPEND": "spend", "RECEIVE": "refund"}
_DUTY = ("excise", "duty")
_OVERHEAD = ("rent", "wage", "salar", "power", "light", "heating", "fuel", "vehicle", "freight", "courier", "postage")


class PurchaseSourceError(ValueError):
    pass


def nz_today() -> date:
    return datetime.now(NZ).date()


def _value(raw):
    """SDK enums carry ``.value``; plain strings don't. Never ``str()`` an enum."""
    return getattr(raw, "value", raw)


def _text(raw) -> str | None:
    value = _value(raw)
    return None if value is None else str(value)


def _dec(raw) -> Decimal | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))  # a float's str() is its shortest repr: 0.3 -> "0.3"
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() else None


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _words(name: str | None) -> list[str]:
    return [w for w in re.split(r"[^0-9a-z]+", (name or "").casefold()) if w]


def default_treatment(account_type: str | None, account_class: str | None, name: str | None) -> str | None:
    """Spec "Account default keywords". None = not an expense account: its lines aren't stored."""
    if (account_class or "").upper() != "EXPENSE":
        return None
    words = _words(name)
    if any(w.startswith(k) for w in words for k in _DUTY):
        return "duty"
    if any(w.startswith(k) for w in words for k in _OVERHEAD):
        return "overhead"
    return "stock" if (account_type or "").upper() == "DIRECTCOSTS" else "not_stock"


def classify_line(line: PurchaseLine, account: XeroAccount, *, payee: str | None = None, rules=None) -> str:
    """The one place a line's treatment is decided: the winning purchase rule (8.1c-2), else the
    account's effective treatment. Sets ``treatment`` and ``treatment_rule_id``."""
    from app.features.costing.rules import winner

    rule = winner(rules or [], line.account_code, payee, line.description) if rules else None
    line.treatment = rule.treatment if rule is not None else account.treatment
    line.treatment_rule_id = rule.id if rule is not None else None
    return line.treatment


# --- accounts ----------------------------------------------------------------------------------


def sync_accounts(db: Session, org_id: UUID, accounts: Iterable) -> dict[str, XeroAccount]:
    """Upsert the chart of accounts (never touching ``treatment_override``); re-classify lines
    whose account's default changed. Returns accounts by Xero id."""
    existing = {a.xero_account_id: a for a in db.query(XeroAccount).filter(XeroAccount.org_id == org_id)}
    now = utc_now()
    changed: list[XeroAccount] = []
    for raw in accounts or []:
        xero_id = getattr(raw, "account_id", None)
        if not xero_id:
            continue
        xero_id = str(xero_id)
        row = existing.get(xero_id)
        if row is None:
            row = XeroAccount(org_id=org_id, xero_account_id=xero_id)
            db.add(row)
            existing[xero_id] = row
        before = row.treatment
        row.code = getattr(raw, "code", None)
        row.name = getattr(raw, "name", None)
        row.type = _text(getattr(raw, "type", None))
        row.account_class = _text(getattr(raw, "_class", None))
        row.status = _text(getattr(raw, "status", None))
        row.default_treatment = default_treatment(row.type, row.account_class, row.name)
        row.last_synced_at = now
        if row.id is not None and row.treatment != before and row.default_treatment is not None:
            changed.append(row)
    db.flush()
    for row in changed:
        reclassify_account_lines(db, org_id, row)
    ineligible = [row for row in existing.values() if row.default_treatment is None and row.id is not None]
    if ineligible:  # not an expense account (an override doesn't make it one)
        retire_account_lines(db, org_id, *ineligible)
    return existing


def retire_account_lines(db: Session, org_id: UUID, *accounts: XeroAccount) -> int:
    """An account that is no longer an expense account: its live lines are superseded, as if
    Xero had dropped them (the one seam 8.1c extends to send recorded lines to review)."""
    now = utc_now()
    lines = (
        db.query(PurchaseLine)
        .filter(
            PurchaseLine.org_id == org_id,
            PurchaseLine.account_id.in_([a.id for a in accounts]),
            PurchaseLine.superseded_at.is_(None),
        )
        .all()
    )
    from app.features.costing.actions import lock_lines, on_line_gone

    for ln in lock_lines(db, org_id, [ln.id for ln in lines]):
        if ln.superseded_at is not None:
            continue
        ln.superseded_at = now
        on_line_gone(db, ln)
    db.flush()
    return len(lines)


def reclassify_account_lines(db: Session, org_id: UUID, account: XeroAccount) -> int:
    if account.treatment is None:
        return 0
    lines = (
        db.query(PurchaseLine)
        .filter(
            PurchaseLine.org_id == org_id,
            PurchaseLine.account_id == account.id,
            PurchaseLine.superseded_at.is_(None),
        )
        .all()
    )
    from app.features.costing.actions import lock_lines, on_line_treatment_changed
    from app.features.costing.models import PurchaseDocument
    from app.features.costing.rules import active_rules

    rules = active_rules(db, org_id)
    payees = (
        dict(
            db.query(PurchaseDocument.id, PurchaseDocument.payee_name).filter(
                PurchaseDocument.org_id == org_id, PurchaseDocument.id.in_({ln.document_id for ln in lines})
            )
        )
        if lines
        else {}
    )
    for ln in lock_lines(db, org_id, [ln.id for ln in lines]):
        if ln.superseded_at is not None:
            continue
        before = ln.treatment
        classify_line(ln, account, payee=payees.get(ln.document_id), rules=rules)
        on_line_treatment_changed(db, ln, before, ln.treatment)
    db.flush()
    return len(lines)


def list_accounts(db: Session, org_id: UUID) -> list[dict]:
    from sqlalchemy import func

    counts = dict(
        db.query(PurchaseLine.account_id, func.count(PurchaseLine.id))
        .filter(PurchaseLine.org_id == org_id, PurchaseLine.superseded_at.is_(None))
        .group_by(PurchaseLine.account_id)
        .all()
    )
    rows = (
        db.query(XeroAccount)
        .filter(XeroAccount.org_id == org_id, XeroAccount.account_class == "EXPENSE")
        .order_by(XeroAccount.code, XeroAccount.name)
        .all()
    )
    return [
        {
            "xero_account_id": a.xero_account_id,
            "code": a.code,
            "name": a.name,
            "type": a.type,
            "default_treatment": a.default_treatment,
            "treatment_override": a.treatment_override,
            "treatment": a.treatment,
            "live_lines": int(counts.get(a.id, 0)),
        }
        for a in rows
    ]


def set_account_treatment(db: Session, org_id: UUID, xero_account_id: str, treatment: str | None) -> XeroAccount:
    if treatment is not None and treatment not in TREATMENTS:
        raise PurchaseSourceError(f"treatment must be one of {', '.join(TREATMENTS)} or null")
    row = (
        db.query(XeroAccount)
        .filter(
            XeroAccount.org_id == org_id,
            XeroAccount.xero_account_id == str(xero_account_id),
            XeroAccount.account_class == "EXPENSE",
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise LookupError("Account not found")
    row.treatment_override = treatment
    db.flush()
    reclassify_account_lines(db, org_id, row)
    return row


# --- bank transactions ------------------------------------------------------------------------------


def _canonical_text(text) -> str | None:
    if text is None:
        return None
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(text))).strip()


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normal = value.normalize()
    return format(normal, "f") if normal == normal.to_integral() else str(normal)


def fingerprint(row: dict) -> str:
    payload = {
        "account_id": str(row["account_id"]) if row.get("account_id") else None,
        "amount_ex_tax": _canonical_decimal(row.get("amount_ex_tax")),
        "description": _canonical_text(row.get("description")),
        "item_code": _canonical_text(row.get("item_code")),
        "quantity": _canonical_decimal(row.get("quantity")),
        "source_unit_amount": _canonical_decimal(row.get("source_unit_amount")),
        "tax_amount": _canonical_decimal(row.get("tax_amount")),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _resolve_account(li, by_id: dict[str, XeroAccount], by_code: dict[str, list[XeroAccount]]):
    account_id = getattr(li, "account_id", None)
    if account_id:
        return by_id.get(str(account_id))
    code = getattr(li, "account_code", None)
    matches = by_code.get(code, []) if code else []
    return matches[0] if len(matches) == 1 else None


# --- source adapters: a Xero object -> one header the shared upsert understands ----------------

BILL_ACTIVE = ("AUTHORISED", "PAID")
BILL_GONE = ("VOIDED", "DELETED")


def _header(obj, *, source, kind, external_id, status, reference, bank_account_name=None, is_reconciled=None):
    """``status``: active | voided | draft (draft: not stored; a stored one is treated as voided)."""
    return {
        "source": source,
        "kind": kind,
        "external_id": str(external_id) if external_id else None,
        "status": status,
        "date": getattr(obj, "date", None),
        "contact": getattr(obj, "contact", None),
        "reference": reference,
        "currency": _text(getattr(obj, "currency_code", None)),
        "rate": getattr(obj, "currency_rate", None),
        "amount_types": _text(getattr(obj, "line_amount_types", None)) or "Exclusive",
        "lines": getattr(obj, "line_items", None) or [],
        "bank_account_name": bank_account_name,
        "is_reconciled": is_reconciled,
        "updated": getattr(obj, "updated_date_utc", None),
    }


def _bank_header(t) -> dict | None:
    kind = STORED_TYPES.get((_text(getattr(t, "type", None)) or "").upper())
    if kind is None:
        return None
    bank = getattr(t, "bank_account", None)
    gone = (_text(getattr(t, "status", None)) or "").upper() in ("DELETED", "VOIDED")
    return _header(
        t,
        source=SOURCE,
        kind=kind,
        external_id=getattr(t, "bank_transaction_id", None),
        status="voided" if gone else "active",
        reference=getattr(t, "reference", None),
        bank_account_name=getattr(bank, "name", None) if bank is not None else None,
        is_reconciled=getattr(t, "is_reconciled", None),
    )


def _bill_status(raw) -> str:
    status = (_text(raw) or "").upper()
    if status in BILL_ACTIVE:
        return "active"
    if status in BILL_GONE:
        return "voided"
    return "draft"  # DRAFT, SUBMITTED: not a bill yet


def _bill_reference(label: str, number, reference) -> str | None:
    parts = [f"{label} {number}" if number else None, reference or None]
    text = " · ".join(p for p in parts if p)
    return text[:255] or None


def _bill_header(inv) -> dict | None:
    if (_text(getattr(inv, "type", None)) or "").upper() != "ACCPAY":
        return None
    return _header(
        inv,
        source=SOURCE_BILL,
        kind="spend",
        external_id=getattr(inv, "invoice_id", None),
        status=_bill_status(getattr(inv, "status", None)),
        reference=_bill_reference("Bill", getattr(inv, "invoice_number", None), getattr(inv, "reference", None)),
    )


def _credit_header(note) -> dict | None:
    if (_text(getattr(note, "type", None)) or "").upper() != "ACCPAYCREDIT":
        return None
    return _header(
        note,
        source=SOURCE_BILL_CREDIT,
        kind="refund",
        external_id=getattr(note, "credit_note_id", None),
        status=_bill_status(getattr(note, "status", None)),
        reference=_bill_reference(
            "Credit", getattr(note, "credit_note_number", None), getattr(note, "reference", None)
        ),
    )


def upsert_bank_transactions(db: Session, org_id: UUID, transactions: Iterable, **kwargs) -> dict:
    """Upsert SPEND / RECEIVE bank transactions. ``start_date`` filters only transactions not
    already stored (a stored one edited to an earlier date is still updated)."""
    return _upsert_documents(db, org_id, [_bank_header(t) for t in transactions or []], **kwargs)


def upsert_bills(db: Session, org_id: UUID, bills: Iterable, credit_notes: Iterable, **kwargs) -> dict:
    """Upsert supplier bills (ACCPAY) and supplier credits (ACCPAYCREDIT), 8.1f-1: the same
    path as bank transactions, with ``source`` saying where each came from."""
    headers = [_bill_header(b) for b in bills or []] + [_credit_header(c) for c in credit_notes or []]
    return _upsert_documents(db, org_id, headers, **kwargs)


def _upsert_documents(
    db: Session,
    org_id: UUID,
    headers: list,
    *,
    accounts: dict[str, XeroAccount],
    base_currency: str,
    start_date: date | None,
    xero_tenant_id: str | None,
) -> dict:
    by_code: dict[str, list[XeroAccount]] = {}
    for acct in accounts.values():
        if acct.code:
            by_code.setdefault(acct.code, []).append(acct)
    stats = {"documents": 0, "lines": 0, "skipped_lines": 0, "skipped_documents": 0, "auto_recorded": 0}
    newly_created: list[tuple[PurchaseLine, PurchaseDocument]] = []
    now = utc_now()
    from app.features.costing.rules import active_rules

    rules = active_rules(db, org_id)

    for h in headers:
        if h is None or not h["external_id"]:
            stats["skipped_documents"] += 1
            continue
        kind, external_id, source = h["kind"], h["external_id"], h["source"]
        doc = (
            # nosemgrep: sqlalchemy-query-in-for-loop — per-document upsert under that document's row lock; a Xero page is at most 100 transactions.
            db.query(PurchaseDocument)
            .filter(
                PurchaseDocument.org_id == org_id,
                PurchaseDocument.source == source,
                PurchaseDocument.external_id == external_id,
            )
            .with_for_update()
            .one_or_none()
        )
        when = h["date"]
        if isinstance(when, datetime):
            when = when.date()
        if doc is None and start_date is not None and (when is None or when < start_date):
            stats["skipped_documents"] += 1
            continue

        sign = Decimal("-1") if kind == "refund" else Decimal("1")
        currency = (h["currency"] or base_currency or "")[:3]
        fx_status = "ok" if currency == base_currency else "needs_rate"
        amount_types = h["amount_types"]

        incoming = []
        for position, li in enumerate(h["lines"], start=1):
            acct = _resolve_account(li, accounts, by_code)
            if acct is None or acct.account_class != "EXPENSE" or acct.treatment is None:
                stats["skipped_lines"] += 1
                continue
            # Unknown stays unknown: a missing or malformed amount is never priced as $0.
            line_amount = _dec(getattr(li, "line_amount", None))
            tax = Decimal("0") if amount_types == "NoTax" else _dec(getattr(li, "tax_amount", None))
            if line_amount is None:
                ex_tax = None
            elif amount_types == "Inclusive":
                ex_tax = None if tax is None else line_amount - tax
            else:
                ex_tax = line_amount
            if fx_status == "ok":
                ex_base = None if ex_tax is None else _money(sign * ex_tax)
                tax_base = None if tax is None else _money(sign * tax)
            else:
                ex_base, tax_base = None, None
            line_item_id = getattr(li, "line_item_id", None)
            row = {
                "line_key": str(line_item_id) if line_item_id else f"pos:{position}",
                "position": position,
                "account_id": acct.id,
                "description": getattr(li, "description", None),
                "item_code": getattr(li, "item_code", None),
                "quantity": _dec(getattr(li, "quantity", None)),
                "source_unit_amount": _dec(getattr(li, "unit_amount", None)),
                "account_code": acct.code,
                "account_name": acct.name,
                "amount_ex_tax": ex_base,
                "tax_amount": tax_base,
            }
            row["fingerprint"] = fingerprint(row)
            row["_account"] = acct
            incoming.append(row)

        # A draft is not stored; a stored document that went back to draft is no longer real.
        voided = h["status"] in ("voided", "draft")
        if doc is None and (not incoming or voided):
            stats["skipped_documents"] += 1  # never stored, and nothing to keep
            continue
        if doc is None:
            doc = PurchaseDocument(org_id=org_id, source=source, external_id=external_id)
            db.add(doc)
        contact = h["contact"]
        doc.xero_tenant_id = xero_tenant_id
        doc.kind = kind
        doc.payee_name = getattr(contact, "name", None) if contact is not None else None
        contact_id = getattr(contact, "contact_id", None) if contact is not None else None
        doc.xero_contact_id = str(contact_id) if contact_id else None
        doc.document_date = when
        doc.reference = h["reference"]
        doc.currency_code = currency or None
        doc.currency_rate = _dec(h["rate"])
        doc.fx_status = fx_status
        was_active = doc.status in (None, "active")  # a new document has nothing to restore
        doc.status = "voided" if voided else "active"
        doc.bank_account_name = h["bank_account_name"]
        doc.is_reconciled = h["is_reconciled"]
        updated = h["updated"]
        if isinstance(updated, datetime) and updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        doc.external_updated_at = updated if isinstance(updated, datetime) else None
        doc.last_synced_at = now
        db.flush()
        from app.features.costing.actions import on_line_amount_changed, on_line_gone, on_line_treatment_changed

        if voided:
            # Xero may send a voided transaction with no (or fewer) lines; its stored lines are
            # what was bought and stay as they were. Only the change to voided sends what was
            # recorded against them to review (a later re-sync of the void must not re-flag it).
            if was_active:
                for ln in (
                    db.query(PurchaseLine)
                    .filter(
                        PurchaseLine.org_id == org_id,
                        PurchaseLine.document_id == doc.id,
                        PurchaseLine.superseded_at.is_(None),
                    )
                    .with_for_update()
                    .all()
                ):
                    on_line_gone(db, ln, cause="void")
                db.flush()
            stats["documents"] += 1
            continue

        live = {
            ln.line_key: ln
            # nosemgrep: sqlalchemy-query-in-for-loop — per-document upsert under that document's row lock; a Xero page is at most 100 transactions.
            for ln in db.query(PurchaseLine)
            .filter(
                PurchaseLine.org_id == org_id,
                PurchaseLine.document_id == doc.id,
                PurchaseLine.superseded_at.is_(None),
            )
            .with_for_update()
        }
        keep: set[str] = set()
        voided_amounts: dict = {}  # restoring: amount changes are applied after the allocations return
        for row in incoming:
            acct = row.pop("_account")
            current = live.get(row["line_key"])
            positional = row["line_key"].startswith("pos:")
            if current is not None and positional and current.fingerprint != row["fingerprint"]:
                current.superseded_at = now  # a different line now sits at this position
                on_line_gone(db, current)
                db.flush()
                current = None
            if current is None:
                current = PurchaseLine(org_id=org_id, document_id=doc.id, **row, treatment="not_stock")
                db.add(current)
                classify_line(current, acct, payee=doc.payee_name, rules=rules)
                newly_created.append((current, doc))
            else:
                before_amount = current.amount_ex_tax
                before_treatment = current.treatment
                for name, value in row.items():
                    setattr(current, name, value)
                classify_line(current, acct, payee=doc.payee_name, rules=rules)
                db.flush()
                if was_active:
                    on_line_amount_changed(db, current, before_amount)
                else:
                    voided_amounts[current.id] = before_amount
                on_line_treatment_changed(db, current, before_treatment, current.treatment)
            keep.add(row["line_key"])
            stats["lines"] += 1
        for key, ln in live.items():
            if key not in keep:
                ln.superseded_at = now
                on_line_gone(db, ln)
        db.flush()
        if not was_active:  # voided before, active again: after the incoming values are applied
            from app.features.costing.actions import on_document_restored

            for ln in (
                db.query(PurchaseLine)
                .filter(
                    PurchaseLine.org_id == org_id,
                    PurchaseLine.document_id == doc.id,
                    PurchaseLine.superseded_at.is_(None),
                )
                .all()
            ):
                on_document_restored(db, ln, old_amount=voided_amounts.get(ln.id))
            db.flush()

        totals = (
            # nosemgrep: sqlalchemy-query-in-for-loop — per-document upsert under that document's row lock; a Xero page is at most 100 transactions.
            db.query(PurchaseLine.amount_ex_tax, PurchaseLine.tax_amount)
            .filter(
                PurchaseLine.org_id == org_id,
                PurchaseLine.document_id == doc.id,
                PurchaseLine.superseded_at.is_(None),
            )
            .all()
        )
        if any(r[0] is None or r[1] is None for r in totals):
            doc.total_ex_tax, doc.total_tax = None, None
        else:
            doc.total_ex_tax = sum((r[0] for r in totals), Decimal("0"))
            doc.total_tax = sum((r[1] for r in totals), Decimal("0"))
        if incoming:
            stats["documents"] += 1
    db.flush()
    if newly_created:
        from app.features.costing import actions
        from app.features.costing.rules import winner

        for new_line, new_doc in newly_created:
            rule = winner(rules, new_line.account_code, new_doc.payee_name, new_line.description)
            if (
                rule is None
                or not rule.auto_record
                or rule.treatment != "stock"
                or new_line.treatment != "stock"
                or new_doc.kind != "spend"
                or new_doc.status != "active"
                or new_line.superseded_at is not None
                or new_line.amount_ex_tax is None
                or new_line.state != "open"
            ):
                continue
            try:
                with db.begin_nested():
                    suggestion = actions.prefill(
                        db,
                        new_line,
                        new_doc,
                        actions.open_amount(db, new_line),
                        rules=rules,
                        history={},
                    )
                    if suggestion is None or suggestion["source"] != "rule":
                        continue
                    actions.record(
                        db,
                        org_id,
                        new_line.id,
                        suggestion["rows"],
                        rest="later",
                        user_id=None,
                    )
                stats["auto_recorded"] += 1
            except Exception as error:
                logger.warning(
                    "purchase_auto_record_failed",
                    org_id=str(org_id),
                    line_id=str(new_line.id),
                    error_type=type(error).__name__,
                )
    logger.info("purchase_sources_upserted", org_id=str(org_id), **stats)
    return stats
