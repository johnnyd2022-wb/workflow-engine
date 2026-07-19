#!/usr/bin/env python3
"""Historical-findings store: give review skills compounding memory across runs.

Today `review-feature` and `security-audit` start every run cold. They re-surface the same
finding a human already looked at and rejected ("this f-string is a constant, not
injection") — which trains the reader to skim past the report, which is how the one real
finding gets skimmed past too. And when a bug that was fixed months ago quietly comes back,
nothing says "you have seen this before, it's a regression."

This store fixes both. Every finding gets a stable, tool-agnostic **signature** (area +
kind + normalised evidence, so it survives line moves and renumbering). Verdicts are
recorded against that signature, append-only. Before surfacing a finding, a skill asks
`decide` and gets one of:

  new              no history — surface it normally
  known-confirmed  seen and confirmed before — surface, with the prior context
  recurring        was FIXED and is back — a regression; surface loudly
  suppress         a human already ruled it false-positive / accepted-risk — do not re-raise

Suppression is only ever granted by a recorded human verdict (false-positive /
accepted-risk), never invented by the tool — same rule as `.agents/autonomy.md`: an agent
may recommend accepted-risk, only a human grants it.

Store: `.agents/history/findings.jsonl` (override the dir with $HISTORY_DIR for tests).

Usage:
    # compute the canonical signature (so every caller agrees on it)
    python scripts/finding_history.py signature --area app/features/crm --kind sql-injection \\
        --evidence 'session.execute(f"select ... {user_id}")'

    # before surfacing a finding, ask what to do with it
    python scripts/finding_history.py decide --area app/features/crm --kind sql-injection \\
        --evidence 'session.execute(f"...")'

    # after a human (or the skill, for confirmed/fixed) rules on it, record the verdict
    python scripts/finding_history.py record --area app/features/crm --kind sql-injection \\
        --evidence 'session.execute(f"...")' --verdict false-positive --skill security-audit \\
        --ref '!123' --notes 'constant query, no user input'

    python scripts/finding_history.py --check     # exit 1 if the store is malformed

Exit codes: 0 = ok, 1 = malformed store (--check) or bad input, 2 = usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# confirmed      a real defect, surfaced and actioned            -> stays visible
# fixed          confirmed and since patched                     -> a later reappearance is a regression
# false-positive a human ruled it not a real issue               -> suppressed
# accepted-risk  a human accepted it knowingly                   -> suppressed until conditions change
VERDICTS = {"confirmed", "fixed", "false-positive", "accepted-risk"}
SUPPRESSING = {"false-positive", "accepted-risk"}

# Volatile substrings that would otherwise split one finding into many signatures. Kept
# deliberately close to error_scan.py's noise list — same problem, same normalisation.
_NOISE = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<addr>"),
    (re.compile(r"\b\d+\b"), "<n>"),
    (re.compile(r"\s+"), " "),
]


def history_dir() -> Path:
    override = os.environ.get("HISTORY_DIR")
    return Path(override) if override else REPO_ROOT / ".agents" / "history"


def store_path() -> Path:
    return history_dir() / "findings.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date_to_ts(date_str: str | None) -> str | None:
    """--date YYYY-MM-DD -> ISO ts (midnight UTC), for backfilling a historical verdict
    with its real date instead of today. None means 'use now'."""
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(f"--date must be YYYY-MM-DD, got {date_str!r}") from e
    return d.isoformat(timespec="seconds")


def normalise_evidence(evidence: str) -> str:
    """Collapse the volatile parts of a finding's evidence so the same bug in the same
    place hashes the same next time, even if line numbers, ids, or literals shifted."""
    out = evidence.strip().lower()
    for pat, repl in _NOISE:
        out = pat.sub(repl, out)
    return out.strip()


def signature(area: str, kind: str, evidence: str) -> str:
    """Stable 12-char signature. `area` is a path or feature slug (not a line number),
    `kind` is the rule id or vulnerability class, `evidence` is the offending snippet."""
    basis = f"{area.strip()}|{kind.strip().lower()}|{normalise_evidence(evidence)}"
    return sha1(basis.encode("utf-8")).hexdigest()[:12]


def _read() -> list[dict[str, Any]]:
    path = store_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"findings.jsonl:{i}: not valid JSON ({e})") from e
        if not isinstance(rec, dict):
            raise ValueError(f"findings.jsonl:{i}: expected an object")
        out.append(rec)
    return out


def _append(rec: dict[str, Any]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def record(
    *,
    area: str,
    kind: str,
    evidence: str,
    verdict: str,
    skill: str | None = None,
    ref: str | None = None,
    notes: str | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")
    rec = {
        "ts": ts or _now(),
        "sig": signature(area, kind, evidence),
        "area": area,
        "kind": kind,
        "verdict": verdict,
        "skill": skill,
        "ref": ref,
        "notes": notes,
    }
    _append(rec)
    return rec


def history_for(sig: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All records for a signature, in write order (oldest first)."""
    return [r for r in records if r.get("sig") == sig]


def decide(area: str, kind: str, evidence: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure: what should a skill do with this finding, given the store?

    The LAST recorded verdict for the signature is authoritative (a re-review can overturn
    an earlier call). 'recurring' beats a plain 'confirmed' because a defect that was marked
    fixed and is back is a strictly worse signal than one that was merely open.
    """
    sig = signature(area, kind, evidence)
    hist = history_for(sig, records)
    if not hist:
        return {"action": "new", "sig": sig, "history": []}
    last = hist[-1]["verdict"]
    if last in SUPPRESSING:
        action = "suppress"
    elif last == "fixed":
        action = "recurring"  # it was fixed; seeing it again is a regression
    else:  # confirmed
        action = "known-confirmed"
    return {
        "action": action,
        "sig": sig,
        "last_verdict": last,
        "seen": len(hist),
        "history": [
            {"ts": h["ts"], "verdict": h["verdict"], "ref": h.get("ref"), "notes": h.get("notes")} for h in hist
        ],
    }


def check() -> list[str]:
    try:
        records = _read()
    except ValueError as e:
        return [str(e)]
    problems: list[str] = []
    for i, r in enumerate(records, start=1):
        if not r.get("sig"):
            problems.append(f"findings.jsonl:{i}: missing sig")
        if not r.get("area"):
            problems.append(f"findings.jsonl:{i}: missing area")
        if r.get("verdict") not in VERDICTS:
            problems.append(f"findings.jsonl:{i}: bad verdict {r.get('verdict')!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Historical-findings store for review skills.")
    ap.add_argument("--check", action="store_true", help="validate the store, exit 1 if malformed")
    sub = ap.add_subparsers(dest="cmd")

    def add_finding_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--area", required=True, help="path or feature slug (NOT a line number)")
        p.add_argument("--kind", required=True, help="rule id or vulnerability/defect class")
        p.add_argument("--evidence", required=True, help="the offending snippet / repro")

    sig = sub.add_parser("signature", help="print the canonical signature")
    add_finding_args(sig)

    dec = sub.add_parser("decide", help="new | known-confirmed | recurring | suppress")
    add_finding_args(dec)
    dec.add_argument("--json", action="store_true")

    rec = sub.add_parser("record", help="record a verdict against a finding")
    add_finding_args(rec)
    rec.add_argument("--verdict", required=True, choices=sorted(VERDICTS))
    rec.add_argument("--skill", default=None)
    rec.add_argument("--ref", default=None)
    rec.add_argument("--notes", default=None)
    rec.add_argument("--date", default=None, help="YYYY-MM-DD to backfill a historical verdict (default: now)")

    args = ap.parse_args(argv)

    if args.check:
        problems = check()
        if problems:
            print("history store problems:", file=sys.stderr)
            for p in problems:
                print(f"  ✗ {p}", file=sys.stderr)
            return 1
        print("✓ history store well-formed")
        return 0

    if args.cmd == "signature":
        print(signature(args.area, args.kind, args.evidence))
        return 0

    if args.cmd == "decide":
        try:
            result = decide(args.area, args.kind, args.evidence, _read())
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            line = f"{result['action']}  (sig {result['sig']}"
            if result["history"]:
                line += f", last={result.get('last_verdict')}, seen={result.get('seen')}"
            print(line + ")")
        return 0

    if args.cmd == "record":
        try:
            out = record(
                area=args.area,
                kind=args.kind,
                evidence=args.evidence,
                verdict=args.verdict,
                skill=args.skill,
                ref=args.ref,
                notes=args.notes,
                ts=_date_to_ts(args.date),
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"recorded {out['verdict']} for sig {out['sig']} ({out['area']} / {out['kind']})")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
