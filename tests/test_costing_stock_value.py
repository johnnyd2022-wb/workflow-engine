"""Live-cogs 8.1g: stock value and snapshots (spec .agents/specs/live-cogs.md, "8.1g build contract").

Written before the implementation. Each test names the acceptance criterion it proves.
World W (the spec's): Juniper 10 kg at $5 with 3 kg in an unfinished batch ($15 pool), Orris 1 kg
at $30 plus 2 kg unpriced (estimated $60), Mystery 5 kg with no cost, Gin 12 bottles at $120,
Mash 6 L at $30.
"""

# ruff: noqa: F811 -- flask_app is re-exported as a fixture and used as a test argument

from __future__ import annotations

import csv
import io
from datetime import date
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryType
from app.core.db.models.user import UserRole
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.utils.time import utc_now
from tests.costing_helpers import D, complete, lot, new_org, price, purge, user_client, workflow
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export

API = "/api/core/costing"
FINAL = InventoryType.FINAL_PRODUCT.value
WIP = InventoryType.WORK_IN_PROGRESS.value


@pytest.fixture
def world(db, flask_app):
    org = new_org(db)
    client = user_client(db, flask_app, org)
    yield org, client
    purge(db, org)


def _world_w(db, client, org):
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    execution, (macerate, _bottle) = workflow(db, org.id, [[], [{"name": "Gin", "unit": "bottles"}]])
    complete(client, execution, macerate, [(juniper, 3, "kg")], [])  # $15 consumed, nothing out yet
    orris_one = lot(db, org.id, "Orris", 1, "kg")
    price(db, org.id, orris_one.id, 30, 1)
    orris_two = lot(db, org.id, "Orris", 2, "kg")  # no price of its own: estimated from the last price paid
    mystery = lot(db, org.id, "Mystery", 5, "kg")
    gin = lot(db, org.id, "Gin", 12, "bottles", inventory_type=FINAL)
    price(db, org.id, gin.id, 120, 12)
    mash = lot(db, org.id, "Mash", 6, "L", inventory_type=WIP)
    price(db, org.id, mash.id, 30, 6)
    return {
        "juniper": juniper,
        "orris_one": orris_one,
        "orris_two": orris_two,
        "mystery": mystery,
        "gin": gin,
        "mash": mash,
        "execution": execution,
    }


def _stock(client):
    response = client.get(f"{API}/stock-value")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _lots(body):
    return {(line["name"], line["quantity"]): line for line in body["lines"] if line["kind"] == "lot"}


def _by_name(body):
    return {line["name"]: line for line in body["lines"] if line["kind"] == "lot"}


def _snapshots(client):
    response = client.get(f"{API}/stock-value/snapshots")
    assert response.status_code == 200, response.get_json()
    return response.get_json()["snapshots"]


def _sell(db, org, name, quantity):
    InventoryRepository(db).consume_final_product_fifo(org.id, name, str(quantity))


def _waste(client, item, quantity):
    response = client.post(
        "/api/core/inventory/wastage",
        json={"entries": [{"inventory_item_id": str(item.id), "quantity_wasted": str(quantity), "reason": "spillage"}]},
    )
    assert response.status_code == 201, response.get_json()


# --- AC129 / AC130 / AC131: stock value now -------------------------------------------------------


def test_ac129_stock_value_now_for_world_w(world, db):
    org, client = world
    _world_w(db, client, org)

    body = _stock(client)

    assert D(body["total"]) == D("290")
    assert {name: D(c["value"]) for name, c in body["categories"].items()} == {
        "raw": D("125"),
        "in_production": D("15"),
        "wip": D("30"),
        "finished": D("120"),
    }
    assert (D(body["split"]["actual"]), D(body["split"]["estimated"]), D(body["split"]["partial"])) == (
        D("230"),
        D("60"),
        D("0"),
    )
    assert body["unknown_lots"] == 1 and body["partial_lots"] == 0 and body["complete"] is False
    lines = _by_name(body)
    assert D(lines["Juniper"]["quantity"]) == D("7") and D(lines["Juniper"]["value"]) == D("35")
    assert [line for line in body["lines"] if line["kind"] == "in_production"][0]["value"] == "15.0000"


def test_ac130_unknown_cost_is_never_zero_and_partial_is_a_floor(world, db):
    org, client = world
    _world_w(db, client, org)
    mystery = _by_name(_stock(client))["Mystery"]
    assert mystery["status"] == "unknown"
    assert mystery["unit_cost"] is None and mystery["value"] is None and mystery["known_unit_cost"] is None

    other_org = new_org(db)
    other = user_client(db, client.application, other_org)
    try:
        orris = lot(db, other_org.id, "Orris", 2, "kg")
        price(db, other_org.id, orris.id, 60, 2)
        unknown = lot(db, other_org.id, "Mystery", 5, "kg")
        execution, (step,) = workflow(db, other_org.id, [[{"name": "Tonic", "unit": "bottles"}]])
        complete(
            other,
            execution,
            step,
            [(orris, 1, "kg"), (unknown, 1, "kg")],
            [{"name": "Tonic", "quantity": 3, "unit": "bottles"}],
        )
        body = _stock(other)
        tonic = _by_name(body)["Tonic"]
        assert tonic["status"] == "partial" and tonic["unit_cost"] is None
        assert D(tonic["known_unit_cost"]) == D("10") and D(tonic["value"]) == D("30")
        assert (D(body["split"]["actual"]), D(body["split"]["estimated"]), D(body["split"]["partial"])) == (
            D("30"),
            D("0"),
            D("30"),
        )
        assert D(body["total"]) == D("60")
        assert body["unknown_lots"] == 1 and body["partial_lots"] == 1 and body["complete"] is False
    finally:
        purge(db, other_org)


def test_ac131_empty_lots_and_finished_batch_leftovers_are_not_stock(world, db):
    org, client = world
    juniper = lot(db, org.id, "Juniper", 10, "kg")
    price(db, org.id, juniper.id, 50, 10)
    empty = lot(db, org.id, "Empty", 1, "kg")
    price(db, org.id, empty.id, 9, 1)
    InventoryRepository(db).set_inventory_item_quantity(empty.id, org.id, "0")
    # A batch that finishes having consumed 2 kg ($10) and made nothing: a production loss.
    done, (only,) = workflow(db, org.id, [[]])
    complete(client, done, only, [(juniper, 2, "kg")], [])
    # A batch still running with 1 kg ($5) consumed: stock in production.
    running, (first, _second) = workflow(db, org.id, [[], [{"name": "Gin", "unit": "bottles"}]])
    complete(client, running, first, [(juniper, 1, "kg")], [])

    body = _stock(client)

    assert "Empty" not in _by_name(body)
    assert D(_by_name(body)["Juniper"]["value"]) == D("35")  # 7 kg left
    assert D(body["categories"]["in_production"]["value"]) == D("5")
    assert D(body["total"]) == D("40")  # the $10 lost in the finished batch is not here
    assert body["complete"] is True


# --- AC132: a snapshot is held fixed --------------------------------------------------------------


def test_ac132_manual_snapshot_freezes_the_figures(world, db):
    org, client = world
    things = _world_w(db, client, org)
    now = _stock(client)

    taken = client.post(f"{API}/stock-value/snapshot", json={}, headers={"Idempotency-Key": str(uuid4())})
    assert taken.status_code == 201, taken.get_json()
    snap = taken.get_json()
    assert snap["kind"] == "manual" and snap["trigger"] == "manual"
    assert D(snap["total"]) == D(now["total"]) == D("290")
    assert {k: v["value"] for k, v in snap["categories"].items()} == {
        k: v["value"] for k, v in now["categories"].items()
    }

    _sell(db, org, "Gin", 2)
    price(db, org.id, things["juniper"].id, 110, 10)  # Juniper now $11/kg
    _waste(client, things["orris_two"], 1)

    moved = _stock(client)
    assert D(moved["total"]) != D("290")
    detail = client.get(f"{API}/stock-value/snapshots/{snap['id']}").get_json()
    assert D(detail["total"]) == D("290")
    assert {(ln["name"], ln["quantity"], ln["value"]) for ln in detail["lines"]} == {
        (ln["name"], ln["quantity"], ln["value"]) for ln in now["lines"]
    }
    assert [s["id"] for s in _snapshots(client)] == [snap["id"]]
    # "Changes since close" re-prices what was on hand then: Juniper 7 kg now $11 (+42) and the
    # $15 pool of 3 kg now $33 (+18). The snapshot itself stays at 290.
    changes = detail["changes_since_close"]
    assert (D(changes["total_then"]), D(changes["total_now"]), D(changes["delta"])) == (D("290"), D("350"), D("60"))


# --- AC133 / AC135: automatic month-end snapshots -------------------------------------------------


def _clock(monkeypatch, today):
    monkeypatch.setattr("app.features.costing.purchase_sources.nz_today", lambda: today)


def _two_months_on():
    """A date a month and a bit after this one, so the last completed month ends in the future
    (its cutoff is after every row a test writes: the snapshot is exact)."""
    from app.features.costing.purchase_sources import nz_today

    real = nz_today()
    index = real.year * 12 + real.month - 1 + 2
    return date(index // 12, index % 12 + 1, 5)


def _last_day_before(day):
    return date.fromordinal(day.replace(day=1).toordinal() - 1)


def test_ac133_first_costing_read_takes_the_month_end_snapshot_without_xero(world, db, monkeypatch):
    org, client = world
    _world_w(db, client, org)
    today = _two_months_on()
    _clock(monkeypatch, today)

    first = _stock(client)
    snaps = _snapshots(client)
    assert len(snaps) == 1
    assert (snaps[0]["kind"], snaps[0]["trigger"], snaps[0]["as_of_date"]) == (
        "month_end",
        "costing_read",
        _last_day_before(today).isoformat(),
    )
    assert D(snaps[0]["total"]) == D(first["total"]) == D("290")
    _stock(client)
    assert len(_snapshots(client)) == 1  # a second read takes nothing


def test_ac133_with_xero_a_read_takes_none_and_the_first_sync_takes_it(world, db, monkeypatch):
    from tests.test_costing_purchases import FakeXero, connect, sync

    org, client = world
    connect(db, org.id)
    FakeXero().install(monkeypatch)
    _world_w(db, client, org)
    today = _two_months_on()
    _clock(monkeypatch, today)

    _stock(client)
    assert _snapshots(client) == []

    result = sync(db, org.id)
    assert result.success, result.errors
    (snap,) = _snapshots(client)
    assert (snap["kind"], snap["trigger"], snap["as_of_date"]) == (
        "month_end",
        "xero_sync",
        _last_day_before(today).isoformat(),
    )


def test_ac133_a_failing_snapshot_never_fails_the_sync(world, db, monkeypatch):
    from app.features.costing import stock_value
    from tests.test_costing_purchases import FakeXero, connect, sync

    org, client = world
    connect(db, org.id)
    FakeXero().install(monkeypatch)
    _world_w(db, client, org)
    _clock(monkeypatch, _two_months_on())

    def boom(*_args, **_kwargs):
        raise RuntimeError("snapshot exploded")

    monkeypatch.setattr(stock_value, "take_snapshot", boom)
    result = sync(db, org.id)
    assert result.success, result.errors
    assert _snapshots(client) == []


def test_ac135_two_missed_months_are_two_snapshots_oldest_first_and_no_stock_means_none(world, db, monkeypatch):
    from app.features.costing import stock_value

    org, client = world
    _world_w(db, client, org)
    today = _two_months_on()
    _clock(monkeypatch, today)
    (first,) = stock_value.ensure_month_end_snapshots(db, org.id, trigger="costing_read")
    db.commit()
    assert first.as_of_date == _last_day_before(today)

    later = date(today.year + (today.month + 2 > 12), (today.month + 1) % 12 + 1, 5)  # two months on again
    _clock(monkeypatch, later)
    made = stock_value.ensure_month_end_snapshots(db, org.id, trigger="costing_read")
    db.commit()
    dates = [s.as_of_date for s in made]
    assert len(dates) == 2 and dates == sorted(dates) and dates[0] > first.as_of_date
    assert dates[-1] == _last_day_before(later)

    empty_org = new_org(db)
    try:
        assert stock_value.ensure_month_end_snapshots(db, empty_org.id, trigger="costing_read") == []
    finally:
        purge(db, empty_org)


# --- AC134: as at the cutoff, not at the moment it was taken --------------------------------------


def test_ac134_later_movements_are_reversed_out_of_a_late_snapshot(world, db):
    from app.features.costing import stock_value

    org, client = world
    gin = lot(db, org.id, "Gin", 12, "bottles", inventory_type=FINAL)
    price(db, org.id, gin.id, 120, 12)
    cutoff = utc_now()
    _sell(db, org, "Gin", 2)
    _waste(client, gin, 1)
    lot(db, org.id, "Rum", 5, "L")  # made after the cutoff

    snap = stock_value.take_snapshot(db, org.id, kind="manual", trigger="manual", cutoff_at=cutoff)
    db.commit()

    payload = client.get(f"{API}/stock-value/snapshots/{snap.id}").get_json()
    lines = _by_name(payload)
    assert set(lines) == {"Gin"}
    assert D(lines["Gin"]["quantity"]) == D("12") and D(lines["Gin"]["value"]) == D("120")
    assert D(payload["total"]) == D("120") and payload["quantity_basis"] == "reconstructed"
    assert D(_stock(client)["total"]) == D("90")  # 9 bottles on hand now


# --- AC136: permissions, isolation, the daily cap -------------------------------------------------


def test_ac136_view_manage_isolation_feature_and_daily_cap(world, db, flask_app):
    from app.features.costing import stock_value

    org, client = world
    _world_w(db, client, org)
    snap = client.post(f"{API}/stock-value/snapshot", json={}, headers={"Idempotency-Key": str(uuid4())}).get_json()

    production = user_client(db, flask_app, org, role=UserRole.PRODUCTION)
    assert production.get(f"{API}/stock-value").status_code == 403
    viewer = user_client(db, flask_app, org, permissions=["costs.view", "inventory.view"])
    assert viewer.get(f"{API}/stock-value").status_code == 200
    assert viewer.get(f"{API}/stock-value/snapshots/{snap['id']}").status_code == 200
    denied = viewer.post(f"{API}/stock-value/snapshot", json={}, headers={"Idempotency-Key": str(uuid4())})
    assert denied.status_code == 403
    manager = user_client(db, flask_app, org, permissions=["costs.manage"])
    assert (
        manager.post(f"{API}/stock-value/snapshot", json={}, headers={"Idempotency-Key": str(uuid4())}).status_code
        == 201
    )

    other_org = new_org(db)
    off_org = new_org(db, grant=False)
    try:
        other = user_client(db, flask_app, other_org)
        assert other.get(f"{API}/stock-value/snapshots/{snap['id']}").status_code == 404
        assert other.get(f"{API}/stock-value/snapshots/{snap['id']}/export.csv").status_code == 404
        off = user_client(db, flask_app, off_org)
        for path in ("/stock-value", "/stock-value/snapshots", "/bridge"):
            assert off.get(f"{API}{path}").status_code == 404
        assert off.post(f"{API}/stock-value/snapshot", json={}).status_code == 404

        capped = new_org(db)
        capped_client = user_client(db, flask_app, capped)
        lot(db, capped.id, "Juniper", 1, "kg")
        for _ in range(20):
            stock_value.take_snapshot(db, capped.id, kind="manual", trigger="manual")
        db.commit()
        over = capped_client.post(f"{API}/stock-value/snapshot", json={}, headers={"Idempotency-Key": str(uuid4())})
        assert over.status_code == 400 and "20" in over.get_json()["error"]
        purge(db, capped)
    finally:
        purge(db, other_org, off_org)


# --- AC137: the accountant's CSV ------------------------------------------------------------------


def test_ac137_csv_export_leaves_unknown_cost_blank_and_escapes_formulas(world, db):
    org, client = world
    _world_w(db, client, org)
    evil = lot(db, org.id, "=HYPERLINK(1)", 2, "kg")
    price(db, org.id, evil.id, 10, 2)
    snap = client.post(f"{API}/stock-value/snapshot", json={}, headers={"Idempotency-Key": str(uuid4())}).get_json()

    response = client.get(f"{API}/stock-value/snapshots/{snap['id']}/export.csv")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in response.headers["Content-Disposition"] and ".csv" in response.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    header = rows[0]
    assert header[:8] == ["Category", "Item", "Batch", "Quantity", "Unit", "Unit cost", "Value", "Cost status"]
    by_item = {r[1]: r for r in rows[1:] if len(r) >= 8}
    assert by_item["Mystery"][5] == "" and by_item["Mystery"][6] == "" and by_item["Mystery"][7] == "unknown"
    assert by_item["Juniper"][6] == "35.00" and by_item["Juniper"][4] == "kg"
    assert "'=HYPERLINK(1)" in by_item and "=HYPERLINK(1)" not in by_item
    text = response.get_data(as_text=True)
    assert "Total" in text and "1 lot has no cost" in text
    subtotals = {r[1]: r for r in rows if r and r[0] == "Subtotal"}
    assert subtotals["Raw materials"][6] == "135.00"  # Juniper 35 + Orris 30 + 60 + the escaped lot's 10
    assert subtotals["Finished goods"][6] == "120.00"
    assert subtotals["In production"][6] == "15.00"


# --- AC146: the migration -------------------------------------------------------------------------


def test_ac146_one_alembic_head_and_tables_exist(db):
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "app" / "core" / "db" / "migrations"))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1
    tables = set(inspect(db.get_bind()).get_table_names())
    assert {"stock_value_snapshots", "stock_value_lines", "stock_value_movements"} <= tables


def test_ac146_downgrade_refuses_while_a_snapshot_exists(world, db):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.features.costing import stock_value

    org, _client = world
    lot(db, org.id, "Juniper", 1, "kg")
    stock_value.take_snapshot(db, org.id, kind="manual", trigger="manual")
    db.commit()

    migration = importlib.import_module("app.core.db.migrations.versions.costing_stock_001")
    assert migration.revision == "costing_stock_001" and migration.down_revision == "costing_rules_002"
    with db.get_bind().connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="snapshot"):
                    migration.downgrade()
        finally:
            transaction.rollback()
