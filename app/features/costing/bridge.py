"""The Xero bridge (live-cogs 8.1g; spec "8.1g build contract").

Two halves. The tie-out compares Xero's stock accounts (its P&L, read live) with the purchase
lines Biz-E synced, and lists what isn't recorded as stock. The roll-forward explains what left
stock between two snapshots from the movements stored with the later one, so a closed period
doesn't move. The roll-forward works without Xero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.features.costing import stock_value
from app.features.costing.engine import money
from app.features.costing.models import (
    PurchaseAllocation,
    PurchaseDocument,
    PurchaseLine,
    StockValueMovement,
    StockValueSnapshot,
)
from app.features.costing.service import CostingError
from app.observability import get_logger

logger = get_logger(__name__)

ZERO = Decimal("0")
REPORT_SCOPE = "accounting.reports.profitandloss.read"


def _amount(raw) -> Decimal | None:
    text = str(raw if raw is not None else "").strip().replace(",", "").replace("$", "")
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    try:
        value = Decimal(text.strip("()"))
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_profit_and_loss(rows) -> list[dict]:
    """Account rows of a Xero P&L: account id (from the cell's ``account`` attribute, else None),
    name, amount and section. Headers, totals and unreadable rows are skipped."""
    out: list[dict] = []

    def walk(items, section):
        for row in items or []:
            kind = getattr(getattr(row, "row_type", None), "value", getattr(row, "row_type", None))
            if kind == "Section":
                walk(row.rows, row.title or section)
            elif kind == "Row":
                cells = row.cells or []
                if len(cells) < 2:
                    continue
                amount = _amount(cells[1].value)
                if amount is None:
                    continue
                account_id = next(
                    (a.value for a in (cells[0].attributes or []) if getattr(a, "id", None) == "account"), None
                )
                out.append({"account_id": account_id, "name": cells[0].value, "amount": amount, "section": section})

    walk(rows, None)
    return out


def _fetch_profit_and_loss(db: Session, org_id: UUID, start, end) -> dict:
    from app.features.crm.repositories.xero_tenant_repo import XeroTenantRepository
    from app.features.crm.repositories.xero_token_repo import XeroTokenRepository
    from app.features.crm.services import xero_api_client as client_module
    from app.features.crm.services.xero_oauth_service import XeroTokenExpiredError

    if XeroTenantRepository(db).get_connected(org_id) is None:
        return {"state": "not_connected"}
    token = XeroTokenRepository(db).get(org_id)
    granted = (token.scopes or "").split() if token is not None else []
    if granted and REPORT_SCOPE not in granted:
        return {"state": "needs_reconnect"}
    try:
        rows = client_module.XeroAPIClient(db, org_id).get_profit_and_loss(start, end)
        return {"state": "ok", "rows": parse_profit_and_loss(rows)}
    except (client_module.XeroInsufficientScopeError, XeroTokenExpiredError):
        return {"state": "needs_reconnect"}
    except Exception as error:  # noqa: BLE001 - never echo Xero or SQL internals
        ref = uuid4().hex[:12]
        logger.exception("costing_bridge_pl_failed", org_id=str(org_id), ref=ref, error_type=type(error).__name__)
        return {"state": "failed", "ref": ref}


def _stock_accounts(db: Session, org_id: UUID):
    from app.features.crm.models.xero_account import XeroAccount

    accounts = db.query(XeroAccount).filter(XeroAccount.org_id == org_id).all()
    return accounts, {a.id for a in accounts if a.treatment == "stock"}


def _xero_totals(accounts, rows) -> dict:
    """P&L amounts by account treatment (matched on Xero's account id, else exact name)."""
    by_id = {a.xero_account_id: a for a in accounts}
    by_name = defaultdict(list)
    for a in accounts:
        by_name[(a.name or "").strip().casefold()].append(a)
    totals: dict = defaultdict(lambda: ZERO)
    per_account: dict = defaultdict(lambda: ZERO)
    for row in rows:
        account = by_id.get(row["account_id"]) if row["account_id"] else None
        if account is None:
            matches = by_name.get((row["name"] or "").strip().casefold(), [])
            account = matches[0] if len(matches) == 1 else None
        if account is None or not account.treatment:
            continue
        totals[account.treatment] += row["amount"]
        per_account[account.id] += row["amount"]
    return {"by_treatment": totals, "per_account": per_account}


def _tie_out(db: Session, org_id: UUID, start, end, pl_rows) -> dict:
    accounts, stock_ids = _stock_accounts(db, org_id)
    xero = _xero_totals(accounts, pl_rows)
    a_total = xero["by_treatment"].get("stock", ZERO)
    lines = (
        db.query(PurchaseLine, PurchaseDocument)
        .join(
            PurchaseDocument,
            (PurchaseDocument.org_id == PurchaseLine.org_id) & (PurchaseDocument.id == PurchaseLine.document_id),
        )
        .filter(
            PurchaseLine.org_id == org_id,
            PurchaseLine.superseded_at.is_(None),
            PurchaseDocument.status == "active",
            PurchaseDocument.document_date >= start,
            PurchaseDocument.document_date <= end,
            PurchaseLine.amount_ex_tax.isnot(None),
        )
        .all()
    )
    lines = [(line, doc) for line, doc in lines if line.account_id in stock_ids]
    ids = [line.id for line, _ in lines]
    recorded_by_line: dict = defaultdict(lambda: ZERO)
    active_by_line: dict = defaultdict(lambda: ZERO)
    if ids:
        allocations = (
            db.query(PurchaseAllocation)
            .filter(
                PurchaseAllocation.org_id == org_id,
                PurchaseAllocation.purchase_line_id.in_(ids),
                PurchaseAllocation.status.in_(("active", "orphaned")),
            )
            .all()
        )
        for allocation in allocations:
            recorded_by_line[allocation.purchase_line_id] += Decimal(str(allocation.amount))
            if allocation.status == "active":
                active_by_line[allocation.purchase_line_id] += Decimal(str(allocation.amount))
    synced = ZERO
    recorded = ZERO
    listed = []
    for line, doc in sorted(lines, key=lambda r: (r[1].document_date, str(r[0].id))):
        amount = Decimal(str(line.amount_ex_tax))
        synced += amount
        recorded += recorded_by_line[line.id]
        not_stock = Decimal(str(line.not_stock_amount or 0))
        open_amount = amount - active_by_line[line.id] - not_stock
        left = open_amount + not_stock
        if left == ZERO:
            continue
        listed.append(
            {
                "line_id": str(line.id),
                "date": doc.document_date.isoformat(),
                "payee": doc.payee_name,
                "description": line.description,
                "account": line.account_name or line.account_code,
                "amount": money(amount),
                "open_amount": money(open_amount),
                "not_stock_amount": money(not_stock),
                "listed": money(left),
                "state": line.state,
            }
        )
    listed_total = sum((Decimal(row["listed"]) for row in listed), ZERO)
    return {
        "xero_stock_total": money(a_total),
        "recorded": money(recorded),
        "difference": money(a_total - recorded),
        "not_recorded": listed,
        "not_recorded_total": money(listed_total),
        "other_entries": money(a_total - synced),
        "accounts": [
            {
                "code": a.code,
                "name": a.name,
                "xero_total": money(xero["per_account"].get(a.id, ZERO)),
            }
            for a in sorted(accounts, key=lambda a: a.code or "")
            if a.id in stock_ids
        ],
        "_xero": xero,
    }


def _duty(db: Session, org_id: UUID, start, end, xero_total) -> dict:
    from app.features.compliant.service import nz_alcohol_active

    tracked = bool(nz_alcohol_active(db, org_id))
    out = {"tracked": tracked, "xero_total": money(xero_total) if xero_total is not None else None, "computed": None}
    whole_months = start.day == 1 and (end + timedelta(days=1)).day == 1
    if not tracked or not whole_months:
        if tracked:
            out["reason"] = "The period isn't whole months"
        return out
    try:
        from app.features.costing import margins

        report = margins.report(db, org_id, start, end.replace(day=1))
        duties = [row["duty"] for row in report["rows"]]
        if all(d is not None for d in duties):
            out["computed"] = money(sum((Decimal(d) for d in duties), ZERO))
        else:
            out["reason"] = "Duty couldn't be worked out for every sale"
    except Exception as error:  # noqa: BLE001 - the bridge shows the rest without it
        logger.warning("costing_bridge_duty_failed", org_id=str(org_id), error_type=type(error).__name__)
    return out


def _roll_forward(db: Session, org_id: UUID, opening: StockValueSnapshot, closing: StockValueSnapshot) -> dict:
    between = (
        db.query(StockValueSnapshot)
        .filter(
            StockValueSnapshot.org_id == org_id,
            StockValueSnapshot.cutoff_at > opening.cutoff_at,
            StockValueSnapshot.cutoff_at <= closing.cutoff_at,
        )
        .order_by(StockValueSnapshot.cutoff_at)
        .all()
    )
    totals: dict = defaultdict(lambda: ZERO)
    ids = [s.id for s in between]
    if ids:
        movements = (
            db.query(StockValueMovement)
            .filter(StockValueMovement.org_id == org_id, StockValueMovement.snapshot_id.in_(ids))
            .all()
        )
        for movement in movements:
            totals[movement.kind] += Decimal(str(movement.value))
    purchases = totals["purchase"]
    o, c = Decimal(str(opening.total_value)), Decimal(str(closing.total_value))
    components = {
        "cogs": -totals["sale"],
        "wastage": -totals["wastage"],
        "samples": -totals["sample"],
        "variance": -totals["variance"],
        "production_loss": -totals["production_loss"],
        "estimate_changes": -(totals["revaluation"] + totals["added_other"]),
        "other": -(totals["transfer"] + totals["rounding"]),
    }
    return {
        "opening": money(o),
        "purchases": money(purchases),
        "closing": money(c),
        "cost_left": money(o + purchases - c),
        "components": {k: money(v) for k, v in components.items()},
        "estimate_detail": {"revaluation": money(totals["revaluation"]), "added_other": money(totals["added_other"])},
        "rounding": money(totals["rounding"]),
        "balanced": abs(totals["rounding"]) <= Decimal("0.01"),
    }


def build_bridge(
    db: Session, org_id: UUID, opening: StockValueSnapshot | None, closing: StockValueSnapshot | None
) -> dict:
    if opening is None or closing is None:
        return {"state": "needs_snapshots", "snapshots": len(stock_value.list_snapshots(db, org_id))}
    if opening.cutoff_at >= closing.cutoff_at:
        raise CostingError("The first snapshot must be earlier than the second")
    start, end = opening.as_of_date + timedelta(days=1), closing.as_of_date
    body = {
        "state": "ok",
        "from": stock_value.snapshot_header(opening),
        "to": stock_value.snapshot_header(closing),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "roll_forward": _roll_forward(db, org_id, opening, closing),
        "changes_since_close": stock_value.changes_since_close(db, org_id, closing),
        "tie_out": None,
    }
    xero_total_duty = xero_total_overhead = None
    if start > end:
        body["xero"] = {"state": "same_day"}
    else:
        fetched = _fetch_profit_and_loss(db, org_id, start, end)
        body["xero"] = {k: v for k, v in fetched.items() if k != "rows"}
        if fetched["state"] == "ok":
            tie = _tie_out(db, org_id, start, end, fetched["rows"])
            by_treatment = tie.pop("_xero")["by_treatment"]
            xero_total_duty = by_treatment.get("duty", ZERO)
            xero_total_overhead = by_treatment.get("overhead", ZERO)
            body["tie_out"] = tie
    body["duty"] = _duty(db, org_id, start, end, xero_total_duty)
    body["overhead"] = {"xero_total": money(xero_total_overhead) if xero_total_overhead is not None else None}
    return body
