"""Unit tests for scripts/rule_candidates.py — the learning-loop verifier's decision logic.

The verifier's whole value is that it fails when a finding-born rule doesn't actually catch
its bug. If `evaluate` returned ok for a rule that never fired, the gate would be
decorative — green while catching nothing. These pin both failure directions
(under-matching and over-matching) plus the parser that feeds it. semgrep is not invoked
here: `evaluate` is pure over a findings map, so this stays DB- and binary-free.
"""

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "rule_candidates", Path(__file__).resolve().parents[1] / "scripts" / "rule_candidates.py"
)
rc = importlib.util.module_from_spec(_SPEC)
# register before exec: the module defines @dataclass with field(default_factory=...),
# whose resolution reads sys.modules[__module__] at class-creation time.
sys.modules[_SPEC.name] = rc
_SPEC.loader.exec_module(rc)


def _rule():
    return rc.Rule(rule_id="r1", fixture="r1")


def test_evaluate_passes_when_fires_on_vuln_and_silent_on_fixed(tmp_path):
    vuln = tmp_path / "vulnerable.py"
    fixed = tmp_path / "fixed.py"
    findings = {vuln.resolve(): {"r1"}, fixed.resolve(): set()}
    res = rc.evaluate(_rule(), vuln, fixed, findings)
    assert res.ok
    assert res.reasons == []


def test_evaluate_fails_when_rule_does_not_fire_on_vulnerable(tmp_path):
    vuln = tmp_path / "vulnerable.py"
    fixed = tmp_path / "fixed.py"
    # rule fired on nothing — it doesn't catch the bug it was born from
    res = rc.evaluate(_rule(), vuln, fixed, {})
    assert not res.ok
    assert any("did NOT fire on vulnerable" in r for r in res.reasons)


def test_evaluate_fails_when_rule_over_matches_fixed(tmp_path):
    vuln = tmp_path / "vulnerable.py"
    fixed = tmp_path / "fixed.py"
    findings = {vuln.resolve(): {"r1"}, fixed.resolve(): {"r1"}}
    res = rc.evaluate(_rule(), vuln, fixed, findings)
    assert not res.ok
    assert any("fired on fixed" in r for r in res.reasons)


def test_evaluate_fails_on_missing_fixtures():
    res = rc.evaluate(_rule(), None, None, {})
    assert not res.ok
    assert any("vulnerable" in r for r in res.reasons)
    assert any("fixed" in r for r in res.reasons)


def test_parse_learned_rules_extracts_id_and_provenance():
    text = """rules:
  - id: bize-example
    languages: [python]
    severity: ERROR
    message: something
    metadata:
      born-from: security-audit
      date: "2026-07-19"
      fixture: bize-example
    patterns:
      - pattern: foo(...)
  - id: bize-second
    languages: [python]
    metadata:
      born-from: perf-guardrails
      date: "2026-07-20"
    patterns:
      - pattern: bar(...)
"""
    rules = rc.parse_learned_rules(text)
    assert [r.rule_id for r in rules] == ["bize-example", "bize-second"]
    assert rules[0].fixture == "bize-example"
    assert rules[0].born_from == "security-audit"
    # fixture defaults to the rule id when the metadata omits it
    assert rules[1].fixture == "bize-second"
    assert rules[1].born_from == "perf-guardrails"


def test_parse_empty_is_no_rules():
    assert rc.parse_learned_rules("rules:\n") == []
