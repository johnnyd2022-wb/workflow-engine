"""Live-cogs polish batch 2 (after 8.1f): items from "Still open" in .agents/plans/live-cogs-polish.md.

AC1  Readiness: once its engine budget is spent, each later product is costed on a budget of its
     own, so a list row never reads "not ready" when the product's own page says ready.
AC2  A material row that ran out of budget is never kept for the next product to reuse.
AC3  "Remember this" on an existing rule keeps the payee and description as the person typed them.
AC4  Costing settings are read once per request, however often the engine runs out of budget.
AC5  A prime that runs out of budget leaves nothing half loaded, so the rows an engine on its own
     budget shares are always whole.

The fifth item, the credit-note tax backfill, is a decision and not a change: see the plan.
"""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from app.features.costing import engine as engine_module
from tests.costing_helpers import complete, lot, price, workflow
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export
from tests.test_costing_allocations import world as rules_world  # noqa: F401 -- fixture re-export
from tests.test_costing_margins import world as margins_world  # noqa: F401 -- fixture re-export
from tests.test_costing_price_history import world as history_world  # noqa: F401 -- fixture re-export
from tests.test_costing_readiness import world as readiness_world  # noqa: F401 -- fixture re-export

API = "/api/core/costing"


def _make_product(db, org, client, name, materials):
    """One finished product made from the given (lot, quantity, unit) materials, in its own process."""
    execution, (step,) = workflow(db, org.id, [[{"name": name, "unit": "bottles"}]])
    complete(client, execution, step, list(materials), [{"name": name, "quantity": 1, "unit": "bottles"}])
    return execution


SHAPES = {
    "Alpha": ["Base spirit", "Angelica"],
    "Bravo": ["Base spirit", "Juniper"],
    "Charlie": ["Base spirit", "Coriander"],  # Charlie and Delta share a material no earlier product used
    "Delta": ["Base spirit", "Coriander"],
    "Echo": ["Base spirit", "Orris"],
}


def _readiness_catalogue(db, org, client, shapes=SHAPES):
    """Products named by ``shapes`` ({name: [material names]}), every material priced and shared by name."""
    lots: dict = {}
    for names in shapes.values():
        for material in names:
            if material not in lots:
                lots[material] = lot(db, org.id, material, 10, "kg")
                price(db, org.id, lots[material].id, 100, 10)
    for name, names in shapes.items():
        _make_product(db, org, client, name, [(lots[m], 1, "kg") for m in names])
    return lots


@contextmanager
def _statements_touching(db, table):
    """The SQL statements run against ``table`` while the block runs (the app's and the test's alike)."""
    seen: list[str] = []
    engine = getattr(db.get_bind(), "engine", db.get_bind())

    def listener(_conn, _cursor, statement, *_rest):
        if table in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", listener)


# --- AC1 / AC2: readiness after an engine overflow ------------------------------------------------


@pytest.mark.parametrize("max_nodes", [2, 3, 4])
def test_ac1_after_an_overflow_each_product_reads_as_its_own_page_does(readiness_world, db, monkeypatch, max_nodes):  # noqa: F811
    org, client = readiness_world
    _readiness_catalogue(db, org, client)
    monkeypatch.setattr(engine_module, "MAX_NODES", max_nodes)

    listed = [p for p in client.get(f"{API}/readiness").get_json()["products"] if p["name"] in SHAPES]
    assert len(listed) == len(SHAPES)
    own = {p["key"]: client.get(f"{API}/readiness/{p['key']}").get_json()["ready"] for p in listed}
    assert set(own.values()) == {True}, "each product alone fits the budget, so each page reads ready"
    assert {p["key"]: p["ready"] for p in listed} == own


def test_ac2_a_material_that_ran_out_of_budget_is_not_kept_for_the_next_product(readiness_world, db, monkeypatch):  # noqa: F811
    from app.features.costing import readiness

    org, client = readiness_world
    _readiness_catalogue(db, org, client)
    kept: list[dict] = []
    real = readiness._lot_rows

    def watching(lot_ids, engine, cache=None, **kwargs):
        try:
            return real(lot_ids, engine, cache, **kwargs)
        finally:
            if cache is not None:
                kept.append(dict(cache))

    monkeypatch.setattr(readiness, "_lot_rows", watching)
    monkeypatch.setattr(engine_module, "MAX_NODES", 3)
    client.get(f"{API}/readiness")
    assert any(snapshot for snapshot in kept), "the cache is used until the budget runs out"
    for snapshot in kept:
        for row in snapshot.values():
            assert row["status"] != "unknown", f"a row that ran out of budget was kept for the next product: {row}"


# --- AC3: "Remember this" keeps the typed payee ---------------------------------------------------


def _remember(client, line_id):
    return client.post(f"{API}/purchases/{line_id}/remember", headers={"Idempotency-Key": str(uuid4())})


def test_ac3_remember_on_an_existing_rule_keeps_the_payee_as_typed(flask_app, rules_world, db):  # noqa: F811
    from tests.costing_helpers import user_client
    from tests.test_costing_allocations import _assert_success, _record, _row
    from tests.test_costing_rules import _purchase, _rule

    client = user_client(db, flask_app, rules_world["org"])
    made = _rule(client, payee_pattern="Moore Wilson's Wellington", account_code="310", treatment="stock")
    assert made.status_code == 201, made.get_json()
    line_id = _purchase(rules_world, db, "60", payee="MOORE WILSON'S WELLINGTON")
    _assert_success(_record(client, line_id, [_row("Orris root", 1, 60)]))

    remembered = _remember(client, line_id)
    assert remembered.status_code == 201, remembered.get_json()
    assert remembered.get_json()["id"] == made.get_json()["id"], "the same rule, updated"
    assert remembered.get_json()["payee_pattern"] == "Moore Wilson's Wellington"
    (listed,) = client.get(f"{API}/rules").get_json()["rules"]
    assert listed["payee_pattern"] == "Moore Wilson's Wellington" and listed["template"] is not None


def test_ac3_an_upsert_keeps_both_typed_forms_and_gives_a_legacy_rule_the_new_casing(rules_world, db):  # noqa: F811
    from app.features.costing import rules
    from app.features.costing.models import PurchaseRule

    org_id = rules_world["org"].id
    typed = {
        "payee_pattern": "Moore Wilson's Wellington",
        "description_pattern": "Juniper BERRIES",
        "match_type": "exact",
        "treatment": "not_stock",
    }
    first = rules.create(db, org_id, typed)
    again = rules.upsert_by_matchers(
        db,
        org_id,
        {**typed, "payee_pattern": "MOORE WILSON'S  WELLINGTON", "description_pattern": "juniper berries"},
    )
    assert again.id == first.id
    assert (again.payee_display, again.description_display) == ("Moore Wilson's Wellington", "Juniper BERRIES")
    assert (again.payee_pattern, again.description_pattern) == ("moore wilson's wellington", "juniper berries")

    legacy = db.get(PurchaseRule, UUID(str(first.id)))
    legacy.payee_display = legacy.description_display = None  # as every rule saved before the typed form
    db.flush()
    updated = rules.upsert_by_matchers(
        db, org_id, {**typed, "payee_pattern": "Moore Wilson's WELLINGTON", "description_pattern": "Juniper Berries"}
    )
    assert (updated.payee_display, updated.description_display) == ("Moore Wilson's WELLINGTON", "Juniper Berries")


# --- AC4: costing settings are read once per request -----------------------------------------------


def test_ac4_readiness_reads_costing_settings_once_however_often_it_overflows(readiness_world, db, monkeypatch):  # noqa: F811
    org, client = readiness_world
    _readiness_catalogue(db, org, client)
    monkeypatch.setattr(engine_module, "MAX_NODES", 3)
    with _statements_touching(db, "costing_settings") as reads:
        assert client.get(f"{API}/readiness").status_code == 200
    assert len(reads) == 1, f"settings read {len(reads)} times: {reads}"


def test_ac4_a_materials_history_reads_costing_settings_once_after_an_overflow(history_world, db, monkeypatch):  # noqa: F811
    org, client = history_world["org"], history_world["client"]
    spirit = lot(db, org.id, "Base spirit", 100, "L")
    price(db, org.id, spirit.id, 1000, 100)
    for _ in range(4):
        execution, (step,) = workflow(db, org.id, [[{"name": "Node Gin", "unit": "bottles"}]])
        complete(client, execution, step, [(spirit, 1, "L")], [{"name": "Node Gin", "quantity": 1, "unit": "bottles"}])
    db.expire_all()
    monkeypatch.setattr(engine_module, "MAX_NODES", 4)  # one lot fits; four together don't
    with _statements_touching(db, "costing_settings") as reads:
        body = client.get(f"{API}/materials/Node Gin/history").get_json()
    assert {row["status"] for row in body["lots"]} == {"actual"}, "each lot still reads as its own page does"
    assert len(reads) == 1, f"settings read {len(reads)} times: {reads}"


def test_ac4_the_materials_picker_reads_costing_settings_once_when_nothing_fits(history_world, db, monkeypatch):  # noqa: F811
    org, client = history_world["org"], history_world["client"]
    for name in ("Juniper", "Coriander", "Orris", "Angelica"):
        item = lot(db, org.id, name, 2, "kg")
        price(db, org.id, item.id, 10, 2)
    db.commit()
    monkeypatch.setattr(engine_module, "MAX_WORK", 0)
    with _statements_touching(db, "costing_settings") as reads:
        response = client.get(f"{API}/materials")
    assert response.status_code == 200
    assert {m["name"] for m in response.get_json()["materials"]} >= {"Juniper", "Coriander", "Orris", "Angelica"}
    assert len(reads) == 1, f"settings read {len(reads)} times: {reads}"


def test_ac4_a_margins_report_adds_no_settings_read_when_its_lineage_is_too_big(margins_world, db, monkeypatch):  # noqa: F811
    """The report reads the costing settings for its base currency, and its engine reads them once;
    running out of budget must add nothing to that."""
    from tests.test_costing_margins import API as MARGINS_API
    from tests.test_costing_margins import GIN

    world = margins_world
    batch = world["lot"]("B1", unit_cost="4")
    inv = world["sell"]([("Wildflower Gin 700ml", 2, "80", "0")])
    world["allocate"](inv, "l1", batch, 2)
    url = f"{MARGINS_API}?from=2026-10&to=2026-10"
    with _statements_touching(db, "costing_settings") as normal:
        assert world["client"].get(url).status_code == 200
    monkeypatch.setattr(engine_module, "MAX_WORK", 0)
    with _statements_touching(db, "costing_settings") as overflowed:
        response = world["client"].get(url)
    assert response.status_code == 200, response.get_json()
    assert [r for r in response.get_json()["rows"] if r["product"] == GIN]
    assert normal, "the report reads the costing settings (its base currency, and the engine's)"
    assert len(overflowed) == len(normal), f"settings read {len(overflowed)} times: {overflowed}"


def test_ac4_an_engine_on_its_own_budget_copies_what_the_first_one_read(readiness_world, db):  # noqa: F811
    org, _client = readiness_world
    first = engine_module.CostEngine(db, org.id)
    with _statements_touching(db, "costing_settings") as reads:
        second = first.own_budget()
        bare = first.own_budget(reuse_loaded=False)
    assert reads == []
    for engine in (second, bare):
        assert (engine.use_last_known_price, engine.split_basis) == (first.use_last_known_price, first.split_basis)
        assert engine is not first and engine._memo is not first._memo and engine._charged is not first._charged
    assert second._lots is first._lots, "loaded rows are shared, never queried twice"
    assert bare._lots is not first._lots, "a bare engine starts with nothing loaded"


# --- AC5: a prime that runs out of budget leaves nothing half loaded --------------------------------


def test_ac5_a_prime_that_runs_out_of_budget_leaves_nothing_half_loaded(readiness_world, db, monkeypatch):  # noqa: F811
    org, _client = readiness_world
    juniper = lot(db, org.id, "Juniper", 2, "kg")
    price(db, org.id, juniper.id, 10, 2)
    db.commit()
    engine = engine_module.CostEngine(db, org.id)
    monkeypatch.setattr(engine_module, "MAX_WORK", 0)
    with pytest.raises(engine_module.TooLargeError):
        engine.prime([juniper.id])
    assert juniper.id not in engine._in_flow_cache, "not marked as loaded with its flows left out"
    assert juniper.id not in engine._entry_cache

    monkeypatch.setattr(engine_module, "MAX_WORK", 200_000)
    shared = engine.own_budget()  # shares what the failed prime left behind, by reference
    assert shared._solve(("lot", juniper.id)).status == "actual", "the priced lot still costs as itself"
