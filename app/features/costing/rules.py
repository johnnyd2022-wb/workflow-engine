"""Purchase rules: validation, matching and precedence, re-classification, "remember this"
(live-cogs 8.1c-2; spec "8.1c-2 build contract"). Callers own the commit.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.costing.models import PurchaseAllocation, PurchaseDocument, PurchaseLine, PurchaseRule
from app.features.costing.service import CostingError, CostingNotFoundError

TREATMENTS = ("stock", "not_stock", "duty", "overhead")
MATCH_TYPES = ("exact", "contains")
QUANTITY_MODES = ("fixed", "from_price", "ask")
ROW_TYPES = ("raw_material", "final_product")
FIELDS = {
    "account_code",
    "payee_pattern",
    "description_pattern",
    "match_type",
    "treatment",
    "template",
    "auto_record",
    "is_active",
}


class RuleConflictError(CostingError):
    """A rule with the same matchers exists (409)."""


def normalise(text: Any) -> str | None:
    if text is None:
        return None
    value = re.sub(r"\s+", " ", str(text).casefold()).strip()
    return value or None


def _positive(raw, what) -> str:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise CostingError(f"{what} must be a number") from None
    if not value.is_finite() or value <= 0 or value >= Decimal("100000000000000"):
        raise CostingError(f"{what} must be more than 0")
    return str(value)


def validate_template(template) -> list[dict] | None:
    if template is None:
        return None
    if not isinstance(template, list) or not 1 <= len(template) <= 20:
        raise CostingError("A template has 1 to 20 rows")
    rows, total, rests = [], Decimal("0"), 0
    for raw in template:
        if not isinstance(raw, dict):
            raise CostingError("Each template row is an object")
        name, unit = raw.get("name"), raw.get("unit")
        if not isinstance(name, str) or not isinstance(unit, str):
            raise CostingError("A template row's name and unit are text")
        name, unit = name.strip(), unit.strip()
        if not name or not unit:
            raise CostingError("Each template row needs a name and a unit")
        if len(name) > 255 or len(unit) > 50:
            raise CostingError("A template row's name or unit is too long")
        for flag in ("ask_batch_number", "ask_expiry"):
            if flag in raw and not isinstance(raw[flag], bool):
                raise CostingError(f"{flag} must be true or false")
        kind = raw.get("inventory_type") or "raw_material"
        if kind not in ROW_TYPES:
            raise CostingError("inventory_type must be raw_material or final_product")
        mode = raw.get("quantity_mode")
        if mode not in QUANTITY_MODES:
            raise CostingError("quantity_mode must be fixed, from_price or ask")
        row = {"name": name, "unit": unit, "inventory_type": kind, "quantity_mode": mode}
        if mode == "fixed":
            row["quantity"] = _positive(raw.get("quantity"), "quantity")
        if mode == "from_price":
            row["unit_price"] = _positive(raw.get("unit_price"), "unit_price")
        share = raw.get("share")
        if share == "rest":
            rests += 1
            row["share"] = "rest"
        else:
            value = Decimal(_positive(share, "share"))
            if not value.is_finite() or value > 100:
                raise CostingError("A share is at most 100")
            total += value
            row["share"] = str(value)
        row["ask_batch_number"] = bool(raw.get("ask_batch_number"))
        row["ask_expiry"] = bool(raw.get("ask_expiry"))
        rows.append(row)
    if rests > 1:
        raise CostingError("Only one row can take the rest")
    if not total.is_finite() or total > 100:
        raise CostingError("Shares add up to more than 100%")
    return rows


def validate(body: dict) -> dict:
    if not isinstance(body, dict):
        raise CostingError("Send a JSON object")
    unknown = set(body) - FIELDS
    if unknown:
        raise CostingError(f"Unknown field(s): {', '.join(sorted(unknown))}")

    def text_field(name, limit):
        raw = body.get(name)
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise CostingError(f"{name} must be text")
        if len(raw) > limit:
            raise CostingError(f"{name} is at most {limit} characters")
        return raw

    raw_account = text_field("account_code", 50)
    account = (raw_account.strip() or None) if raw_account is not None else None  # whitespace is no matcher
    payee = normalise(text_field("payee_pattern", 255))
    description = normalise(text_field("description_pattern", 500))
    # casefold can lengthen text ("ß" -> "ss"): the stored, normalised value must fit too
    if payee and len(payee) > 255:
        raise CostingError("payee_pattern is at most 255 characters")
    if description and len(description) > 500:
        raise CostingError("description_pattern is at most 500 characters")
    if not (account or payee or description):
        raise CostingError("A rule needs an account, a payee or a description to match")
    match_type = body.get("match_type", "exact")
    if match_type not in MATCH_TYPES:
        raise CostingError("match_type must be exact or contains")
    treatment = body.get("treatment")
    if treatment not in TREATMENTS:
        raise CostingError(f"treatment must be one of {', '.join(TREATMENTS)}")
    template = validate_template(body.get("template"))
    if template is not None and treatment != "stock":
        raise CostingError("Only a stock rule has a template")
    auto_record = body.get("auto_record", False)
    if not isinstance(auto_record, bool):
        raise CostingError("auto_record must be true or false")
    if auto_record:
        if treatment != "stock":
            raise CostingError("auto_record is only allowed for stock rules")
        if template is None:
            raise CostingError("auto_record requires a template")
        if any(row["quantity_mode"] == "ask" for row in template):
            raise CostingError("auto_record templates cannot ask for quantity")
        if any(row["ask_batch_number"] or row["ask_expiry"] for row in template):
            raise CostingError("auto_record templates cannot ask for batch number or expiry")
        if not any(row["share"] == "rest" for row in template) and sum(
            (Decimal(row["share"]) for row in template), Decimal("0")
        ) != Decimal("100"):
            raise CostingError("auto_record template shares must total 100 or include a rest row")
    active = body.get("is_active", True)
    if not isinstance(active, bool):
        raise CostingError("is_active must be true or false")
    return {
        "account_code": account,
        "payee_pattern": payee,
        "description_pattern": description,
        "match_type": match_type,
        "treatment": treatment,
        "template": template,
        "auto_record": auto_record,
        "is_active": active,
    }


def as_dict(rule: PurchaseRule) -> dict:
    return {
        "id": str(rule.id),
        "account_code": rule.account_code,
        "payee_pattern": rule.payee_pattern,
        "description_pattern": rule.description_pattern,
        "match_type": rule.match_type,
        "treatment": rule.treatment,
        "template": rule.template,
        "auto_record": rule.auto_record,
        "is_active": rule.is_active,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def get_rule(db: Session, org_id: UUID, rule_id) -> PurchaseRule:
    try:
        uid = UUID(str(rule_id))
    except (ValueError, TypeError):
        raise CostingNotFoundError("Rule not found") from None
    rule = (
        db.query(PurchaseRule)
        .filter(PurchaseRule.org_id == org_id, PurchaseRule.id == uid)
        .with_for_update()
        .one_or_none()
    )
    if rule is None:
        raise CostingNotFoundError("Rule not found")
    return rule


def _save(db: Session, rule: PurchaseRule) -> None:
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise RuleConflictError("A rule with the same matchers already exists") from None


def create(db: Session, org_id: UUID, body: dict, user_id=None) -> PurchaseRule:
    rule = PurchaseRule(org_id=org_id, created_by_user_id=user_id, **validate(body))
    db.add(rule)
    _save(db, rule)
    reclassify_open_lines(db, org_id)
    return rule


def update(db: Session, org_id: UUID, rule_id, body: dict) -> PurchaseRule:
    rule = get_rule(db, org_id, rule_id)
    current = {
        "account_code": rule.account_code,
        "payee_pattern": rule.payee_pattern,
        "description_pattern": rule.description_pattern,
        "match_type": rule.match_type,
        "treatment": rule.treatment,
        "template": rule.template,
        "auto_record": rule.auto_record,
        "is_active": rule.is_active,
    }
    current.update({k: v for k, v in body.items() if k in FIELDS})
    clean = validate(current)
    for name, value in clean.items():
        setattr(rule, name, value)
    rule.updated_at = utc_now()
    _save(db, rule)
    reclassify_open_lines(db, org_id)
    return rule


def delete(db: Session, org_id: UUID, rule_id) -> None:
    rule = get_rule(db, org_id, rule_id)
    db.query(PurchaseLine).filter(PurchaseLine.org_id == org_id, PurchaseLine.treatment_rule_id == rule.id).update(
        {PurchaseLine.treatment_rule_id: None}, synchronize_session=False
    )
    db.delete(rule)
    db.flush()
    reclassify_open_lines(db, org_id)


def upsert_by_matchers(db: Session, org_id: UUID, body: dict, user_id=None) -> PurchaseRule:
    clean = validate(body)
    existing = (
        db.query(PurchaseRule)
        .filter(
            PurchaseRule.org_id == org_id,
            PurchaseRule.account_code.is_(None)
            if clean["account_code"] is None
            else PurchaseRule.account_code == clean["account_code"],
            PurchaseRule.payee_pattern.is_(None)
            if clean["payee_pattern"] is None
            else PurchaseRule.payee_pattern == clean["payee_pattern"],
            PurchaseRule.description_pattern.is_(None)
            if clean["description_pattern"] is None
            else PurchaseRule.description_pattern == clean["description_pattern"],
            PurchaseRule.match_type == clean["match_type"],
        )
        .with_for_update()
        .one_or_none()
    )
    if existing is None:
        return create(db, org_id, clean, user_id=user_id)
    for name, value in clean.items():
        setattr(existing, name, value)
    existing.updated_at = utc_now()
    _save(db, existing)
    reclassify_open_lines(db, org_id)
    return existing


# --- matching -------------------------------------------------------------------------------------


def active_rules(db: Session, org_id: UUID) -> list[PurchaseRule]:
    return db.query(PurchaseRule).filter(PurchaseRule.org_id == org_id, PurchaseRule.is_active.is_(True)).all()


def _text_matches(pattern: str | None, value: str | None, match_type: str) -> bool:
    if pattern is None:
        return True
    value = normalise(value) or ""
    return value == pattern if match_type == "exact" else pattern in value


def matches(rule: PurchaseRule, account_code: str | None, payee: str | None, description: str | None) -> bool:
    if rule.account_code is not None and rule.account_code != (account_code or None):
        return False
    return _text_matches(rule.payee_pattern, payee, rule.match_type) and _text_matches(
        rule.description_pattern, description, rule.match_type
    )


def _rank(rule: PurchaseRule):
    count = sum(1 for m in (rule.account_code, rule.payee_pattern, rule.description_pattern) if m is not None)
    exact = 1 if rule.match_type == "exact" else 0
    has_payee = 1 if rule.payee_pattern is not None else 0
    updated = rule.updated_at.timestamp() if rule.updated_at else 0
    # higher is better on the first four; the smaller id wins a full tie
    return (-count, -exact, -has_payee, -updated, str(rule.id))


def winner(rules: list[PurchaseRule], account_code, payee, description) -> PurchaseRule | None:
    found = [r for r in rules if matches(r, account_code, payee, description)]
    return min(found, key=_rank) if found else None


def reclassify_open_lines(db: Session, org_id: UUID) -> int:
    """Rule changes reach live lines that are open or skipped and hold no allocation (AC17)."""
    from app.features.costing.purchase_sources import classify_line
    from app.features.crm.models.xero_account import XeroAccount

    rules = active_rules(db, org_id)
    accounts = {a.id: a for a in db.query(XeroAccount).filter(XeroAccount.org_id == org_id)}
    allocated = {
        row[0]
        for row in db.query(PurchaseAllocation.purchase_line_id).filter(
            PurchaseAllocation.org_id == org_id, PurchaseAllocation.status.in_(("active", "orphaned"))
        )
    }
    rows = (
        db.query(PurchaseLine, PurchaseDocument.payee_name)
        .join(
            PurchaseDocument,
            (PurchaseDocument.org_id == PurchaseLine.org_id) & (PurchaseDocument.id == PurchaseLine.document_id),
        )
        .filter(
            PurchaseLine.org_id == org_id,
            PurchaseLine.superseded_at.is_(None),
            PurchaseLine.state.in_(("open", "skipped")),
            PurchaseDocument.status == "active",  # a voided purchase is not a live line
        )
        .with_for_update(of=PurchaseLine)
        .all()
    )
    changed = 0
    for line, payee in rows:
        if line.id in allocated or line.account_id not in accounts:
            continue
        before = line.treatment
        classify_line(line, accounts[line.account_id], payee=payee, rules=rules)
        changed += line.treatment != before
    db.flush()
    return changed


# --- remember this ---------------------------------------------------------------------------------


def remember(db: Session, org_id: UUID, line_id, user_id=None) -> PurchaseRule:
    from app.core.db.models.inventory_item import InventoryItem
    from app.features.costing import actions

    line = actions.get_line(db, org_id, line_id)
    doc = actions._document(db, line)
    if doc.kind != "spend" or line.state not in ("recorded", "partly_recorded"):
        raise CostingError("Record this purchase first")
    if not normalise(doc.payee_name):
        raise CostingError("This purchase has no payee to remember")
    amount = Decimal(str(line.amount_ex_tax))
    from decimal import ROUND_DOWN

    picked = []
    positive = [a for a in actions.line_allocations(db, line) if Decimal(str(a.amount)) > 0]
    items = {
        i.id: i
        for i in db.query(InventoryItem).filter(
            InventoryItem.org_id == org_id, InventoryItem.id.in_([a.inventory_item_id for a in positive])
        )
    }
    for alloc in positive:  # refunds and $0 rows can't be a share of a later purchase
        item = items[alloc.inventory_item_id]
        picked.append((alloc, item))
    # Shares rounded down to 4 dp, and the rounding residual given to the largest row, so they
    # add up to exactly the recorded share of the purchase (never past 100%).
    exact_total = (
        (sum(Decimal(str(a.amount)) for a, _ in picked) / amount * 100).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        if amount
        else Decimal("0")
    )
    shares = {
        a.id: (Decimal(str(a.amount)) / amount * 100).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        for a, _ in picked
    }
    if picked:
        largest = max(picked, key=lambda p: (Decimal(str(p[0].amount)), str(p[0].id)))[0]
        shares[largest.id] += exact_total - sum(shares.values(), Decimal("0"))
    rows = []
    for alloc, item in picked:
        if shares[alloc.id] <= 0:
            continue
        rows.append(
            {
                "name": item.name,
                "unit": item.unit,
                "inventory_type": item.inventory_type,
                "quantity_mode": "fixed",
                "quantity": str(alloc.quantity),
                "share": str(shares[alloc.id]),
                "ask_batch_number": bool(item.supplier_batch_number),
                "ask_expiry": bool(item.expiry_date),
            }
        )
    if not rows:
        raise CostingError("Nothing recorded to remember")
    return upsert_by_matchers(
        db,
        org_id,
        {
            "payee_pattern": doc.payee_name,
            "account_code": line.account_code,
            "match_type": "exact",
            "treatment": "stock",
            "template": rows,
        },
        user_id=user_id,
    )


def not_stock_rule(db: Session, org_id: UUID, line: PurchaseLine, doc: PurchaseDocument, user_id=None) -> PurchaseRule:
    if not normalise(doc.payee_name):
        raise CostingError("This purchase has no payee to remember")
    return upsert_by_matchers(
        db,
        org_id,
        {
            "payee_pattern": doc.payee_name,
            "account_code": line.account_code,
            "match_type": "exact",
            "treatment": "not_stock",
        },
        user_id=user_id,
    )
