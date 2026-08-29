"""Data access for per-org feature entitlements (``feature_subscriptions``).

Every method takes ``org_id`` explicitly and filters inline (conventions §2). No shared
scoped-query helper.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.utils.time import utc_now


class FeatureSubscriptionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, org_id: UUID, feature_key: str) -> FeatureSubscription | None:
        return (
            self.db.query(FeatureSubscription)
            .filter(
                FeatureSubscription.org_id == org_id,
                FeatureSubscription.feature_key == feature_key,
            )
            .first()
        )

    def is_active(self, org_id: UUID, feature_key: str) -> bool:
        row = self.get(org_id, feature_key)
        return bool(row and row.active)

    def list_for_org(self, org_id: UUID) -> list[FeatureSubscription]:
        return (
            self.db.query(FeatureSubscription)
            .filter(FeatureSubscription.org_id == org_id)
            .order_by(FeatureSubscription.feature_key)
            .all()
        )

    def grant(
        self,
        org_id: UUID,
        feature_key: str,
        granted_by_user_id: UUID | None = None,
        notes: str | None = None,
    ) -> FeatureSubscription:
        """Insert a new active grant, or re-activate + refresh an existing row.

        Idempotent: the ``(org_id, feature_key)`` unique constraint means at most one row
        ever exists for a pair; a repeat call leaves exactly one active row.
        """
        row = self.get(org_id, feature_key)
        if row is None:
            row = FeatureSubscription(
                org_id=org_id,
                feature_key=feature_key,
                active=True,
                granted_by_user_id=granted_by_user_id,
                notes=notes,
            )
            self.db.add(row)
        else:
            row.active = True
            row.granted_at = utc_now()
            if granted_by_user_id is not None:
                row.granted_by_user_id = granted_by_user_id
            if notes is not None:
                row.notes = notes
        self.db.commit()
        return row

    def revoke(self, org_id: UUID, feature_key: str) -> bool:
        """Deactivate the grant. Returns True if a row was changed, False if none existed."""
        row = self.get(org_id, feature_key)
        if row is None:
            return False
        if row.active:
            row.active = False
            self.db.commit()
        return True
