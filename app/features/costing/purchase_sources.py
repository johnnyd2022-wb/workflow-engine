"""Purchases from accounting software, in one shape whatever the source (live-cogs 8.1b).

The mirror of ``app/features/crm/services/sales_sources.py``. Xero is the only source today: its
bank transactions (card and bank "spend money" / "receive money") are normalised into
``purchase_documents`` / ``purchase_lines`` here, in the org's base currency and excluding GST.
To add another source, write a class with ``name`` and ``ingest()`` and add it to
``PURCHASE_SOURCES``.

Spec .agents/specs/live-cogs.md: "Xero sync changes", "When Xero changes later" and the 8.1b
decisions (B1-B9). This module owns the *line* side of "changes later": the line's amount,
review reason and superseded marker. What a change means for the purchase's allocations is 8.1c's,
reached through ``hooks``. Pulling a record twice is harmless: changes are found by comparing the
stored line with the incoming one, never by timestamps.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.costing import treatments
from app.features.costing.purchase_models import PurchaseDocument, PurchaseLine
from app.features.crm.models.xero_account import XeroAccount
from app.observability import get_logger

logger = get_logger(__name__)

SOURCE_XERO_BANK = "xero_bank"
# Every target customer is a New Zealand business and Xero doesn't tell us the organisation's base
# currency anywhere we read, so a document with no currency, or in NZD, is in base currency (B2).
BASE_CURRENCY = "NZD"

MONEY = Decimal("0.0001")
UNIT = Decimal("0.000001")
ZERO = Decimal("0")

_VOIDED = {"DELETED", "VOIDED"}
_RECORDED_STATES = ("partly_recorded", "recorded", "not_stock")
# A weaker reason never replaces a stronger one: a deleted purchase matters more than an edited
# amount (its cost changed), which matters more than a recode (only its classification did).
_REASON_RANK = {None: 0, "recoded": 1, "amount_changed": 2, "deleted_in_xero": 3}


# --- what 8.1c does to the allocations -----------------------------------------------------------


class LineChangeHooks:
    """The allocation side of "When Xero changes later". 8.1b has no allocations, so these do
    nothing; 8.1c replaces the bodies. Each is called after the line itself has been updated,
    inside the document's savepoint, only for a line that already has a decision recorded on it.
    """

    def amount_changed(self, db: Session, org_id: UUID, line: PurchaseLine, old_amount: Decimal) -> None:
        """Rescale each active allocation by new / old (4 dp, remainder to the largest) and
        re-derive the line's state. ``line.amount_ex_tax`` and ``not_stock_amount`` are already new."""

    def recoded(self, db: Session, org_id: UUID, line: PurchaseLine, old_account_code: str | None) -> None:
        """The line moved from a stock account to a non-stock one. Allocations and lots stay."""

    def deleted(self, db: Session, org_id: UUID, line: PurchaseLine) -> None:
        """Xero deleted or voided the document, or no longer returns this line: mark the line's
        allocations ``orphaned`` (still priced, status ``estimated``)."""

    def reinstated(self, db: Session, org_id: UUID, line: PurchaseLine) -> None:
        """A line that was treated as deleted came back: make its orphaned allocations active."""


hooks = LineChangeHooks()


# --- normalised shape ------------------------------------------------------------------------------


@dataclass
class LineData:
    line_key: str
    description: str | None
    item_code: str | None
    quantity: Decimal | None
    unit_amount: Decimal | None
    account_code: str | None
    amount_ex_tax: Decimal
    tax_amount: Decimal


@dataclass
class DocumentData:
    source: str
    external_id: str
    kind: str
    payee_name: str | None
    xero_contact_id: str | None
    document_date: date
    reference: str | None
    currency_code: str
    currency_rate: Decimal
    status: str
    total_ex_tax: Decimal
    total_tax: Decimal
    external_updated_at: datetime | None
    lines: list[LineData] = field(default_factory=list)


@dataclass(frozen=True)
class ChartAccount:
    code: str
    name: str
    default_treatment: str | None  # None: not an expense account


@dataclass
class IngestSummary:
    documents: int = 0  # documents stored or updated
    unknown_account_lines: int = 0  # lines whose account isn't in the cached chart (not stored)
    errors: list[str] = field(default_factory=list)


def load_chart(db: Session, org_id: UUID) -> dict[str, ChartAccount]:
    """The org's cached chart of accounts by code. An active account wins a code an archived one had."""
    rows = db.query(XeroAccount).filter(XeroAccount.org_id == org_id, XeroAccount.code.isnot(None)).all()
    rows.sort(key=lambda a: (str(a.status or "").upper() == "ACTIVE", a.updated_at or utc_now()))
    return {a.code: ChartAccount(a.code, a.name, a.default_treatment) for a in rows}


# --- normalising a Xero bank transaction ---------------------------------------------------------------


def _text(value) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _round(value: Decimal, exponent: Decimal) -> Decimal:
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def _squash(value) -> str:
    return " ".join(str(value or "").lower().split())


def line_key(item: Any, position: int) -> str:
    """Xero's LineItemID when it sends one; otherwise ``pos:<n>:<fingerprint>`` (decision B1).

    ``n`` is the line's 1-based position among *all* the transaction's lines. The fingerprint is
    the first 8 hex digits of SHA-256 over the normalised description and item code, so an edit to
    the amount, tax or account keeps the key while a reorder, an insert before the line or a new
    description gives a new one. The old key is then superseded rather than quietly pointing at
    a different line.
    """
    raw = _text(getattr(item, "line_item_id", None))
    if raw:
        return raw[:100]
    digest = hashlib.sha256(
        f"{_squash(getattr(item, 'description', None))}\x1f{_squash(getattr(item, 'item_code', None))}".encode()
    ).hexdigest()[:8]
    return f"pos:{position}:{digest}"


def _currency(txn: Any, external_id: str) -> tuple[str, Decimal]:
    """(code, rate) for the document. Xero's rate is units of the document's currency per one unit
    of base currency, so base amount = foreign amount / rate (decision B2)."""
    code = _text(getattr(txn, "currency_code", None)).upper() or BASE_CURRENCY
    if code == BASE_CURRENCY:
        return BASE_CURRENCY, Decimal("1")
    rate = _dec(getattr(txn, "currency_rate", None))
    if rate is None or rate <= 0:
        raise ValueError(f"bank transaction {external_id} is in {code} but Xero gave no exchange rate")
    return code, rate


def normalise_bank_transaction(txn: Any) -> DocumentData | None:
    """A Xero ``BankTransaction`` as a ``DocumentData``; ``None`` for anything but SPEND / RECEIVE.

    Raises ``ValueError`` for a document that can't be stored honestly (no id, no date, a foreign
    document without an exchange rate).
    """
    type_ = _text(getattr(txn, "type", None)).upper()
    if type_ not in ("SPEND", "RECEIVE"):
        return None
    external_id = _text(getattr(txn, "bank_transaction_id", None))
    if not external_id:
        raise ValueError("bank transaction has no id")
    day = getattr(txn, "date", None)
    if isinstance(day, datetime):
        day = day.date()
    if not isinstance(day, date):
        raise ValueError(f"bank transaction {external_id} has no date")

    refund = type_ == "RECEIVE"
    sign = -1 if refund else 1
    currency, rate = _currency(txn, external_id)
    inclusive = _text(getattr(txn, "line_amount_types", None)).lower() == "inclusive"

    def to_base(amount: Decimal, exponent: Decimal = MONEY, *, signed: bool = True) -> Decimal:
        converted = _round(amount / rate, exponent)
        return -converted if (signed and sign < 0) else converted

    lines: list[LineData] = []
    for position, item in enumerate(getattr(txn, "line_items", None) or [], start=1):
        line_amount = _dec(getattr(item, "line_amount", None)) or ZERO
        tax = _dec(getattr(item, "tax_amount", None)) or ZERO
        ex_tax = line_amount - tax if inclusive else line_amount  # Exclusive and NoTax: as is
        quantity = _dec(getattr(item, "quantity", None))
        unit = _dec(getattr(item, "unit_amount", None))
        if inclusive:  # Xero's unit amount includes the tax here; keep an ex-tax one
            unit = abs(ex_tax) / quantity if quantity and quantity > 0 else None
        lines.append(
            LineData(
                line_key=line_key(item, position),
                description=_text(getattr(item, "description", None)) or None,
                item_code=_text(getattr(item, "item_code", None)) or None,
                quantity=quantity,
                unit_amount=None if unit is None else to_base(unit, UNIT, signed=False),
                account_code=_text(getattr(item, "account_code", None)) or None,
                amount_ex_tax=to_base(ex_tax),
                tax_amount=to_base(tax),
            )
        )

    sub_total = _dec(getattr(txn, "sub_total", None))
    total_tax = _dec(getattr(txn, "total_tax", None))
    contact = getattr(txn, "contact", None)
    return DocumentData(
        source=SOURCE_XERO_BANK,
        external_id=external_id,
        kind="refund" if refund else "spend",
        payee_name=(_text(getattr(contact, "name", None)) or None) if contact else None,
        xero_contact_id=(_text(getattr(contact, "contact_id", None)) or None) if contact else None,
        document_date=day,
        reference=_text(getattr(txn, "reference", None)) or None,
        currency_code=currency,
        currency_rate=rate,
        status="voided" if _text(getattr(txn, "status", None)).upper() in _VOIDED else "active",
        total_ex_tax=to_base(sub_total) if sub_total is not None else sum((x.amount_ex_tax for x in lines), ZERO),
        total_tax=to_base(total_tax) if total_tax is not None else sum((x.tax_amount for x in lines), ZERO),
        external_updated_at=getattr(txn, "updated_date_utc", None),
        lines=lines,
    )


# --- storing it ----------------------------------------------------------------------------------------


def is_recorded(line: PurchaseLine) -> bool:
    """A decision has been recorded on the line (stock recorded, or some/all of it said not stock)."""
    return line.state in _RECORDED_STATES or (line.not_stock_amount or ZERO) != ZERO


def _chart_treatment(account: ChartAccount | None, current: str) -> str:
    """What the chart says a line on ``account`` is: its default, ``not_stock`` once it is no longer
    an expense account, and ``current`` when the account isn't in the chart at all (nothing to go on)."""
    if account is None:
        return current
    return account.default_treatment or treatments.NOT_STOCK


def _flag(line: PurchaseLine, reason: str) -> None:
    if _REASON_RANK[reason] > _REASON_RANK.get(line.review_reason, 0):
        line.review_reason = reason


def _rescale_not_stock(not_stock: Decimal, old: Decimal, new: Decimal) -> Decimal:
    if not not_stock or not old:
        return not_stock
    scaled = _round(not_stock * new / old, MONEY)
    return new if abs(scaled) > abs(new) else scaled


def _new_line(org_id: UUID, document_id: UUID, data: LineData, account: ChartAccount) -> PurchaseLine:
    return PurchaseLine(
        org_id=org_id,
        document_id=document_id,
        line_key=data.line_key,
        description=data.description,
        item_code=data.item_code,
        quantity=data.quantity,
        unit_amount=data.unit_amount,
        account_code=data.account_code,
        account_name=account.name,
        amount_ex_tax=data.amount_ex_tax,
        tax_amount=data.tax_amount,
        treatment=account.default_treatment,
        treatment_override=False,
        state="open",
        not_stock_amount=ZERO,
    )


def _update_line(
    db: Session,
    org_id: UUID,
    row: PurchaseLine,
    data: LineData,
    account: ChartAccount | None,
    *,
    document_was_voided: bool,
    document_is_voided: bool,
) -> None:
    recorded = is_recorded(row)
    was_gone = document_was_voided or row.superseded_at is not None

    if document_is_voided:
        if not was_gone and recorded:
            _flag(row, "deleted_in_xero")
            hooks.deleted(db, org_id, row)
        return  # nothing else about a deleted purchase matters
    if was_gone:
        row.superseded_at = None
        if row.review_reason == "deleted_in_xero":
            row.review_reason = None
            hooks.reinstated(db, org_id, row)

    old_amount, old_account, old_treatment = row.amount_ex_tax, row.account_code, row.treatment
    amount_changed = data.amount_ex_tax != old_amount
    account_changed = (data.account_code or None) != (old_account or None)
    default = _chart_treatment(account, row.treatment)

    if row.treatment_override:
        treatment = row.treatment  # decided by hand: Xero's coding doesn't change it
    elif recorded:
        treatment = default if account_changed else row.treatment
    elif row.treatment_rule_id is not None:
        treatment = row.treatment  # a purchase rule decided (8.1c re-evaluates those)
    else:
        treatment = default

    row.description = data.description
    row.item_code = data.item_code
    row.quantity = data.quantity
    row.unit_amount = data.unit_amount
    row.account_code = data.account_code
    if account:
        row.account_name = account.name
    row.amount_ex_tax = data.amount_ex_tax
    row.tax_amount = data.tax_amount
    row.treatment = treatment
    if treatment == treatments.STOCK and row.review_reason == "recoded":
        row.review_reason = None  # back where it was: nothing left to review

    if not recorded:
        return
    if amount_changed:
        row.not_stock_amount = _rescale_not_stock(row.not_stock_amount or ZERO, old_amount, data.amount_ex_tax)
        _flag(row, "amount_changed")
        hooks.amount_changed(db, org_id, row, old_amount)
    if (
        account_changed
        and not row.treatment_override
        and old_treatment == treatments.STOCK
        and treatment != treatments.STOCK
    ):
        _flag(row, "recoded")
        hooks.recoded(db, org_id, row, old_account)


def _retire_line(db: Session, org_id: UUID, row: PurchaseLine, *, document_was_voided: bool, now: datetime) -> None:
    """Xero returned the document but not this line: treat it like a deleted one."""
    reported = document_was_voided or row.superseded_at is not None
    if row.superseded_at is None:
        row.superseded_at = now
    if not reported and is_recorded(row):
        _flag(row, "deleted_in_xero")
        hooks.deleted(db, org_id, row)


def upsert_document(
    db: Session, org_id: UUID, data: DocumentData, chart: dict[str, ChartAccount], summary: IngestSummary
) -> bool:
    """Store or update one document and its lines. False when nothing of it is worth storing."""
    now = utc_now()
    storable = [x for x in data.lines if (a := chart.get(x.account_code or "")) and a.default_treatment]
    document = (
        db.query(PurchaseDocument)
        .filter(
            PurchaseDocument.org_id == org_id,
            PurchaseDocument.source == data.source,
            PurchaseDocument.external_id == data.external_id,
        )
        .one_or_none()
    )
    if document is None and not storable:
        summary.unknown_account_lines += sum(1 for x in data.lines if (x.account_code or "") not in chart)
        return False

    was_voided = document is not None and document.status == "voided"
    if document is None:
        document = PurchaseDocument(org_id=org_id, source=data.source, external_id=data.external_id)
        db.add(document)
    document.kind = data.kind
    document.payee_name = data.payee_name
    document.xero_contact_id = data.xero_contact_id
    document.document_date = data.document_date
    document.reference = data.reference
    document.currency_code = data.currency_code
    document.currency_rate = data.currency_rate
    document.status = data.status
    document.total_ex_tax = data.total_ex_tax
    document.total_tax = data.total_tax
    document.external_updated_at = data.external_updated_at
    document.last_synced_at = now
    db.flush()

    existing = {
        row.line_key: row
        for row in db.query(PurchaseLine)
        .filter(PurchaseLine.org_id == org_id, PurchaseLine.document_id == document.id)
        .all()
    }
    returned: set[str] = set()
    for item in data.lines:
        returned.add(item.line_key)
        account = chart.get(item.account_code or "")
        row = existing.get(item.line_key)
        if row is not None:
            _update_line(
                db,
                org_id,
                row,
                item,
                account,
                document_was_voided=was_voided,
                document_is_voided=data.status == "voided",
            )
        elif account and account.default_treatment:
            db.add(_new_line(org_id, document.id, item, account))
        elif account is None:
            summary.unknown_account_lines += 1
    for key, row in existing.items():
        if key not in returned:
            _retire_line(db, org_id, row, document_was_voided=was_voided, now=now)
    db.flush()
    return True


def reclassify_unrecorded_lines(db: Session, org_id: UUID, chart: dict[str, ChartAccount], codes: set[str]) -> int:
    """Re-apply the account default to lines coded to ``codes`` that nobody has acted on.

    Used when the chart changes under existing lines. A line with a decision recorded, a hand-set
    treatment or a purchase rule's treatment is left alone (8.1c reuses this for rule changes).
    """
    if not codes:
        return 0
    rows = (
        db.query(PurchaseLine)
        .filter(
            PurchaseLine.org_id == org_id,
            PurchaseLine.account_code.in_(sorted(codes)),
            PurchaseLine.treatment_override.is_(False),
            PurchaseLine.treatment_rule_id.is_(None),
            PurchaseLine.state.in_(("open", "skipped")),
        )
        .all()
    )
    changed = 0
    for row in rows:
        account = chart.get(row.account_code or "")
        wanted = _chart_treatment(account, row.treatment)
        if row.treatment != wanted:
            row.treatment = wanted
            changed += 1
    db.flush()
    return changed


class XeroBankPurchaseSource:
    """Xero SPEND / RECEIVE bank transactions."""

    name = SOURCE_XERO_BANK
    label = "Xero"

    def ingest(self, db: Session, org_id: UUID, transactions: list, chart: dict[str, ChartAccount]) -> IngestSummary:
        """Store ``transactions`` (xero-python ``BankTransaction`` objects); each in its own
        savepoint, so one the database rejects fails alone."""
        summary = IngestSummary()
        for txn in transactions:
            label = _text(getattr(txn, "bank_transaction_id", None)) or "?"
            try:
                data = normalise_bank_transaction(txn)
                if data is None:
                    continue
                with db.begin_nested():
                    if upsert_document(db, org_id, data, chart, summary):
                        summary.documents += 1
            except Exception as error:  # noqa: BLE001 - reported per record, the sync goes on
                logger.warning("xero_bank_transaction_sync_record_failed", bank_transaction_id=label, error=str(error))
                summary.errors.append(f"bank transaction {label}: {error}")
        if summary.unknown_account_lines:
            logger.warning(
                "purchase_lines_on_unknown_accounts", org_id=str(org_id), lines=summary.unknown_account_lines
            )
        db.flush()
        return summary


PURCHASE_SOURCES = {SOURCE_XERO_BANK: XeroBankPurchaseSource()}
