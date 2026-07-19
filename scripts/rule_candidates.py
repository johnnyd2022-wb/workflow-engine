#!/usr/bin/env python3
"""Learning loop: prove that every finding-born semgrep rule actually catches its bug.

security-audit §3 already says the right thing — when you find a vulnerability class by
reading code, write a semgrep rule so the next occurrence is caught by machine, and
"confirm the rule fires on the pre-patch code and stays silent after the fix." But nothing
enforces that last clause, so it is the first thing skipped at 3am, and an untested rule is
a false sense of security: it sits in the config looking like coverage while catching
nothing.

This script turns that manual step into a gate. Every rule in .semgrep/rules/learned.yml
must ship with a fixture pair — .semgrep/fixtures/<fixture>/vulnerable.* and fixed.* — and
this verifier proves the rule FIRES on vulnerable and stays SILENT on fixed. A rule that
fails either half is a rule that isn't doing its job, and CI says so.

That is the AER North Star made mechanical: each validated finding becomes a permanent,
*tested* deterministic check, and the need for LLM reasoning over that class drops to zero.

Usage:
    python scripts/rule_candidates.py verify        # gate: exit 1 if any rule fails
    python scripts/rule_candidates.py verify --json
    python scripts/rule_candidates.py list          # learned rules + provenance
    python scripts/rule_candidates.py scaffold --id bize-<name> [--lang python|js]

Exit codes: 0 = all learned rules proven (or none exist), 1 = a rule failed / is unproven,
2 = usage error, 3 = semgrep unavailable (cannot prove anything — reported, not silent).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = REPO_ROOT / ".semgrep" / "rules" / "learned.yml"
FIXTURES_DIR = REPO_ROOT / ".semgrep" / "fixtures"

EXT = {"python": "py", "js": "js"}


@dataclass
class Rule:
    rule_id: str
    fixture: str
    born_from: str | None = None
    date: str | None = None


@dataclass
class RuleResult:
    rule_id: str
    ok: bool
    reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Parsing. PyYAML is not a repo dependency and the other scripts stay stdlib-only, so we
# parse the narrow, self-authored shape of learned.yml by hand: top-level rule entries are
# `  - id: <id>` (two-space indent), and each rule's `fixture:`/`born-from:`/`date:` live in
# its metadata block below it. The verifier enforces the shape, so drift fails loudly here
# rather than being silently mis-parsed.
# --------------------------------------------------------------------------------------
def parse_learned_rules(text: str) -> list[Rule]:
    # split into per-rule blocks on the `  - id:` boundary
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^  - id:\s*\S", ln)]
    rules: list[Rule] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start:end]
        rule_id = re.match(r"^  - id:\s*(\S+)", block[0]).group(1)

        def field_in_block(key: str) -> str | None:
            for ln in block:
                m = re.match(rf"^\s+{re.escape(key)}:\s*(.+?)\s*$", ln)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
            return None

        rules.append(
            Rule(
                rule_id=rule_id,
                fixture=field_in_block("fixture") or rule_id,
                born_from=field_in_block("born-from"),
                date=field_in_block("date"),
            )
        )
    return rules


def resolve_fixtures(rule: Rule) -> tuple[Path | None, Path | None]:
    """Find vulnerable.* and fixed.* for a rule's fixture, whatever the language ext."""
    d = FIXTURES_DIR / rule.fixture
    if not d.is_dir():
        return None, None
    vuln = next(iter(sorted(d.glob("vulnerable.*"))), None)
    fixed = next(iter(sorted(d.glob("fixed.*"))), None)
    return vuln, fixed


# --------------------------------------------------------------------------------------
# semgrep. Degrades honestly (like scripts/perf_triage.py): no semgrep on PATH means we
# say we could not prove the rules, never that they passed.
# --------------------------------------------------------------------------------------
def run_semgrep(files: list[Path]) -> dict[Path, set[str]] | None:
    """Scan the given files with learned.yml. Returns {resolved_path: {rule_id, ...}}, or
    None if semgrep is unavailable / errored. Files are passed explicitly so semgrep scans
    them even though they live under the hidden .semgrep/ dir."""
    if shutil.which("semgrep") is None or not files:
        return None
    proc = subprocess.run(
        ["semgrep", "--config", str(RULES_FILE), "--json", "--quiet", *[str(f) for f in files]],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    findings: dict[Path, set[str]] = {}
    for res in raw.get("results", []):
        path = Path(res["path"])
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        else:
            path = path.resolve()
        rule_id = res["check_id"].split(".")[-1]  # local rules -> bare id
        findings.setdefault(path, set()).add(rule_id)
    return findings


def evaluate(rule: Rule, vuln: Path | None, fixed: Path | None, findings: dict[Path, set[str]]) -> RuleResult:
    """Pure decision: given the fixture paths and the findings map, did this rule do its
    job? Separated from semgrep so it is unit-testable without the binary."""
    reasons: list[str] = []
    if vuln is None:
        reasons.append(f"no vulnerable.* fixture under .semgrep/fixtures/{rule.fixture}/")
    if fixed is None:
        reasons.append(f"no fixed.* fixture under .semgrep/fixtures/{rule.fixture}/")
    if reasons:
        return RuleResult(rule.rule_id, ok=False, reasons=reasons)

    fired_on_vuln = rule.rule_id in findings.get(vuln.resolve(), set())
    fired_on_fixed = rule.rule_id in findings.get(fixed.resolve(), set())

    if not fired_on_vuln:
        reasons.append("did NOT fire on vulnerable.* — the rule doesn't catch the bug it was born from")
    if fired_on_fixed:
        reasons.append("fired on fixed.* — the rule over-matches and would flag correct code")
    return RuleResult(rule.rule_id, ok=not reasons, reasons=reasons)


def verify() -> dict:
    text = RULES_FILE.read_text(encoding="utf-8") if RULES_FILE.exists() else ""
    rules = parse_learned_rules(text)
    if not rules:
        return {"status": "empty", "rules": 0, "results": []}

    fixtures = {r.rule_id: resolve_fixtures(r) for r in rules}
    scan_files = [p for pair in fixtures.values() for p in pair if p is not None]
    findings = run_semgrep(scan_files)
    if findings is None:
        return {"status": "semgrep-unavailable", "rules": len(rules), "results": []}

    results = [evaluate(r, *fixtures[r.rule_id], findings) for r in rules]
    return {
        "status": "ok" if all(r.ok for r in results) else "failed",
        "rules": len(rules),
        "results": [{"rule_id": r.rule_id, "ok": r.ok, "reasons": r.reasons} for r in results],
    }


def scaffold(rule_id: str, lang: str) -> int:
    ext = EXT.get(lang)
    if ext is None:
        print(f"error: --lang must be one of {sorted(EXT)}", file=sys.stderr)
        return 2
    d = FIXTURES_DIR / rule_id
    d.mkdir(parents=True, exist_ok=True)
    vuln = d / f"vulnerable.{ext}"
    fixed = d / f"fixed.{ext}"
    for f, note in ((vuln, "FIRE on"), (fixed, "stay SILENT on")):
        if not f.exists():
            f.write_text(
                f"# Fixture: the code the rule {rule_id} must {note}.\n"
                f"# Replace this with a minimal, realistic example.\n",
                encoding="utf-8",
            )
    print(f"scaffolded fixtures under {d.relative_to(REPO_ROOT)}/")
    print("\nAdd this rule to .semgrep/rules/learned.yml, then run: rule_candidates.py verify\n")
    print(
        f"""  - id: {rule_id}
    languages: [{lang}]
    severity: ERROR
    message: >
      <what the bug is and how to fix it, in a sentence a developer can act on>
    metadata:
      born-from: <skill or human that found it>
      finding: "<the finding this rule generalises>"
      date: "<YYYY-MM-DD>"
      fixture: {rule_id}
    patterns:
      - pattern: <the vulnerable pattern>"""
    )
    return 0


def render(report: dict) -> str:
    status = report["status"]
    if status == "empty":
        return "no learned rules yet — .semgrep/rules/learned.yml is empty"
    if status == "semgrep-unavailable":
        return f"semgrep not on PATH — cannot prove {report['rules']} learned rule(s). NOT reporting them as passed."
    out = [f"learned rules: {report['rules']}"]
    for r in report["results"]:
        mark = "✓" if r["ok"] else "✗"
        out.append(f"  {mark} {r['rule_id']}")
        for reason in r["reasons"]:
            out.append(f"      - {reason}")
    out.append("")
    out.append(
        "✓ every learned rule fires on its bug and stays silent on the fix"
        if status == "ok"
        else "✗ some learned rules are unproven — see above"
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify finding-born semgrep rules against their fixtures.")
    sub = ap.add_subparsers(dest="cmd")

    v = sub.add_parser("verify", help="prove every learned rule (default)")
    v.add_argument("--json", action="store_true")

    sub.add_parser("list", help="list learned rules and their provenance")

    sc = sub.add_parser("scaffold", help="create a fixture skeleton + rule template")
    sc.add_argument("--id", required=True, dest="rule_id")
    sc.add_argument("--lang", default="python", choices=sorted(EXT))

    args = ap.parse_args(argv)
    cmd = args.cmd or "verify"

    if cmd == "scaffold":
        return scaffold(args.rule_id, args.lang)

    if cmd == "list":
        text = RULES_FILE.read_text(encoding="utf-8") if RULES_FILE.exists() else ""
        rules = parse_learned_rules(text)
        if not rules:
            print("no learned rules yet")
            return 0
        for r in rules:
            vuln, fixed = resolve_fixtures(r)
            fx = "fixtures ok" if vuln and fixed else "MISSING FIXTURES"
            print(f"  {r.rule_id}  (born-from: {r.born_from or '?'}, {r.date or '?'})  [{fx}]")
        return 0

    # verify (default)
    report = verify()
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        print(render(report))
    if report["status"] == "ok" or report["status"] == "empty":
        return 0
    if report["status"] == "semgrep-unavailable":
        return 3
    return 1


if __name__ == "__main__":
    sys.exit(main())
