"""Market indicator input remains comparable and survives a metrics DB outage."""

import json
import sys
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
    spool = tmp_path / "spool.jsonl"
    monkeypatch.setenv("BIZE_METRICS_SPOOL", str(spool))
    monkeypatch.delenv("BIZE_METRICS_PASSWORD", raising=False)
    monkeypatch.delenv("KEEPASS_PASSWORD", raising=False)
    rows = market_metrics.parse_batch(batch())
    assert rows[0]["upper_bound"] == "1500000"
    assert market_metrics.metrics_db.store("indicator", rows[0]) == "spooled"
    saved = json.loads(spool.read_text(encoding="utf-8"))
    assert saved["kind"] == "indicator"
    assert saved["record"]["metric_key"] == "sam_nzd_annual"
    assert saved["record"]["threshold_value"] == "1400000"
    assert saved["record"]["refresh_cadence"] == "monthly"


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
