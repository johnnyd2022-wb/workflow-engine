"""Design review L1: a month's stock value stays provisional until the month is closed.

`.agents/reports/design-review/2026-11-17-mcp-costing-planning-analytics.md` §L1: the month-end
snapshot was taken on the first Xero sync or costing read after the month ended, priced at the costs
known at that moment, with B (purchases recorded in the period) frozen, and never changed. On the 1st
most of last month's card spend and bills aren't recorded yet, so the closed value was priced on
estimates and the accountant's CSV was the frozen one.

Now the automatic month-end snapshot freezes the quantities at the cutoff, and its valuation is
provisional: every read re-prices those quantities with today's costs. Closing it (a person with
``costs.manage``, or the first sync or session read on or after the 20th of the next month) writes
the valuation once; from then on it doesn't move (AC143).

Dates: the clock is moved to the month after next, so the month that has just "ended" ends in the
future and every row a test writes is inside it (the quantities are exact).
"""

# ruff: noqa: F811 -- fixtures are re-exported and used as test arguments

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.core.db.models.user import UserRole
from tests.costing_helpers import D, login, lot, new_org, price, purge, user_client
from tests.factories import UserFactory
from tests.mcp_oauth.support import bearer, make_client, mint_grant, unique_addr
from tests.org_purge import purge_orgs
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import _link, _sync_purchase
from tests.test_costing_bridge import world  # noqa: F401 -- fixture re-export
from tests.test_costing_purchases import sync

API = "/api/core/costing"


def _real_today() -> date:
    from app.features.costing import purchase_sources

    return purchase_sources.nz_today()


REAL_TODAY = _real_today()  # read before any test moves the clock


def _month_after_next(day: int) -> date:
    real = REAL_TODAY
    index = real.year * 12 + real.month - 1 + 2
    return date(index // 12, index % 12 + 1, day)


def _last_day_before(day: date) -> date:
    return day.replace(day=1) - timedelta(days=1)


def _clock(monkeypatch, today):
    monkeypatch.setattr("app.features.costing.purchase_sources.nz_today", lambda: today)


def _month_end(client):
    response = client.get(f"{API}/stock-value/snapshots")
    assert response.status_code == 200, response.get_json()
    (snapshot,) = [s for s in response.get_json()["snapshots"] if s["kind"] == "month_end"]
    return snapshot


def _detail(client, snapshot_id):
    response = client.get(f"{API}/stock-value/snapshots/{snapshot_id}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _roll(client, opening_id, closing_id):
    response = client.get(f"{API}/bridge?from={opening_id}&to={closing_id}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _close(client, snapshot_id, expect=200):
    response = client.post(
        f"{API}/stock-value/snapshots/{snapshot_id}/close", json={}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == expect, response.get_json()
    return response.get_json()


def _month_with_a_late_bill(world, db, monkeypatch):
    """Juniper 10 kg at $5 on hand; Orris 4 kg received during the month with its bill not in Xero yet.
    The clock is then the 3rd of the next month and the sync takes the month-end snapshot."""
    from app.features.costing import stock_value

    org = world["org"]
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    today = _month_after_next(3)
    month_end = _last_day_before(today)
    opening = stock_value.take_snapshot(
        db, org.id, kind="manual", trigger="manual", as_of_date=_last_day_before(month_end)
    )
    db.commit()
    orris = lot(db, org.id, "Orris", 4, "kg")  # received in the month: no cost until the bill is recorded
    _clock(monkeypatch, today)
    result = sync(db, org.id)
    assert result.success, result.errors
    return opening, orris, month_end


def _record_late_bill(world, db, client, orris, month_end):
    """The bill for the Orris, dated in the month, arrives in Xero on the 3rd and is recorded against the lot."""
    _doc, line, *_ = _sync_purchase(world["sync"], db, "80", on=month_end - timedelta(days=2), description="Orris")
    linked = _link(client, line.id, [{"inventory_item_id": str(orris.id), "amount": "80"}])
    assert linked.status_code == 200, linked.get_json()


# --- (1) a late purchase moves the provisional month ------------------------------------------------


def test_l1_a_purchase_recorded_after_month_end_reprices_the_provisional_month(world, db, monkeypatch):
    client = world["client"]
    opening, orris, month_end = _month_with_a_late_bill(world, db, monkeypatch)
    closing = _month_end(client)
    assert closing["as_of_date"] == month_end.isoformat() and closing["trigger"] == "xero_sync"
    first = _detail(client, closing["id"])
    assert D(first["total"]) == D("50") and first["unknown_lots"] == 1
    assert D(_roll(client, opening.id, closing["id"])["roll_forward"]["purchases"]) == D("0")

    _record_late_bill(world, db, client, orris, month_end)

    after = _detail(client, closing["id"])
    assert D(after["total"]) == D("130") and after["unknown_lots"] == 0
    orris_line = next(line for line in after["lines"] if line["name"] == "Orris")
    assert D(orris_line["value"]) == D("80") and orris_line["status"] == "actual"
    assert D(_month_end(client)["total"]) == D("130")  # the list says the same
    body = _roll(client, opening.id, closing["id"])
    roll = body["roll_forward"]
    assert (D(roll["opening"]), D(roll["purchases"]), D(roll["closing"])) == (D("50"), D("80"), D("130"))
    assert roll["balanced"] is True
    assert after["status"] == "provisional" and body["provisional"] is True

    exported = client.get(f"{API}/stock-value/snapshots/{closing['id']}/export.csv")
    rows = list(csv.reader(io.StringIO(exported.get_data(as_text=True))))
    assert rows[0][0] == "Provisional — not closed"
    total_row = next(r for r in rows if r and r[0] == "Total")
    assert total_row[6] == "130.00"


# --- (2) after close, the same late purchase changes nothing ----------------------------------------


def test_l1_after_close_the_same_late_purchase_changes_nothing(world, db, monkeypatch):
    from app.core.db.models.audit_log import AuditLog

    org, client = world["org"], world["client"]
    opening, orris, month_end = _month_with_a_late_bill(world, db, monkeypatch)
    closing = _month_end(client)

    closed = _close(client, closing["id"])
    assert closed["status"] == "closed" and closed["closed_at"] and closed["closed_automatically"] is False
    audit = db.query(AuditLog).filter(AuditLog.org_id == org.id, AuditLog.action == "stock_value_month_closed").one()
    assert str(audit.entity_id) == closing["id"]
    _close(client, closing["id"], expect=409)  # already closed

    before = _detail(client, closing["id"])
    roll_before = _roll(client, opening.id, closing["id"])["roll_forward"]
    _record_late_bill(world, db, client, orris, month_end)

    after = _detail(client, closing["id"])
    assert after["status"] == "closed"
    assert {k: after[k] for k in ("total", "categories", "split", "unknown_lots")} == {
        k: before[k] for k in ("total", "categories", "split", "unknown_lots")
    }
    assert after["lines"] == before["lines"] and D(after["total"]) == D("50")
    body = _roll(client, opening.id, closing["id"])
    assert body["roll_forward"] == roll_before and body["provisional"] is False
    changes = after["changes_since_close"]
    assert (D(changes["total_now"]), D(changes["delta"])) == (D("130"), D("80"))
    assert (D(changes["purchases_then"]), D(changes["purchases_now"])) == (D("0"), D("80"))
    exported = client.get(f"{API}/stock-value/snapshots/{closing['id']}/export.csv").get_data(as_text=True)
    assert "Provisional" not in exported


# --- (3) it closes itself on the 20th, not before; a token never closes it ----------------------------


@pytest.fixture
def plain(db, flask_app):
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


def test_l1_the_month_closes_itself_on_the_20th_and_not_before(plain, db, monkeypatch):
    org, client = plain
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)

    _clock(monkeypatch, _month_after_next(5))
    assert client.get(f"{API}/stock-value").status_code == 200
    snapshot = _month_end(client)
    assert snapshot["status"] == "provisional" and snapshot["closes_on"] == _month_after_next(20).isoformat()

    _clock(monkeypatch, _month_after_next(19))
    client.get(f"{API}/stock-value")
    assert _month_end(client)["status"] == "provisional"

    _clock(monkeypatch, _month_after_next(20))
    client.get(f"{API}/stock-value")
    closed = _month_end(client)
    assert closed["status"] == "closed" and closed["closed_automatically"] is True
    assert D(closed["total"]) == D("50")


@pytest.fixture
def assistant_org(db, flask_app):
    """An org with costing, assistants on for admins, and an admin with a session and a read token
    (the shape of tests/openapi/test_token_reads_write_nothing.py's fixture)."""
    from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings, OAuthClient

    org = new_org(db)
    org_id = org.id
    admin = UserFactory(org_id=org.id, email=f"drl1-{org.id.hex[:8]}@example.test", role=UserRole.ADMIN)
    db.add(McpOrgSettings(org_id=org.id, enabled=True, allow_unverified_clients=True))
    db.add(McpAllowedRole(org_id=org.id, role_key="builtin:admin"))
    db.commit()
    client_row = make_client(db)
    client_pk = client_row.id
    _grant, access, _refresh = mint_grant(db, admin, client_row)
    token = flask_app.test_client()
    token.environ_base.update(
        {"wsgi.url_scheme": "https", "HTTP_X_FORWARDED_PROTO": "https", "REMOTE_ADDR": unique_addr()}
    )
    with flask_app.app_context():
        yield {"org": org, "token": token, "headers": bearer(access), "session": login(flask_app, admin.email)}
    db.rollback()
    purge_orgs(db, [org_id])
    db.query(OAuthClient).filter(OAuthClient.id == client_pk).delete(synchronize_session=False)  # only ours
    db.commit()


def test_l1_reading_the_snapshot_itself_on_the_20th_closes_it(plain, db, monkeypatch):
    org, client = plain
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    _clock(monkeypatch, _month_after_next(5))
    snapshot = _month_end(client)
    assert snapshot["status"] == "provisional"

    _clock(monkeypatch, _month_after_next(21))
    exported = client.get(f"{API}/stock-value/snapshots/{snapshot['id']}/export.csv").get_data(as_text=True)
    assert "Provisional" not in exported
    assert _detail(client, snapshot["id"])["status"] == "closed"


def test_l1_a_token_read_never_closes_the_month(assistant_org, db, monkeypatch):
    from app.features.costing.models import StockValueSnapshot

    org = assistant_org["org"]
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    _clock(monkeypatch, _month_after_next(5))
    assert assistant_org["session"].get(f"{API}/stock-value").status_code == 200  # takes it, provisional

    _clock(monkeypatch, _month_after_next(25))
    response = assistant_org["token"].get(f"{API}/stock-value", headers=assistant_org["headers"])
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    db.expire_all()
    (snapshot,) = db.query(StockValueSnapshot).filter(StockValueSnapshot.org_id == org.id).all()
    assert snapshot.kind == "month_end" and snapshot.status == "provisional"

    assistant_org["session"].get(f"{API}/stock-value")
    assert _month_end(assistant_org["session"])["status"] == "closed"


# --- (4) close the oldest first --------------------------------------------------------------------------


def test_l1_a_month_cant_be_closed_while_an_earlier_one_is_provisional(plain, db, flask_app, monkeypatch):
    from app.features.costing import stock_value

    org, client = plain
    lot(db, org.id, "Juniper", 10, "kg")
    _clock(monkeypatch, _month_after_next(5))
    (older,) = stock_value.ensure_month_end_snapshots(db, org.id, trigger="costing_read")
    db.commit()
    later = _month_after_next(5)
    later = date(later.year + (later.month == 12), later.month % 12 + 1, 5)
    _clock(monkeypatch, later)
    (newer,) = stock_value.ensure_month_end_snapshots(db, org.id, trigger="costing_read")
    db.commit()
    assert (older.status, newer.status) == ("provisional", "provisional")

    refused = _close(client, newer.id, expect=409)
    assert "first" in refused["error"]
    viewer = user_client(db, flask_app, org, permissions=["costs.view", "inventory.view"])
    denied = viewer.post(
        f"{API}/stock-value/snapshots/{older.id}/close", json={}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert denied.status_code == 403
    other = new_org(db)
    try:
        _close(user_client(db, flask_app, other), older.id, expect=404)
    finally:
        purge(db, other)

    assert _close(client, older.id)["status"] == "closed"
    assert _close(client, newer.id)["status"] == "closed"


# --- (5) the migration ----------------------------------------------------------------------------------


def test_l1_migration_marks_existing_snapshots_closed_and_downgrade_refuses_provisional(plain, db):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    org, _client = plain
    migration = importlib.import_module("app.core.db.migrations.versions.costing_stock_002")
    assert migration.down_revision == "mcp_oauth_001"
    db.commit()
    insert = text(
        "INSERT INTO stock_value_snapshots (id, org_id, kind, as_of_date, cutoff_at, trigger) "
        "VALUES (:id, :org, 'manual', '2026-10-31', now(), 'manual')"
    )
    with db.get_bind().connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                provisional = uuid4()
                connection.execute(insert, {"id": provisional, "org": org.id})
                connection.execute(
                    text("UPDATE stock_value_snapshots SET status = 'provisional' WHERE id = :id"), {"id": provisional}
                )
                with pytest.raises(RuntimeError, match="provisional"):
                    migration.downgrade()
                connection.execute(text("DELETE FROM stock_value_snapshots WHERE id = :id"), {"id": provisional})

                migration.downgrade()
                existing = uuid4()
                connection.execute(insert, {"id": existing, "org": org.id})  # a row from before this change
                migration.upgrade()
                status, closed_at = connection.execute(
                    text("SELECT status, closed_at FROM stock_value_snapshots WHERE id = :id"), {"id": existing}
                ).one()
                assert status == "closed" and closed_at is not None
        finally:
            transaction.rollback()
