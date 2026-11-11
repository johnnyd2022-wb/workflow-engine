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


def classify_line(line: PurchaseLine, account: XeroAccount) -> str:
    """The one place a line's treatment is decided. 8.1b: the account's effective treatment.
    8.1c adds rule and manual precedence here, so nothing else may write ``treatment``."""
    return account.treatment


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
        if row.id is not None and row.treatment != before:
            changed.append(row)
    db.flush()
    for row in changed:
        reclassify_account_lines(db, org_id, row)
    return existing


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
    for ln in lines:
        ln.treatment = classify_line(ln, account)
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


def upsert_bank_transactions(
    db: Session,
    org_id: UUID,
    transactions: Iterable,
    *,
    accounts: dict[str, XeroAccount],
    base_currency: str,
    start_date: date | None,
    xero_tenant_id: str | None,
) -> dict:
    """Upsert SPEND / RECEIVE bank transactions. ``start_date`` filters only transactions not
    already stored (a stored one edited to an earlier date is still updated)."""
    by_code: dict[str, list[XeroAccount]] = {}
    for acct in accounts.values():
        if acct.code:
            by_code.setdefault(acct.code, []).append(acct)
    stats = {"documents": 0, "lines": 0, "skipped_lines": 0, "skipped_documents": 0}
    now = utc_now()

    for t in transactions or []:
        kind = STORED_TYPES.get((_text(getattr(t, "type", None)) or "").upper())
        external_id = getattr(t, "bank_transaction_id", None)
        if kind is None or not external_id:
            stats["skipped_documents"] += 1
            continue
        external_id = str(external_id)
        doc = (
            db.query(PurchaseDocument)
            .filter(
                PurchaseDocument.org_id == org_id,
                PurchaseDocument.source == SOURCE,
                PurchaseDocument.external_id == external_id,
            )
            .with_for_update()
            .one_or_none()
        )
        when = getattr(t, "date", None)
        if isinstance(when, datetime):
            when = when.date()
        if doc is None and start_date is not None and (when is None or when < start_date):
            stats["skipped_documents"] += 1
            continue

        sign = Decimal("-1") if kind == "refund" else Decimal("1")
        currency = (_text(getattr(t, "currency_code", None)) or base_currency or "")[:3]
        fx_status = "ok" if currency == base_currency else "needs_rate"
        amount_types = _text(getattr(t, "line_amount_types", None)) or "Exclusive"

        incoming = []
        for position, li in enumerate(getattr(t, "line_items", None) or [], start=1):
            acct = _resolve_account(li, accounts, by_code)
            if acct is None or acct.account_class != "EXPENSE" or acct.treatment is None:
                stats["skipped_lines"] += 1
                continue
            line_amount = _dec(getattr(li, "line_amount", None)) or Decimal("0")
            tax = Decimal("0") if amount_types == "NoTax" else (_dec(getattr(li, "tax_amount", None)) or Decimal("0"))
            ex_tax = line_amount - tax if amount_types == "Inclusive" else line_amount
            if fx_status == "ok":
                ex_base, tax_base = _money(sign * ex_tax), _money(sign * tax)
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

        if doc is None and not incoming:
            stats["skipped_documents"] += 1
            continue
        if doc is None:
            doc = PurchaseDocument(org_id=org_id, source=SOURCE, external_id=external_id)
            db.add(doc)
        contact = getattr(t, "contact", None)
        bank = getattr(t, "bank_account", None)
        doc.xero_tenant_id = xero_tenant_id
        doc.kind = kind
        doc.payee_name = getattr(contact, "name", None) if contact is not None else None
        contact_id = getattr(contact, "contact_id", None) if contact is not None else None
        doc.xero_contact_id = str(contact_id) if contact_id else None
        doc.document_date = when
        doc.reference = getattr(t, "reference", None)
        doc.currency_code = currency or None
        doc.currency_rate = _dec(getattr(t, "currency_rate", None))
        doc.fx_status = fx_status
        status = (_text(getattr(t, "status", None)) or "").upper()
        doc.status = "voided" if status in ("DELETED", "VOIDED") else "active"
        doc.bank_account_name = getattr(bank, "name", None) if bank is not None else None
        doc.is_reconciled = getattr(t, "is_reconciled", None)
        updated = getattr(t, "updated_date_utc", None)
        if isinstance(updated, datetime) and updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        doc.external_updated_at = updated if isinstance(updated, datetime) else None
        doc.last_synced_at = now
        db.flush()

        live = {
            ln.line_key: ln
            for ln in db.query(PurchaseLine)
            .filter(
                PurchaseLine.org_id == org_id,
                PurchaseLine.document_id == doc.id,
                PurchaseLine.superseded_at.is_(None),
            )
            .with_for_update()
        }
        keep: set[str] = set()
        for row in incoming:
            acct = row.pop("_account")
            current = live.get(row["line_key"])
            positional = row["line_key"].startswith("pos:")
            if current is not None and positional and current.fingerprint != row["fingerprint"]:
                current.superseded_at = now  # a different line now sits at this position
                db.flush()
                current = None
            if current is None:
                current = PurchaseLine(org_id=org_id, document_id=doc.id, **row, treatment="not_stock")
                db.add(current)
            else:
                for name, value in row.items():
                    setattr(current, name, value)
            current.treatment = classify_line(current, acct)
            keep.add(row["line_key"])
            stats["lines"] += 1
        for key, ln in live.items():
            if key not in keep:
                ln.superseded_at = now
        db.flush()

        totals = (
            db.query(PurchaseLine.amount_ex_tax, PurchaseLine.tax_amount)
            .filter(
                PurchaseLine.org_id == org_id,
                PurchaseLine.document_id == doc.id,
                PurchaseLine.superseded_at.is_(None),
            )
            .all()
        )
        if any(r[0] is None for r in totals):
            doc.total_ex_tax, doc.total_tax = None, None
        else:
            doc.total_ex_tax = sum((r[0] for r in totals), Decimal("0"))
            doc.total_tax = sum((r[1] or Decimal("0") for r in totals), Decimal("0"))
        if incoming:
            stats["documents"] += 1
    db.flush()
    logger.info("purchase_sources_upserted", org_id=str(org_id), **stats)
    return stats
