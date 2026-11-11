"""Things that need someone, contributed by features (spec live-cogs Gap 12).

Core shows them on Home ("Needs attention") and on Notifications without knowing any feature's
check: a feature registers a provider, and each provider decides for itself who may see its
items (permission, feature flag). A provider that fails is logged and skipped; it never takes
the page down.

An item: ``{"key", "label", "count", "severity", "href", "workspace"}`` and optionally
``"detail"``. ``href`` must be a same-origin path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.observability import get_logger

logger = get_logger(__name__)

Provider = Callable[[Any, UUID, Any], list[dict]]
_PROVIDERS: dict[str, Provider] = {}


def register(name: str, provider: Provider) -> None:
    _PROVIDERS[name] = provider


def collect(db, org_id: UUID, user) -> list[dict]:
    items: list[dict] = []
    for name, provider in list(_PROVIDERS.items()):
        try:
            for item in provider(db, org_id, user) or []:
                href = item.get("href")
                if not isinstance(href, str) or not href.startswith("/") or href.startswith("//"):
                    continue
                if int(item.get("count") or 0) > 0:
                    items.append(dict(item))
        except Exception:
            logger.exception("attention_provider_failed", provider=name, org_id=str(org_id))
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return items
