"""Market indicator input remains comparable and survives a metrics DB outage."""

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import market_research_metrics as market_metrics  # noqa: E402


def batch():
    return {
        "scope_key": "craft-spirits-new-zealand",
        "report_path": ".claude/agents/outputs/market-research/craft-spirits-new-zealand/2026-11-10.md",
        "indicators": [
            {
                "metric_key": "sam_nzd_annual",
                "measured_on": "2026-11-10",
                "period_end": "2026-09-30",
                "lower_bound": 1000000,
                "upper_bound": 1500000,
                "unit": "NZD/year",
                "geography": "New Zealand",
                "source_ref": "https://example.org/statistics",
                "confidence": "medium",
                "refresh_cadence": "monthly",
                "threshold_operator": "above",
                "threshold_value": 1400000,
            }
        ],
    }


def test_valid_batch_spools_without_credentials(tmp_path, monkeypatch):
    skill_spool = tmp_path / "spool.jsonl"
    monkeypatch.setenv("BIZE_METRICS_SPOOL", str(skill_spool))
    monkeypatch.delenv("BIZE_METRICS_PASSWORD", raising=False)
    monkeypatch.delenv("KEEPASS_PASSWORD", raising=False)
    rows = market_metrics.parse_batch(batch())
    assert rows[0]["upper_bound"] == "1500000"
    assert market_metrics.metrics_db.store("indicator", rows[0]) == "spooled"
    assert not skill_spool.exists()  # older worktrees must not see the new indicator kind
    indicator_spool = market_metrics.metrics_db.indicator_spool_path()
    saved = json.loads(indicator_spool.read_text(encoding="utf-8"))
    assert saved["kind"] == "indicator"
    assert saved["record"]["metric_key"] == "sam_nzd_annual"
    assert saved["record"]["threshold_value"] == "1400000"
    assert saved["record"]["refresh_cadence"] == "monthly"


def test_indicator_spool_flushes_without_touching_skill_spool(tmp_path, monkeypatch):
    monkeypatch.setenv("BIZE_METRICS_SPOOL", str(tmp_path / "spool.jsonl"))
    row = market_metrics.parse_batch(batch())[0]
    db = market_metrics.metrics_db
    db.spool_append("indicator", row, path=db.indicator_spool_path())
    db.spool_append("run", {"skill": "existing"})
    inserted = []
    monkeypatch.setattr(db, "_insert", lambda _conn, kind, record: inserted.append((kind, record["metric_key"])))
    assert db.spool_flush(object(), path=db.indicator_spool_path()) == 1
    assert inserted == [("indicator", "sam_nzd_annual")]
    assert db.spool_read(path=db.indicator_spool_path()) == []
    assert db.spool_read()[0]["record"]["skill"] == "existing"


def test_conflicting_spooled_indicator_is_quarantined_without_blocking_later_writes(tmp_path, monkeypatch, capsys):
    from contextlib import contextmanager

    monkeypatch.setenv("BIZE_METRICS_SPOOL", str(tmp_path / "spool.jsonl"))
    db = market_metrics.metrics_db
    row = market_metrics.parse_batch(batch())[0]
    bad = {**row, "metric_key": "conflicting"}
    db.spool_append("indicator", bad, path=db.indicator_spool_path())
    db.spool_append("indicator", row, path=db.indicator_spool_path())
    inserted = []

    def insert(_conn, kind, record):
        if record["metric_key"] == "conflicting":
            raise db.IndicatorConflictError("already recorded with different value")
        inserted.append(record["metric_key"])
        return "inserted"

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(db, "_insert", insert)
    monkeypatch.setattr(db, "session", fake_session)
    assert db.spool_flush(object(), path=db.indicator_spool_path()) == 1
    rejected = db.indicator_spool_path().with_name(f"{db.indicator_spool_path().name}.rejected")
    assert json.loads(rejected.read_text(encoding="utf-8"))["record"]["metric_key"] == "conflicting"
    assert "WARNING: 1 conflicting indicator" in capsys.readouterr().err
    assert db.store("indicator", {**row, "metric_key": "later"}) == "inserted"
    assert inserted == ["sam_nzd_annual", "later"]


class _FakeCursor:
    def __init__(self):
        self.saved = None
        self.result = None
        self.insert_params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params):
        if sql.startswith("INSERT INTO market_indicators"):
            self.insert_params = params
            if self.saved is None:
                self.saved = list(params)
                columns = market_metrics.metrics_db._INDICATOR_COLS
                self.saved[columns.index("measured_on")] = date.fromisoformat(self.saved[columns.index("measured_on")])
                self.saved[columns.index("lower_bound")] = Decimal(self.saved[columns.index("lower_bound")])
                self.result = (1,)
            else:
                self.result = None
        else:
            self.result = tuple(self.saved)

    def fetchone(self):
        return self.result


class _FakeConnection:
    def __init__(self):
        self.cur = _FakeCursor()

    def cursor(self):
        return self.cur


def test_indicator_insert_distinguishes_identical_replay_from_correction():
    db = market_metrics.metrics_db
    row = market_metrics.parse_batch(batch())[0]
    conn = _FakeConnection()
    assert db._insert(conn, "indicator", row) == "inserted"
    assert len(conn.cur.insert_params) == len(db._INDICATOR_COLS)
    assert db._insert(conn, "indicator", row) == "already-present"
    changed = {**row, "upper_bound": "1600000"}
    with pytest.raises(db.IndicatorConflictError, match="upper_bound"):
        db._insert(conn, "indicator", changed)


def test_report_path_is_stable_across_worktrees_and_rejects_escape():
    data = batch()
    expected = data["report_path"]
    data["report_path"] = str(market_metrics.REPO_ROOT / expected)
    assert market_metrics.parse_batch(data)[0]["report_path"] == expected
    data["report_path"] = "../outside.md"
    with pytest.raises(ValueError, match="within this repository"):
        market_metrics.parse_batch(data)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"lower_bound": 2000000}, "lower_bound exceeds upper_bound"),
        ({"confidence": "certain"}, "confidence must be"),
        ({"threshold_operator": None}, "threshold needs"),
        ({"measured_on": "yesterday"}, "measured_on must be"),
    ],
)
def test_invalid_observations_are_rejected_before_writing(change, message):
    data = batch()
    data["indicators"][0].update(change)
    with pytest.raises(ValueError, match=message):
        market_metrics.parse_batch(data)
