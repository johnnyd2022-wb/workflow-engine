"""Per-org feature entitlement check.

Thin wrapper over ``FeatureSubscriptionRepository`` so route/middleware/template code has
one obvious call: ``org_has_feature(session, org_id, "compliant")``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository


def org_has_feature(session: Session, org_id: UUID | str | None, feature_key: str) -> bool:
    """True iff ``org_id`` holds an ``active`` subscription to ``feature_key``.

    A falsy ``org_id`` (no tenant context) is never entitled.
    """
    if not org_id:
        return False
    if isinstance(org_id, str):
        try:
            org_id = UUID(org_id)
        except ValueError:
            return False
    return FeatureSubscriptionRepository(session).is_active(org_id, feature_key)
