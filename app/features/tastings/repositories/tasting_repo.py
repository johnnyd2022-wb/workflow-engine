"""Explicit tenant-scoped, bounded tasting queries."""

from app.features.tastings.models import Tasting, TastingAllocation, TastingStockLot


class TastingRepository:
    def __init__(self, db):
        self.db = db

    def get(self, org_id, tasting_id, *, lock=False):
        query = self.db.query(Tasting).filter(Tasting.org_id == org_id, Tasting.id == tasting_id)
        if lock:
            query = query.with_for_update().populate_existing()
        return query.one_or_none()

    def allocations(self, org_id, tasting_id):
        return (
            self.db.query(TastingAllocation)
            .filter(TastingAllocation.org_id == org_id, TastingAllocation.tasting_id == tasting_id)
            .order_by(TastingAllocation.id)
            .all()
        )

    def events(self, org_id, start, end):
        return (
            self.db.query(Tasting)
            .filter(Tasting.org_id == org_id, Tasting.starts_at >= start, Tasting.starts_at < end)
            .order_by(Tasting.starts_at, Tasting.id)
            .limit(201)
            .all()
        )

    def pool(self, org_id, offset=0):
        return (
            self.db.query(TastingStockLot)
            .filter(TastingStockLot.org_id == org_id, TastingStockLot.remaining_volume_ml > 0)
            .order_by(TastingStockLot.created_at.desc(), TastingStockLot.id)
            .offset(offset)
            .limit(51)
            .all()
        )

    def removals(self, org_id, start, end):
        return (
            self.db.query(TastingStockLot)
            .filter(
                TastingStockLot.org_id == org_id,
                TastingStockLot.creates_removal == 1,
                TastingStockLot.removed_on >= start,
                TastingStockLot.removed_on < end,
            )
            .order_by(TastingStockLot.removed_on, TastingStockLot.id)
            .all()
        )
