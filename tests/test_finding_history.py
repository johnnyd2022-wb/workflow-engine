"""Unit tests for scripts/finding_history.py — the historical-findings store.

The store's value is entirely in its decisions being trustworthy: if `decide` returned
`suppress` for something a human never rejected, the skill would silently bury a real
finding; if the signature were fragile, a bug that came back would read as brand new and
the regression signal would be lost. These pin the signature's stability, the
last-verdict-wins rule, and every branch of `decide`.

DB-free: HISTORY_DIR points at a tmp dir; no Postgres, no real store touched.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "finding_history", Path(__file__).resolve().parents[1] / "scripts" / "finding_history.py"
)
fh = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fh
_SPEC.loader.exec_module(fh)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("HISTORY_DIR", str(tmp_path))
    return tmp_path


# --- signature stability ---------------------------------------------------------------


def test_signature_ignores_literals_whitespace_and_case():
    a = fh.signature("app/x", "sql-injection", 'execute(f"where id = 42")')
    b = fh.signature("app/x", "SQL-Injection", 'execute(f"where  id = 9999")')
    assert a == b


def test_signature_distinguishes_different_areas():
    a = fh.signature("app/a", "k", "same evidence")
    b = fh.signature("app/b", "k", "same evidence")
    assert a != b


def test_signature_distinguishes_variable_rename_as_real_change():
    # renaming the offending identifier IS a code change — re-review is correct
    a = fh.signature("app/x", "k", "q.get(uid)")
    b = fh.signature("app/x", "k", "q.get(other)")
    assert a != b


# --- decide branches -------------------------------------------------------------------


def test_decide_new_when_no_history(store):
    assert fh.decide("app/x", "k", "evidence", fh._read())["action"] == "new"


def test_decide_suppress_after_false_positive(store):
    fh.record(area="app/x", kind="k", evidence="ev", verdict="false-positive")
    assert fh.decide("app/x", "k", "ev", fh._read())["action"] == "suppress"


def test_decide_suppress_after_accepted_risk(store):
    fh.record(area="app/x", kind="k", evidence="ev", verdict="accepted-risk")
    assert fh.decide("app/x", "k", "ev", fh._read())["action"] == "suppress"


def test_decide_recurring_after_fixed(store):
    fh.record(area="app/x", kind="k", evidence="ev", verdict="fixed")
    d = fh.decide("app/x", "k", "ev", fh._read())
    assert d["action"] == "recurring"
    assert d["last_verdict"] == "fixed"


def test_decide_known_confirmed(store):
    fh.record(area="app/x", kind="k", evidence="ev", verdict="confirmed")
    assert fh.decide("app/x", "k", "ev", fh._read())["action"] == "known-confirmed"


def test_last_verdict_wins_over_earlier(store):
    # rejected, then a re-review confirmed it: the store must not still say suppress
    fh.record(area="app/x", kind="k", evidence="ev", verdict="false-positive")
    fh.record(area="app/x", kind="k", evidence="ev", verdict="confirmed")
    assert fh.decide("app/x", "k", "ev", fh._read())["action"] == "known-confirmed"


# --- validation ------------------------------------------------------------------------


def test_record_rejects_unknown_verdict(store):
    with pytest.raises(ValueError, match="verdict"):
        fh.record(area="app/x", kind="k", evidence="ev", verdict="meh")


def test_check_flags_bad_verdict(store):
    (store / "findings.jsonl").write_text('{"sig": "x", "area": "a", "verdict": "vibes"}\n', encoding="utf-8")
    problems = fh.check()
    assert any("bad verdict" in p for p in problems)


def test_date_backfill(store):
    rec = fh.record(area="app/x", kind="k", evidence="ev", verdict="confirmed", ts=fh._date_to_ts("2026-07-17"))
    assert rec["ts"].startswith("2026-07-17T00:00:00")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        fh._date_to_ts("nope")
