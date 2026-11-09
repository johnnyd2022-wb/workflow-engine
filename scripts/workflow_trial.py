#!/usr/bin/env python3
"""Lean vs classic: the trial report for the workflow switch (.agents/workflow-mode.json).

Reads the skill-run ledger (bize_dev metrics, see scripts/metrics_db.py) and compares runs
tagged `workflow=lean` with the classic front doors, by risk tier:

    python3 scripts/workflow_trial.py            # table
    python3 scripts/workflow_trial.py --json

Per workflow and tier: runs, review rounds, findings, elapsed time, and what became of the
MR (merged / amended / escaped). Unknown values stay unknown, never zero. It reports; it
doesn't decide. The keep-or-revert call is the founder's, on the rule in workflow-mode.json.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CLASSIC_SKILLS = {"new-feature", "fix-bug", "review-feature"}
_TAG = re.compile(r"\b(workflow|tier|rounds|kind|reviewer)=([\w-]+)")


def _tags(notes) -> dict[str, str]:
    return dict(_TAG.findall(str(notes or "")))


def workflow_of(run: dict) -> str | None:
    tags = _tags(run.get("notes"))
    if tags.get("workflow") in ("lean", "classic"):
        return tags["workflow"]
    if run.get("skill") == "lean-change":
        return "lean"
    if run.get("skill") in CLASSIC_SKILLS:
        return "classic"
    return None


def summarize(runs: list[dict], outcomes: list[dict]) -> dict:
    latest_outcome = {}
    for row in outcomes:
        if row.get("ref"):
            latest_outcome[str(row["ref"])] = row.get("outcome")
    groups: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        flow = workflow_of(run)
        if flow is None:
            continue
        tier = _tags(run.get("notes")).get("tier", "?")
        groups.setdefault((flow, tier), []).append(run)
    out = {}
    for (flow, tier), rows in sorted(groups.items()):
        rounds = [int(t["rounds"]) for t in (_tags(r.get("notes")) for r in rows) if t.get("rounds", "").isdigit()]
        durations = [float(r["duration_s"]) for r in rows if r.get("duration_s") not in (None, "")]
        findings = [int(r["findings"]) for r in rows if r.get("findings") is not None]
        fates = [latest_outcome.get(str(r.get("ref"))) for r in rows if r.get("ref")]
        out[f"{flow}/{tier}"] = {
            "runs": len(rows),
            "median_rounds": statistics.median(rounds) if rounds else None,
            "median_minutes": round(statistics.median(durations) / 60, 1) if durations else None,
            "mean_findings": round(statistics.mean(findings), 1) if findings else None,
            "merged": sum(1 for f in fates if f == "merged"),
            "amended": sum(1 for f in fates if f == "amended"),
            "escaped": sum(1 for f in fates if f == "escaped"),
            "no_outcome_yet": sum(1 for f in fates if f is None),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    import metrics_db

    try:
        report = summarize(metrics_db.fetch("run"), metrics_db.fetch("outcome"))
    except Exception as exc:  # the ledger is down: say so, don't print an empty "result"
        print(f"metrics ledger unavailable: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    if not report:
        print("No lean or classic runs recorded yet.")
        return 0
    cols = (
        "runs",
        "median_rounds",
        "median_minutes",
        "mean_findings",
        "merged",
        "amended",
        "escaped",
        "no_outcome_yet",
    )
    print(f"{'workflow/tier':<14}" + "".join(f"{c:>16}" for c in cols))
    for key, row in report.items():
        print(f"{key:<14}" + "".join(f"{'-' if row[c] is None else row[c]!s:>16}" for c in cols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
