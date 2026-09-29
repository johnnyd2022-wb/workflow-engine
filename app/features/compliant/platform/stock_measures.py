"""Generic stock-measure contracts for pluggable Compliant modules.

Core owns stock, places, counts and movements. A module may add what its regulator
measures on that stock (for example a quantity of alcohol and the duty on it), which
movements the regulator treats as leaving or returning, and what has already been
declared. Core renders these through the labels the module supplies, without knowing the
industry, the regulator or the unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class StockFlow:
    """A regulated movement: ``out`` of the controlled area (e.g. a sale) or back ``in``."""

    item: Any
    quantity: Decimal
    direction: str


class StockMeasureProvider(Protocol):
    labels: dict[str, str]

    def applies(self, session: Session, org_id: UUID) -> bool: ...

    def measure(self, session: Session, org_id: UUID, pairs: list, on: date) -> list[dict]: ...

    def flows(self, session: Session, org_id: UUID, start: date, end: date) -> list[StockFlow]: ...

    def declared(self, session: Session, org_id: UUID, start: date | None, end: date) -> dict[str, str]: ...

    def declared_periods(self, session: Session, org_id: UUID, limit: int) -> list[dict]: ...

    def product_key(self, name: str) -> str: ...


_BLANK = {"measure": None, "cost": None, "detail": None}


def _providers() -> tuple[StockMeasureProvider, ...]:
    """Explicit install-time composition; add an industry pack here, never in Core."""
    from app.features.compliant.modules.nz_alcohol.stock_measures import NZAlcoholStockMeasures

    return (NZAlcoholStockMeasures(),)


def provider_for(session: Session, org_id: UUID) -> StockMeasureProvider | None:
    return next((p for p in _providers() if p.applies(session, org_id)), None)


def labels(session: Session, org_id: UUID) -> dict[str, str]:
    """Copy for Core's stock screens; empty when no module measures this tenant's stock."""
    provider = provider_for(session, org_id)
    return dict(provider.labels) if provider else {}


def measure(session: Session, org_id: UUID, pairs: list, on: date) -> list[dict]:
    """``{"measure", "cost", "detail"}`` per (item, signed quantity); blanks where unknown."""
    provider = provider_for(session, org_id)
    if provider is None or not pairs:
        return [dict(_BLANK) for _ in pairs]
    return provider.measure(session, org_id, pairs, on)


def flows(session: Session, org_id: UUID, start: date, end: date) -> list[StockFlow] | None:
    """Regulated movements in [start, end), or None when no module tracks them."""
    provider = provider_for(session, org_id)
    return provider.flows(session, org_id, start, end) if provider else None


def declared(session: Session, org_id: UUID, start: date | None, end: date) -> dict[str, str]:
    provider = provider_for(session, org_id)
    return provider.declared(session, org_id, start, end) if provider else {}


def declared_periods(session: Session, org_id: UUID, limit: int = 24) -> list[dict]:
    provider = provider_for(session, org_id)
    return provider.declared_periods(session, org_id, limit) if provider else []


def product_key(session: Session, org_id: UUID, name: str) -> str:
    provider = provider_for(session, org_id)
    return provider.product_key(name) if provider else name
