"""Unit tests for scripts/skill_metrics.py — the evaluation-layer ledger and scorecard.

The scorecard is only worth acting on if its arithmetic is honest: an acceptance rate that
counts escaped defects in the denominator, or that lets a rejected MR score as accepted,
would tell us to keep a skill we should retire. These pin the join, the acceptance-rate
formula, the last-write-wins outcome rule, and that malformed ledgers are caught, not
silently averaged over.

DB-free by construction: METRICS_DIR is pointed at a tmp dir, so nothing here touches
Postgres or the real .agents/metrics/ ledger.
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "skill_metrics", Path(__file__).resolve().parents[1] / "scripts" / "skill_metrics.py"
)
skill_metrics = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(skill_metrics)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point the tool at an isolated tmp metrics dir for this test only."""
    monkeypatch.setenv("METRICS_DIR", str(tmp_path))
    return tmp_path


def _score(mod):
    return mod.scorecard(mod._read(mod.runs_path()), mod._read(mod.outcomes_path()))


def test_acceptance_rate_merged_over_merged_plus_closed(ledger):
    # two merged, one closed -> 2/3
    skill_metrics.record_run(skill="security-audit", run_type="chained", verdict="patched", ref="a")
    skill_metrics.record_run(skill="security-audit", run_type="chained", verdict="patched", ref="b")
    skill_metrics.record_run(skill="security-audit", run_type="chained", verdict="patched", ref="c")
    skill_metrics.record_outcome(ref="a", outcome="merged")
    skill_metrics.record_outcome(ref="b", outcome="merged")
    skill_metrics.record_outcome(ref="c", outcome="closed")

    card = _score(skill_metrics)["security-audit"]
    assert card["runs"] == 3
    assert card["acceptance_rate"] == round(2 / 3, 3)


def test_amended_counts_as_accepted_but_tracked_apart(ledger):
    skill_metrics.record_run(skill="perf-guardrails", run_type="scheduled", verdict="patched", ref="x")
    skill_metrics.record_outcome(ref="x", outcome="amended")
    card = _score(skill_metrics)["perf-guardrails"]
    assert card["amended"] == 1
    assert card["acceptance_rate"] == 1.0  # amended shipped, so it's in the numerator


def test_escaped_defect_never_enters_acceptance_denominator(ledger):
    # one merged (accepted), plus an escaped defect that must NOT dilute acceptance
    skill_metrics.record_run(skill="security-audit", run_type="chained", verdict="clean", ref="m")
    skill_metrics.record_run(skill="security-audit", run_type="chained", verdict="clean", ref="e")
    skill_metrics.record_outcome(ref="m", outcome="merged")
    skill_metrics.record_outcome(ref="e", outcome="escaped")
    card = _score(skill_metrics)["security-audit"]
    assert card["acceptance_rate"] == 1.0  # 1 merged / 1 (escaped excluded)
    assert card["escaped"] == 1


def test_last_written_outcome_wins(ledger):
    # closed, then merged -> the reopen-and-merge is authoritative
    skill_metrics.record_run(skill="fix-bug", run_type="interactive", verdict="patched", ref="r")
    skill_metrics.record_outcome(ref="r", outcome="closed")
    skill_metrics.record_outcome(ref="r", outcome="merged")
    card = _score(skill_metrics)["fix-bug"]
    assert card["merged"] == 1
    assert card["closed"] == 0
    assert card["acceptance_rate"] == 1.0


def test_unresolved_runs_have_no_acceptance_rate(ledger):
    # a run with findings but no outcome yet contributes volume, not an acceptance number
    skill_metrics.record_run(skill="review-feature", run_type="chained", verdict="findings-open", findings=4, ref="q")
    card = _score(skill_metrics)["review-feature"]
    assert card["findings_total"] == 4
    assert card["acceptance_rate"] is None


def test_findings_per_run_average(ledger):
    skill_metrics.record_run(skill="security-audit", run_type="chained", verdict="patched", findings=3, ref="a")
    skill_metrics.record_run(skill="security-audit", run_type="chained", verdict="clean", findings=0, ref="b")
    card = _score(skill_metrics)["security-audit"]
    assert card["findings_per_run"] == 1.5


def test_record_rejects_unknown_verdict(ledger):
    with pytest.raises(ValueError, match="verdict"):
        skill_metrics.record_run(skill="x", run_type="chained", verdict="totally-fine")


def test_record_rejects_unknown_run_type(ledger):
    with pytest.raises(ValueError, match="run-type"):
        skill_metrics.record_run(skill="x", run_type="whenever", verdict="clean")


def test_check_flags_malformed_jsonl(ledger):
    (ledger / "runs.jsonl").write_text('{"skill": "x", "run_type": "chained"\n', encoding="utf-8")
    problems = skill_metrics.check(skill_metrics.runs_path(), skill_metrics.outcomes_path())
    assert problems
    assert "not valid JSON" in problems[0]


def test_check_flags_bad_enum(ledger):
    skill_metrics.record_run(skill="x", run_type="chained", verdict="clean", ref="a")
    # hand-write a bad outcome to simulate a corrupted append
    (ledger / "outcomes.jsonl").write_text('{"ref": "a", "outcome": "vibes"}\n', encoding="utf-8")
    problems = skill_metrics.check(skill_metrics.runs_path(), skill_metrics.outcomes_path())
    assert any("bad outcome" in p for p in problems)


def test_empty_ledger_scores_empty(ledger):
    assert _score(skill_metrics) == {}
    assert "empty" in skill_metrics.render_scorecard({})


def test_date_backfill_sets_ts():
    assert skill_metrics._date_to_ts("2026-07-18").startswith("2026-07-18T00:00:00")
    assert skill_metrics._date_to_ts(None) is None


def test_date_backfill_rejects_bad_format():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="YYYY-MM-DD"):
        skill_metrics._date_to_ts("18-07-2026")
