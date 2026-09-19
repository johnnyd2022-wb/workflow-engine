"""The prior inventory database is committed as JSON, so the replay needs nothing else running."""

from __future__ import annotations

import copy
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_legacy as legacy  # noqa: E402
import whistlebird_migration as wm  # noqa: E402
from whistlebird_replay_timeline import build_timeline  # noqa: E402

PRODUCTION_MANIFEST = Path(__file__).parents[1] / "docs" / "whistlebird-production-sheet-source.json"


def _raw() -> dict:
    return json.loads(legacy.DEFAULT_LEGACY_SNAPSHOT.read_text(encoding="utf-8"))


def _synthetic() -> dict:
    """A tiny but valid snapshot: one row per table, exercising every value type."""
    tables = {}
    for name, spec in legacy.LEGACY_TABLES.items():
        row = []
        for column in spec.columns:
            if column == "id":
                row.append(1)
            elif column in spec.date_columns:
                row.append("2024-05-06")
            elif column in {"supplier", "ingredients", "notes", "flavor_code"}:
                row.append("Crème brûlée")
            else:
                row.append(2.0)
        tables[name] = {"columns": list(spec.columns), "rows": [row]}
    return {"version": legacy.SNAPSHOT_VERSION, "exported_on": "2026-09-19", "tables": tables}


# --- the committed file -------------------------------------------------------------


def test_committed_snapshot_covers_every_registry_table_with_data():
    snapshot = legacy.load_snapshot()

    for name in legacy.LEGACY_TABLES:
        assert snapshot.rows(name), f"{name} is empty in the committed snapshot"
    assert {row["ingredients"] for row in snapshot.rows("purchases_ingredients")} >= {"coriander seeds"}


def test_committed_snapshot_preserves_recorded_expiry_dates_as_dates():
    rows = {row["id"]: row for row in legacy.load_snapshot().rows("purchases_ingredients")}

    assert rows[9]["ingredients_expiry"] == date(2024, 6, 1), "butterfly pea flowers"
    assert rows[53]["ingredients_expiry"] == date(2026, 9, 19), "coriander COR004"


def test_the_replay_timeline_builds_from_the_repository_alone_with_no_database():
    """The point of the snapshot: clone the repo, build the whole replay, touch no legacy DB."""
    events = build_timeline(legacy.DEFAULT_LEGACY_SNAPSHOT, PRODUCTION_MANIFEST)

    ids = [event.event_id for event in events]
    assert len(ids) == len(set(ids)) > 600
    known = set(ids)
    assert not [(e.event_id, d) for e in events for d in e.depends_on if d not in known], "unresolved dependency"
    assert any(event_id.startswith("green-gold-step:") for event_id in ids), "manifest-sourced events are present"
    assert any(event_id.startswith("purchase:legacy-") or event_id.startswith("purchase:") for event_id in ids)
    assert any(event_id.startswith("trial-exec:") for event_id in ids), "legacy-sourced trials are present"
    assert any(event_id.startswith("customs:") for event_id in ids), "legacy-sourced customs lodgements are present"


def test_loaders_read_the_snapshot_exactly_as_they_read_the_database():
    snapshot = legacy.load_snapshot()

    raw_rows = sum(
        len(snapshot.rows(t))
        for t in (
            "purchases_gns",
            "purchases_empty_bottles",
            "purchases_ingredients",
            "product_actions_create_premix",
        )
    )
    assert len(list(wm._raw_material_records(snapshot))) == raw_rows
    assert len(wm._customs_lodgement_rows(snapshot)) == len(snapshot.rows("customs_lodgements"))
    assert len(wm._legacy_batches(snapshot)) == len(snapshot.rows("product_actions_flavor_vat"))


# --- parsing --------------------------------------------------------------------------


def _mutated(mutate) -> dict:
    data = copy.deepcopy(_synthetic())
    mutate(data)
    return data


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(version=99), "unsupported snapshot version"),
        (lambda d: d["tables"].pop("purchases_gns"), "missing"),
        (lambda d: d["tables"].update(surprise={"columns": [], "rows": []}), "unknown"),
        (lambda d: d["tables"]["purchases_gns"]["columns"].reverse(), "do not match the registry"),
        (lambda d: d["tables"]["purchases_gns"]["rows"][0].pop(), "expected a row of"),
        (lambda d: d["tables"]["purchases_gns"]["rows"][0].__setitem__(1, "not-a-date"), "not an ISO date"),
        (lambda d: d["tables"]["purchases_gns"]["rows"][0].__setitem__(1, 20240506), "ISO date string"),
        (
            lambda d: d["tables"]["purchases_gns"]["rows"].append(list(d["tables"]["purchases_gns"]["rows"][0])),
            "duplicate id",
        ),
        (lambda d: d.pop("tables"), "'tables' object"),
    ],
)
def test_a_malformed_snapshot_is_rejected(mutate, message):
    with pytest.raises(legacy.LegacySnapshotError, match=message):
        legacy.parse_snapshot(_mutated(mutate))


def test_parsing_restores_dates_and_keeps_int_and_float_distinct():
    data = _synthetic()
    data["tables"]["purchases_ingredients"]["rows"][0][4] = 500  # ingredients_amount is an int4
    data["tables"]["purchases_ingredients"]["rows"][0][6] = None  # a missing expiry

    row = legacy.parse_snapshot(data).rows("purchases_ingredients")[0]

    assert row["date"] == date(2024, 5, 6)
    assert row["ingredients_expiry"] is None
    assert type(row["ingredients_amount"]) is int
    assert type(row["id"]) is int
    assert row["supplier"] == "Crème brûlée"


def test_snapshot_rows_are_copies_so_a_loader_cannot_corrupt_the_source():
    snapshot = legacy.parse_snapshot(_synthetic())

    snapshot.rows("purchases_gns")[0]["supplier"] = "mutated"

    assert snapshot.rows("purchases_gns")[0]["supplier"] != "mutated"


# --- writing --------------------------------------------------------------------------


def test_render_then_parse_round_trips_exactly_including_types():
    data = _synthetic()
    data["tables"]["purchases_gns"]["rows"][0][3] = 0.1  # a float that is not exactly representable

    reparsed = json.loads(legacy.render(data))

    assert reparsed["tables"] == data["tables"]
    assert legacy.parse_snapshot(reparsed).rows("purchases_gns") == legacy.parse_snapshot(data).rows("purchases_gns")


def test_render_puts_one_row_per_line_so_git_diffs_show_which_rows_changed():
    text = legacy.render(_synthetic())

    assert '["id", "date", "supplier", "gns_purchased_l", "abv"]' in text
    assert '[1, "2024-05-06", "Crème brûlée", 2.0, 2.0]' in text


def test_committed_file_is_exactly_what_the_renderer_produces():
    """A hand edit, or a stale format, shows up as a difference here."""
    committed = legacy.DEFAULT_LEGACY_SNAPSHOT.read_text(encoding="utf-8")

    assert legacy.render(json.loads(committed)) == committed


@pytest.mark.parametrize(
    "value", [Decimal("1.5"), float("nan"), float("inf"), object()], ids=["decimal", "nan", "inf", "object"]
)
def test_export_refuses_a_value_type_it_cannot_store_exactly(value):
    with pytest.raises(legacy.LegacySnapshotError):
        legacy._encode(value, "table.column")


def test_dates_are_encoded_as_iso_strings():
    assert legacy._encode(date(2026, 9, 19), "t.c") == "2026-09-19"


# --- sources --------------------------------------------------------------------------


def test_a_path_opens_the_snapshot_and_a_snapshot_passes_through(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(_synthetic()), encoding="utf-8")

    with legacy.open_legacy(path) as from_path:
        assert isinstance(from_path, legacy.LegacySnapshot)
    with legacy.open_legacy(str(path)) as from_text:
        assert isinstance(from_text, legacy.LegacySnapshot)
    ready = legacy.parse_snapshot(_synthetic())
    with legacy.open_legacy(ready) as passed:
        assert passed is ready


def test_a_url_opens_a_live_connection_and_disposes_the_engine(monkeypatch):
    events = []

    class _Connection:
        def __enter__(self):
            events.append("connect")
            return "connection"

        def __exit__(self, *_exc):
            events.append("close")

    class _Engine:
        def connect(self):
            return _Connection()

        def dispose(self):
            events.append("dispose")

    monkeypatch.setattr(legacy, "create_engine", lambda url: (events.append(f"engine:{url}"), _Engine())[1])

    with legacy.open_legacy("postgresql://user@host/db") as source:
        assert source == "connection"

    assert events == ["engine:postgresql://user@host/db", "connect", "close", "dispose"]


def test_a_missing_snapshot_file_is_a_clear_error(tmp_path):
    with pytest.raises(legacy.LegacySnapshotError, match="cannot read legacy snapshot"):
        legacy.load_snapshot(tmp_path / "absent.json")


def test_live_reads_select_only_the_registry_columns_in_the_registry_order():
    statements = []

    class _Result:
        def mappings(self):
            return []

    class _Connection:
        def execute(self, statement):
            statements.append(str(statement))
            return _Result()

    legacy.legacy_rows(_Connection(), "product_actions_bottling")
    legacy.legacy_rows(_Connection(), "purchases_gns")

    assert statements[0] == (
        "SELECT id, date, bottles_stored, abv, bottle_size_ml, vat_batch, bottle_batch "
        "FROM product_actions_bottling ORDER BY date, id"
    )
    assert statements[1] == "SELECT id, date, supplier, gns_purchased_l, abv FROM purchases_gns ORDER BY id"


# --- drift check ----------------------------------------------------------------------


def _drift(monkeypatch, mutate) -> list[str]:
    """Report the differences between a mutated 'live database' and the committed snapshot."""
    live = _raw()
    mutate(live)
    live_source = legacy.parse_snapshot(live)

    class _Open:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return live_source

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(legacy, "open_legacy", _Open)
    return legacy.diff_against("postgresql://live/db")


def test_drift_check_is_silent_when_the_database_matches(monkeypatch):
    assert _drift(monkeypatch, lambda d: None) == []


def test_drift_check_reports_a_new_removed_and_changed_row(monkeypatch):
    def mutate(d):
        rows = d["tables"]["purchases_gns"]["rows"]
        added = list(rows[0])
        added[0] = 9999
        rows.append(added)
        rows.pop(0)
        d["tables"]["purchases_gns"]["rows"][1][2] = "A different supplier"

    problems = _drift(monkeypatch, mutate)

    assert any("purchases_gns#9999: in the database, not in the snapshot" in p for p in problems)
    assert any("purchases_gns#1: in the snapshot, no longer in the database" in p for p in problems)
    assert any("differs in ['supplier']" in p for p in problems)


def test_drift_check_treats_an_int_that_became_a_float_as_a_change(monkeypatch):
    """`2 == 2.0`, but the loaders format values with str(), so the replayed text would change."""

    def mutate(d):
        rows = d["tables"]["purchases_ingredients"]["rows"]
        assert type(rows[0][4]) is int
        rows[0][4] = float(rows[0][4])

    problems = _drift(monkeypatch, mutate)

    assert any("purchases_ingredients#" in p and "ingredients_amount" in p for p in problems)
