"""GL-C06: the demo's exception loop seeds through the real services.

`scripts/demo_orgs.py load` is only run before a demo, so a signature change in
lot_holds / sales_returns / recalls would otherwise surface in front of a prospect.
This runs the established org's seeds plus `_seed_exceptions` once and checks what
docs/demo-script.md promises, then purges the org.
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import demo_orgs  # noqa: E402
import ui_shots  # noqa: E402


@pytest.fixture
def seeded_org(db):
    from app.core.db.repositories.inventory_repo import InventoryRepository

    org, user = demo_orgs._make_org(
        db,
        f"{demo_orgs.PREFIX}test {uuid.uuid4().hex[:6]}",
        f"demo-{uuid.uuid4().hex[:8]}@example.test",
        "pw-Test-123!",
    )
    try:
        inv = InventoryRepository(db)
        for kind in ("stock", "lineage", "sales"):
            getattr(ui_shots, f"_seed_{kind}")(db, org.id, inv)
        demo_orgs._seed_exceptions(db, org.id, user)
        yield org
    finally:
        db.rollback()
        ui_shots.purge_seeded_org(db, org.id, user.id)


def test_exception_loop_matches_the_demo_script(db, seeded_org):
    from app.core.db.models.lot_hold import LotHold
    from app.features.crm.models.sales_return import SalesReturn
    from app.features.crm.models.xero_credit_note_line import XeroCreditNoteLine
    from app.features.recalls.models import Recall, RecallContact

    org_id = seeded_org.id
    holds = db.query(LotHold).filter(LotHold.org_id == org_id).all()
    open_holds = [h for h in holds if h.released_at is None]
    released = [h for h in holds if h.released_at is not None]
    assert len(open_holds) == 2  # the lab check, plus the damaged return's own lot
    assert len(released) == 1
    # "held last month and released": the release reads as a past event, not today.
    assert released[0].released_at < datetime.now(UTC) - timedelta(days=7)
    assert released[0].placed_at < released[0].released_at

    (line,) = db.query(XeroCreditNoteLine).filter(XeroCreditNoteLine.org_id == org_id).all()
    assert line.quantity == 2
    (back,) = db.query(SalesReturn).filter(SalesReturn.org_id == org_id).all()
    assert back.condition == "damaged" and back.quantity == 1  # one back damaged, one to decide

    (drill,) = db.query(Recall).filter(Recall.org_id == org_id).all()
    assert drill.is_drill
    contacts = db.query(RecallContact).filter(RecallContact.recall_id == drill.id).all()
    assert sum(1 for c in contacts if c.notice_sent_at) == min(2, len(contacts))
    assert sum(1 for c in contacts if c.acknowledged_at) == (1 if contacts else 0)
