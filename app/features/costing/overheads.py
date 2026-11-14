"""Overheads into cost, opt-in (live-cogs 8.1h; spec .agents/specs/live-cogs-overheads.md).

Three small pieces, all facts-in / figures-out like the rest of the slice:

* the rates an org types (``overhead_rates``): validation, CRUD, and which rate is in force on a
  batch's completion date;
* what a batch's overheads come to (per batch, per litre of finished product) — the cost engine
  asks, this module answers;
* freight as landed cost: a freight line on a purchase document spreads, by value, over the
  stock that document paid for.

Nothing here commits: callers own the transaction. Off by default — ``costing_settings
.include_overheads`` — and every caller checks that first, so with it off nothing here runs.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.utils.time import utc_now
from app.features.costing.models import OverheadRate, PurchaseAllocation, PurchaseDocument, PurchaseLine
from app.features.costing.service import CostingError, CostingNotFoundError

ZERO = Decimal("0")
MONEY = Decimal("0.0001")
RATE_DP = Decimal("0.000001")
MAX_RATE = Decimal("1000000000000")  # NUMERIC(18,6) holds < 10^12
BASES = ("per_litre", "per_batch")
NAME_MAX = 80
NZ = ZoneInfo("Pacific/Auckland")
FIELDS = ("name", "basis", "amount", "effective_from")
# Words that make an overhead purchase line freight (landed cost). Rent, power and wages are
# overheads, not freight, and are never spread over stock.
FREIGHT_WORDS = re.compile(r"\b(freight|courier|postage|shipping|deliver|cartage)", re.IGNORECASE)


class OverheadConflictError(CostingError):
    """A rate with that name, basis and date already exists (409)."""


# --- rates: validation and CRUD -----------------------------------------------------------------


def _name(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CostingError("Give the overhead a name, like Rent or Labour")
    name = raw.strip()
    if len(name) > NAME_MAX:
        raise CostingError(f"The name can be at most {NAME_MAX} characters")
    return name


def _basis(raw: Any) -> str:
    if raw not in BASES:
        raise CostingError("basis must be per_litre or per_batch")
    return raw


def _amount(raw: Any) -> Decimal:
    if isinstance(raw, bool) or raw is None or raw == "":
        raise CostingError("Amount is required")
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise CostingError("Amount must be a number") from None
    if not value.is_finite():
        raise CostingError("Amount must be a number")
    if value < 0:
        raise CostingError("Amount must be 0 or more")
    if value >= MAX_RATE:
        raise CostingError("Amount is too large")
    if value != value.quantize(RATE_DP):
        raise CostingError("Amount can have at most 6 decimal places")
    return value


def _day(raw: Any) -> date:
    if not isinstance(raw, str):
        raise CostingError("Effective from must be a date (YYYY-MM-DD)")
    try:
        value = date.fromisoformat(raw.strip())
    except ValueError:
        raise CostingError("Effective from must be a date (YYYY-MM-DD)") from None
    if not date(2000, 1, 1) <= value <= date(2100, 12, 31):
        raise CostingError("Effective from must be between 2000 and 2100")
    return value


def _uuid(raw: Any) -> UUID | None:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def validate(body: dict, *, partial: bool = False) -> dict:
    if not isinstance(body, dict):
        raise CostingError("Send a JSON object")
    unknown = set(body) - set(FIELDS) - ({"is_active"} if partial else set())
    if unknown:
        raise CostingError(f"Unknown field(s): {', '.join(sorted(unknown))}")
    checks = {"name": _name, "basis": _basis, "amount": _amount, "effective_from": _day}
    clean: dict = {}
    for key, check in checks.items():
        if key in body:
            clean[key] = check(body[key])
        elif not partial:
            raise CostingError(f"{key.replace('_', ' ').capitalize()} is required")
    if partial and "is_active" in body:
        if not isinstance(body["is_active"], bool):
            raise CostingError("is_active must be true or false")
        clean["is_active"] = body["is_active"]
    return clean


def plain(value: Decimal) -> str:
    """A rate as people write it: at least cents, no padding beyond what was typed."""
    text = format(value, "f")
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0")
    return f"{whole}.{frac.ljust(2, '0')}"


def as_dict(rate: OverheadRate) -> dict:
    return {
        "id": str(rate.id),
        "name": rate.name,
        "basis": rate.basis,
        "amount": plain(Decimal(str(rate.amount))),
        "effective_from": rate.effective_from.isoformat(),
        "is_active": bool(rate.is_active),
    }


def list_rates(db: Session, org_id: UUID) -> list[OverheadRate]:
    return (
        db.query(OverheadRate)
        .filter(OverheadRate.org_id == org_id)
        .order_by(OverheadRate.effective_from.desc(), func.lower(OverheadRate.name), OverheadRate.basis)
        .all()
    )


def get_rate(db: Session, org_id: UUID, rate_id: Any, *, for_update: bool = False) -> OverheadRate:
    rate_uuid = _uuid(rate_id)
    query = db.query(OverheadRate).filter(OverheadRate.org_id == org_id, OverheadRate.id == rate_uuid)
    if for_update:
        query = query.with_for_update()
    rate = query.one_or_none() if rate_uuid is not None else None
    if rate is None:
        raise CostingNotFoundError("Rate not found")
    return rate


def _clash(db: Session, org_id: UUID, name: str, basis: str, day: date, *, except_id=None) -> bool:
    query = db.query(OverheadRate.id).filter(
        OverheadRate.org_id == org_id,
        func.lower(func.btrim(OverheadRate.name)) == name.strip().lower(),
        OverheadRate.basis == basis,
        OverheadRate.effective_from == day,
    )
    if except_id is not None:
        query = query.filter(OverheadRate.id != except_id)
    return query.first() is not None


def _conflict() -> OverheadConflictError:
    return OverheadConflictError(
        "There is already a rate with that name and basis from that date. Edit it, or pick another date."
    )


def create_rate(db: Session, org_id: UUID, body: dict, user_id=None) -> OverheadRate:
    clean = validate(body)
    if _clash(db, org_id, clean["name"], clean["basis"], clean["effective_from"]):
        raise _conflict()
    rate = OverheadRate(org_id=org_id, created_by_user_id=user_id, **clean)
    db.add(rate)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise _conflict() from None
    return rate


def update_rate(db: Session, org_id: UUID, rate_id: Any, body: dict) -> OverheadRate:
    rate = get_rate(db, org_id, rate_id, for_update=True)
    clean = validate(body, partial=True)
    merged = {
        "name": clean.get("name", rate.name),
        "basis": clean.get("basis", rate.basis),
        "effective_from": clean.get("effective_from", rate.effective_from),
    }
    if _clash(db, org_id, merged["name"], merged["basis"], merged["effective_from"], except_id=rate.id):
        raise _conflict()
    for key, value in clean.items():
        setattr(rate, key, value)
    rate.updated_at = utc_now()
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise _conflict() from None
    return rate


def delete_rate(db: Session, org_id: UUID, rate_id: Any) -> None:
    rate = get_rate(db, org_id, rate_id, for_update=True)
    db.delete(rate)
    db.flush()


# --- which rate applies to a batch ------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    id: str
    name: str
    basis: str
    amount: Decimal
    effective_from: date
    created_at: datetime | None = None


def load_rates(db: Session, org_id: UUID) -> list[Rate]:
    """Every active rate the org has typed (a few rows; read once per computation)."""
    return [
        Rate(str(r.id), r.name.strip(), r.basis, Decimal(str(r.amount)), r.effective_from, r.created_at)
        for r in db.query(OverheadRate).filter(OverheadRate.org_id == org_id, OverheadRate.is_active.is_(True)).all()
    ]


def in_force(rates: Iterable[Rate], on: date) -> list[Rate]:
    """Per (name, basis), the rate with the latest ``effective_from`` on or before ``on`` (ties:
    the newest row). A $0 rate is how a name is ended, so it applies nothing."""
    def newest(rate: Rate) -> tuple:
        return (rate.effective_from, rate.created_at or datetime.min.replace(tzinfo=UTC), rate.id)

    chosen: dict[tuple[str, str], Rate] = {}
    for rate in rates:
        if rate.effective_from > on:
            continue
        key = (rate.name.lower(), rate.basis)
        if key not in chosen or newest(rate) > newest(chosen[key]):
            chosen[key] = rate
    return sorted((r for r in chosen.values() if r.amount > 0), key=lambda r: (r.name.lower(), r.basis))


def completion_date(execution) -> date | None:
    """The org's (NZ) calendar date the batch completed, or None while it is still running."""
    status = getattr(execution.status, "value", execution.status)
    done_at = execution.completed_at
    if str(status).lower() != "completed" or done_at is None:
        return None
    if done_at.tzinfo is None:
        done_at = done_at.replace(tzinfo=UTC)
    return done_at.astimezone(NZ).date()


@dataclass
class Applied:
    lines: list = field(default_factory=list)
    amount: Decimal = ZERO
    litres_unknown: bool = False


def _q(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def apply(rates: Iterable[Rate], litres: Callable[[], Decimal | None]) -> Applied:
    """Each rate in force as a line. ``litres()`` is only asked for when a per-litre rate is in
    force; None means it can't be worked out, and then no per-litre line is applied (never a
    guessed or zero one) and ``litres_unknown`` says so."""
    out = Applied()
    known_litres: Decimal | None = None
    asked = False
    for rate in rates:
        if rate.basis == "per_batch":
            quantity, amount = Decimal("1"), _q(rate.amount)
        else:
            if not asked:
                known_litres, asked = litres(), True
            if known_litres is None:
                out.litres_unknown = True
                continue
            quantity, amount = known_litres, _q(rate.amount * known_litres)
        out.lines.append(
            {
                "name": rate.name,
                "basis": rate.basis,
                "rate": plain(rate.amount),
                "quantity": str(quantity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
                "amount": str(amount),
            }
        )
        out.amount += amount
    return out


# --- freight as landed cost --------------------------------------------------------------------


def is_freight_line(line: PurchaseLine) -> bool:
    """Marked freight by a person, or an overhead line that says freight / courier / postage…"""
    if line.freight:
        return True
    if line.treatment != "overhead":
        return False
    return bool(FREIGHT_WORDS.search(f"{line.account_name or ''} {line.description or ''}"))


def freight_shares(db: Session, org_id: UUID, allocations: Iterable[PurchaseAllocation]) -> dict[UUID, Decimal]:
    """The freight each allocation carries: its document's freight × its amount ÷ the value of the
    document's recorded stock. Every given allocation is a key (0 when it carries none). Only one
    document at a time; a refund, a voided document, or a document with nothing recorded gets none."""
    allocations = list(allocations)
    shares = {a.id: ZERO for a in allocations}
    positive = [a for a in allocations if a.cost_flow_id is not None and Decimal(str(a.amount)) > 0]
    if not positive:
        return shares
    document_of = dict(
        db.query(PurchaseLine.id, PurchaseLine.document_id).filter(
            PurchaseLine.org_id == org_id, PurchaseLine.id.in_({a.purchase_line_id for a in positive})
        )
    )
    active = {
        row[0]
        for row in db.query(PurchaseDocument.id).filter(
            PurchaseDocument.org_id == org_id,
            PurchaseDocument.id.in_(set(document_of.values())),
            PurchaseDocument.status == "active",
        )
    }
    if not active:
        return shares
    freight: dict[UUID, Decimal] = defaultdict(Decimal)
    freight_lines: set[UUID] = set()
    for line in db.query(PurchaseLine).filter(
        PurchaseLine.org_id == org_id,
        PurchaseLine.document_id.in_(active),
        PurchaseLine.superseded_at.is_(None),
        PurchaseLine.amount_ex_tax > 0,
        or_(PurchaseLine.freight.is_(True), PurchaseLine.treatment == "overhead"),
    ):
        if is_freight_line(line):
            freight[line.document_id] += Decimal(str(line.amount_ex_tax))
            freight_lines.add(line.id)
    if not freight:
        return shares
    value: dict[UUID, Decimal] = {
        document_id: Decimal(str(total))
        for document_id, total in db.query(PurchaseLine.document_id, func.sum(PurchaseAllocation.amount))
        .join(
            PurchaseAllocation,
            (PurchaseAllocation.org_id == PurchaseLine.org_id) & (PurchaseAllocation.purchase_line_id == PurchaseLine.id),
        )
        .filter(
            PurchaseLine.org_id == org_id,
            PurchaseLine.document_id.in_(set(freight)),
            PurchaseLine.id.notin_(freight_lines),
            PurchaseAllocation.status.in_(("active", "orphaned")),
            PurchaseAllocation.amount > 0,
        )
        .group_by(PurchaseLine.document_id)
    }
    for allocation in positive:
        if allocation.purchase_line_id in freight_lines:
            continue
        document_id = document_of.get(allocation.purchase_line_id)
        total, spend = value.get(document_id, ZERO), freight.get(document_id, ZERO)
        if total > 0 and spend > 0:
            shares[allocation.id] = spend * Decimal(str(allocation.amount)) / total
    return shares
