#!/usr/bin/env python3
"""Skill evaluation layer: record every skill run, join outcomes, score performance.

The verification chain can tell you a run happened; it cannot tell you whether the run
was *worth it*. "Is security-audit finding real bugs or crying wolf?" and "which skill's
findings actually get merged?" are unanswerable today because nothing is written down.
This tool is the ledger that makes the AER evaluation layer real without any ML: two
append-only JSONL files and a deterministic group-by.

Two files under the metrics dir (default `.agents/metrics/`, override with $METRICS_DIR):

  runs.jsonl      one line per skill run           (who ran, what they found, verdict)
  outcomes.jsonl  one line per resolved run/MR      (merged | closed | amended | escaped)

A run and its outcome are joined on `ref` — the MR ref (`!123`) or the branch name. The
agent that opens the MR records the run; whoever later sees it merged/closed records the
outcome, possibly days later. Append-only means no run ever rewrites another's line, which
is what keeps this safe to write from unattended, concurrent skills.

Usage:
    # a skill records its own run (findings + verdict) when it finishes
    python scripts/skill_metrics.py record --skill security-audit --run-type chained \\
        --scope inventory --findings 3 --verdict patched --ref feat/inventory --duration 42

    # later, whoever observes the MR's fate records the outcome
    python scripts/skill_metrics.py outcome --ref '!123' --outcome merged

    # the scorecard: per-skill acceptance, findings volume, escaped defects, cost
    python scripts/skill_metrics.py scorecard          # human table
    python scripts/skill_metrics.py scorecard --json    # machine-readable
    python scripts/skill_metrics.py --check             # exit 1 if the ledger is malformed

Exit codes: 0 = ok, 1 = malformed ledger (--check) or bad input, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# A closed vocabulary so the scorecard can group without guessing. New values are a
# deliberate schema change, not a typo that silently creates a phantom category.
RUN_TYPES = {"chained", "scheduled", "interactive"}
VERDICTS = {"clean", "patched", "findings-open", "could-not-reproduce", "error", "skipped"}
# merged   = the fix/feature shipped                -> the finding earned its keep
# closed   = the MR was rejected without merging     -> false positive / not worth it
# amended  = merged, but a human reworked the diff    -> partially useful
# escaped  = a defect this skill should have caught reached prod (attributed after the fact)
# superseded = replaced by another run before resolution (neither credit nor blame)
OUTCOMES = {"merged", "closed", "amended", "escaped", "superseded"}


def metrics_dir() -> Path:
    """Metrics dir, overridable via $METRICS_DIR so tests point at a temp dir."""
    override = os.environ.get("METRICS_DIR")
    return Path(override) if override else REPO_ROOT / ".agents" / "metrics"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date_to_ts(date_str: str | None) -> str | None:
    """Turn a --date YYYY-MM-DD into an ISO ts (midnight UTC), for backfilling historical
    runs honestly instead of stamping them with today. None means 'use now'."""
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(f"--date must be YYYY-MM-DD, got {date_str!r}") from e
    return d.isoformat(timespec="seconds")


def _append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _read(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping blank lines. Raises ValueError with the line number
    on the first malformed record so --check points at the exact rot, not just 'bad'."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path.name}:{i}: not valid JSON ({e})") from e
        if not isinstance(rec, dict):
            raise ValueError(f"{path.name}:{i}: expected an object, got {type(rec).__name__}")
        out.append(rec)
    return out


def runs_path() -> Path:
    return metrics_dir() / "runs.jsonl"


def outcomes_path() -> Path:
    return metrics_dir() / "outcomes.jsonl"


def record_run(
    *,
    skill: str,
    run_type: str,
    verdict: str,
    scope: str | None = None,
    findings: int = 0,
    ref: str | None = None,
    duration_s: float | None = None,
    notes: str | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    if run_type not in RUN_TYPES:
        raise ValueError(f"run-type must be one of {sorted(RUN_TYPES)}, got {run_type!r}")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")
    if findings < 0:
        raise ValueError("findings cannot be negative")
    rec = {
        "ts": ts or _now(),
        "skill": skill,
        "run_type": run_type,
        "scope": scope,
        "findings": findings,
        "verdict": verdict,
        "ref": ref,
        "duration_s": duration_s,
        "notes": notes,
    }
    _append(runs_path(), rec)
    return rec


def record_outcome(
    *, ref: str, outcome: str, skill: str | None = None, notes: str | None = None, ts: str | None = None
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")
    rec = {"ts": ts or _now(), "ref": ref, "outcome": outcome, "skill": skill, "notes": notes}
    _append(outcomes_path(), rec)
    return rec


def _latest_outcome_by_ref(outcomes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The last-written outcome wins per ref: an MR closed then reopened-and-merged should
    count as merged. Order is file order (append order), so the final line is authoritative."""
    latest: dict[str, dict[str, Any]] = {}
    for rec in outcomes:
        ref = rec.get("ref")
        if ref:
            latest[ref] = rec
    return latest


def scorecard(runs: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate runs by skill, joining resolved outcomes on `ref`.

    acceptance_rate = merged / (merged + closed), counting only runs that reached a
    terminal accept/reject outcome. amended counts as merged for acceptance (it shipped)
    but is tracked separately so "shipped but reworked" stays visible. escaped and
    superseded never enter the acceptance denominator — one is post-hoc blame, the other
    is neither credit nor blame.
    """
    outcome_by_ref = _latest_outcome_by_ref(outcomes)

    per: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "runs": 0,
            "findings_total": 0,
            "verdicts": defaultdict(int),
            "merged": 0,
            "amended": 0,
            "closed": 0,
            "escaped": 0,
            "superseded": 0,
            "resolved": 0,
            "duration_total_s": 0.0,
            "duration_samples": 0,
        }
    )

    for run in runs:
        skill = run.get("skill", "<unknown>")
        s = per[skill]
        s["runs"] += 1
        s["findings_total"] += int(run.get("findings") or 0)
        s["verdicts"][run.get("verdict", "<none>")] += 1
        dur = run.get("duration_s")
        if isinstance(dur, int | float):
            s["duration_total_s"] += float(dur)
            s["duration_samples"] += 1
        ref = run.get("ref")
        oc = outcome_by_ref.get(ref) if ref else None
        if oc:
            kind = oc.get("outcome")
            if kind in ("merged", "amended", "closed", "escaped", "superseded"):
                s[kind] += 1
                if kind in ("merged", "amended", "closed"):
                    s["resolved"] += 1

    result: dict[str, Any] = {}
    for skill, s in sorted(per.items()):
        accepted = s["merged"] + s["amended"]
        denom = accepted + s["closed"]
        result[skill] = {
            "runs": s["runs"],
            "findings_total": s["findings_total"],
            "findings_per_run": round(s["findings_total"] / s["runs"], 2) if s["runs"] else 0.0,
            "verdicts": dict(s["verdicts"]),
            "merged": s["merged"],
            "amended": s["amended"],
            "closed": s["closed"],
            "escaped": s["escaped"],
            "superseded": s["superseded"],
            "resolved": s["resolved"],
            "acceptance_rate": round(accepted / denom, 3) if denom else None,
            "mean_duration_s": round(s["duration_total_s"] / s["duration_samples"], 1)
            if s["duration_samples"]
            else None,
            "total_duration_s": round(s["duration_total_s"], 1) if s["duration_samples"] else None,
        }
    return result


def render_scorecard(card: dict[str, Any]) -> str:
    if not card:
        return "no runs recorded yet — the ledger is empty"
    rows = [
        ("skill", "runs", "find/run", "accept", "escaped", "mean_s"),
    ]
    for skill, m in card.items():
        acc = "—" if m["acceptance_rate"] is None else f"{m['acceptance_rate'] * 100:.0f}%"
        mean = "—" if m["mean_duration_s"] is None else f"{m['mean_duration_s']:.0f}"
        esc = str(m["escaped"]) if m["escaped"] else "·"
        rows.append((skill, str(m["runs"]), f"{m['findings_per_run']:g}", acc, esc, mean))
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    out = []
    for i, row in enumerate(rows):
        out.append("  ".join(cell.ljust(widths[c]) for c, cell in enumerate(row)))
        if i == 0:
            out.append("  ".join("-" * widths[c] for c in range(len(row))))
    escaped_any = any(m["escaped"] for m in card.values())
    if escaped_any:
        out.append("")
        out.append("⚠ escaped defects present — a skill that should have caught a prod bug missed it.")
    return "\n".join(out)


def check(runs_p: Path, outcomes_p: Path) -> list[str]:
    """Validate both ledgers parse and every record carries its required fields and a
    known enum value. Returns a list of problems (empty == clean)."""
    problems: list[str] = []
    try:
        runs = _read(runs_p)
    except ValueError as e:
        return [str(e)]
    try:
        outcomes = _read(outcomes_p)
    except ValueError as e:
        return [str(e)]

    for i, r in enumerate(runs, start=1):
        if not r.get("skill"):
            problems.append(f"runs.jsonl:{i}: missing skill")
        if r.get("run_type") not in RUN_TYPES:
            problems.append(f"runs.jsonl:{i}: bad run_type {r.get('run_type')!r}")
        if r.get("verdict") not in VERDICTS:
            problems.append(f"runs.jsonl:{i}: bad verdict {r.get('verdict')!r}")
    for i, o in enumerate(outcomes, start=1):
        if not o.get("ref"):
            problems.append(f"outcomes.jsonl:{i}: missing ref")
        if o.get("outcome") not in OUTCOMES:
            problems.append(f"outcomes.jsonl:{i}: bad outcome {o.get('outcome')!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Skill evaluation ledger and scorecard.")
    ap.add_argument("--check", action="store_true", help="validate the ledgers, exit 1 if malformed")
    sub = ap.add_subparsers(dest="cmd")

    rec = sub.add_parser("record", help="append a skill run")
    rec.add_argument("--skill", required=True)
    rec.add_argument("--run-type", required=True, choices=sorted(RUN_TYPES))
    rec.add_argument("--verdict", required=True, choices=sorted(VERDICTS))
    rec.add_argument("--scope", default=None, help="feature slug or area audited")
    rec.add_argument("--findings", type=int, default=0)
    rec.add_argument("--ref", default=None, help="MR ref (!123) or branch — the join key for outcomes")
    rec.add_argument("--duration", type=float, default=None, dest="duration_s")
    rec.add_argument("--notes", default=None)
    rec.add_argument("--date", default=None, help="YYYY-MM-DD to backfill a historical run (default: now)")

    oc = sub.add_parser("outcome", help="attach a resolution to a run/MR")
    oc.add_argument("--ref", required=True, help="the run's ref (MR ref or branch)")
    oc.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    oc.add_argument("--skill", default=None)
    oc.add_argument("--notes", default=None)
    oc.add_argument("--date", default=None, help="YYYY-MM-DD to backfill (default: now)")

    sc = sub.add_parser("scorecard", help="per-skill performance summary")
    sc.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)

    if args.check:
        problems = check(runs_path(), outcomes_path())
        if problems:
            print("ledger problems:", file=sys.stderr)
            for p in problems:
                print(f"  ✗ {p}", file=sys.stderr)
            return 1
        print("✓ ledgers well-formed")
        return 0

    if args.cmd == "record":
        try:
            rec_out = record_run(
                skill=args.skill,
                run_type=args.run_type,
                verdict=args.verdict,
                scope=args.scope,
                findings=args.findings,
                ref=args.ref,
                duration_s=args.duration_s,
                notes=args.notes,
                ts=_date_to_ts(args.date),
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"recorded run: {rec_out['skill']} {rec_out['verdict']} ({rec_out['findings']} findings)")
        return 0

    if args.cmd == "outcome":
        try:
            rec_out = record_outcome(
                ref=args.ref, outcome=args.outcome, skill=args.skill, notes=args.notes, ts=_date_to_ts(args.date)
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"recorded outcome: {rec_out['ref']} -> {rec_out['outcome']}")
        return 0

    if args.cmd == "scorecard":
        try:
            card = scorecard(_read(runs_path()), _read(outcomes_path()))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(json.dumps(card, indent=2) if args.json else render_scorecard(card))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
