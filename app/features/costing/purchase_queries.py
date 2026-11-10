"""Reading purchase lines for the Purchases page (live-cogs 8.1b).

The Xero side of each card only: what Xero says (payee, date, amount, account, description) and
where the line stands. What Biz-E proposes (pre-fill from rules, candidates, open amount once
allocations exist) is 8.1c. Tab placement follows spec .agents/specs/live-cogs.md, "The Purchases
page" and "When Xero changes later"; decision B8 fixes it for review reasons, and 8.1c/d may refine
it (Gap 14).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.features.costing.engine import money
from app.features.costing.purchase_models import PurchaseDocument, PurchaseLine
from app.features.costing.treatments import STOCK

TABS = ("to_record", "recorded", "skipped", "not_stock")
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

# These two reasons put a line back in front of the owner whatever tab it was in.
_ATTENTION = ("amount_changed", "deleted_in_xero")


def _tab_clause(tab: str):
    """SQL condition for a tab. 'Live' is a line on an active document that Xero still returns."""
    live = and_(PurchaseDocument.status == "active", PurchaseLine.superseded_at.is_(None))
    live_stock = and_(live, PurchaseLine.treatment == STOCK)
    quiet = PurchaseLine.review_reason.is_(None)
    if tab == "to_record":
        return or_(
            and_(live_stock, PurchaseLine.state.in_(("open", "partly_recorded"))),
            PurchaseLine.review_reason.in_(_ATTENTION),
        )
    if tab == "recorded":
        # A recorded line recoded to a non-stock account stays here with a badge.
        return or_(and_(live_stock, PurchaseLine.state == "recorded", quiet), PurchaseLine.review_reason == "recoded")
    if tab == "skipped":
        return and_(live_stock, PurchaseLine.state == "skipped", quiet)
    if tab == "not_stock":
        # Only the owner's own "not stock" decision: account-default non-stock lines show nowhere.
        return and_(live, PurchaseLine.state == "not_stock", quiet)
    raise ValueError(f"unknown tab {tab!r}")


def _base(db: Session, org_id: UUID, date_from: date | None, date_to: date | None):
    query = (
        db.query(PurchaseLine, PurchaseDocument)
        .join(
            PurchaseDocument,
            and_(PurchaseDocument.org_id == PurchaseLine.org_id, PurchaseDocument.id == PurchaseLine.document_id),
        )
        .filter(PurchaseLine.org_id == org_id, PurchaseDocument.org_id == org_id)
    )
    if date_from:
        query = query.filter(PurchaseDocument.document_date >= date_from)
    if date_to:
        query = query.filter(PurchaseDocument.document_date <= date_to)
    return query


def _qty(value) -> str | None:
    return None if value is None else str(value.quantize(value.__class__("0.0001")))


def card(line: PurchaseLine, document: PurchaseDocument) -> dict:
    return {
        "id": str(line.id),
        "document_id": str(document.id),
        "source": document.source,
        "external_id": document.external_id,
        "kind": document.kind,
        "payee_name": document.payee_name,
        "document_date": document.document_date.isoformat(),
        "document_status": document.status,
        "reference": document.reference,
        "currency_code": document.currency_code,
        "line_key": line.line_key,
        "description": line.description,
        "item_code": line.item_code,
        "quantity": _qty(line.quantity),
        "account_code": line.account_code,
        "account_name": line.account_name,
        "amount_ex_tax": money(line.amount_ex_tax),
        "tax_amount": money(line.tax_amount),
        "treatment": line.treatment,
        "state": line.state,
        "not_stock_amount": money(line.not_stock_amount),
        "review_reason": line.review_reason,
        "superseded": line.superseded_at is not None,
    }


def list_cards(
    db: Session,
    org_id: UUID,
    tab: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict:
    """One tab's cards (newest document first) with the count of every tab under the same dates."""
    counts = {name: _base(db, org_id, date_from, date_to).filter(_tab_clause(name)).count() for name in TABS}
    rows = (
        _base(db, org_id, date_from, date_to)
        .filter(_tab_clause(tab))
        .order_by(PurchaseDocument.document_date.desc(), PurchaseDocument.id, PurchaseLine.line_key)
        .limit(limit)
        .offset(offset)
        .all()
    )
    return {
        "tab": tab,
        "items": [card(line, document) for line, document in rows],
        "total": counts[tab],
        "counts": counts,
        "limit": limit,
        "offset": offset,
        "from": date_from.isoformat() if date_from else None,
        "to": date_to.isoformat() if date_to else None,
    }
