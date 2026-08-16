#!/usr/bin/env python3
"""Structural check for the core-flow test map at .agents/test-map.md.

The map claims which test files prove which core flows. That claim rots two ways, both
silent: a row names a test file that was renamed or deleted (a dangling row), or a new
`tests/test_*.py` gets written and never added to any row (coverage the map is blind to).
Neither errors on its own; this script makes both loud.

It is deliberately structural only. It cannot judge whether a row's *status* is honest
(`covered` vs `partial`) — that is a reading task for test-author, and whether a listed
test is a valid claim at all is test-evaluator's. This script answers exactly: does every
referenced file exist, and is every real test file referenced.

Design mirrors scripts/skill_graph.py and scripts/preflight.py: stdlib only, `--json` for
agents, a human summary by default, and `--check` exits non-zero on any problem.

Usage:
    python3 scripts/test_map_check.py            # human summary
    python3 scripts/test_map_check.py --json     # machine-readable
    python3 scripts/test_map_check.py --check    # exit 1 if any problem
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MAP = REPO_ROOT / ".agents" / "test-map.md"
TESTS_DIR = REPO_ROOT / "tests"

# A referenced test filename in the map: test_<...>.py, where <...> may contain a glob '*'
# (row 23 references `test_observability_*.py` as a family rather than ten literal names).
# The scripts/ lookbehind stops the map's prose mention of `scripts/test_map_check.py`
# (this very script) from being read as a dangling test-file reference.
REF_RE = re.compile(r"(?<!scripts/)test_[A-Za-z0-9_*]+\.py")

# A table row: `| 18 | Flow text | App area | Test file(s) | partial | Notes... |`.
# Cells 2-4 (Flow / App area / Test files) use `[^|]*` rather than `.*` so a greedy `.*`
# can't skip past the real Status cell and match a later `| covered |`-shaped substring
# inside the free-text Notes column instead.
TABLE_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|[^|]*\|[^|]*\|[^|]*\|\s*(covered|partial|none|live)\s*\|", re.MULTILINE)

GAPS_HEADING = "## Known highest-value gaps"

# A row reference inside that section's bullet list: "**Row 8 / 14 / 16**", "**Row 12**",
# "**Rows 6/7**" — capture the whole digit/separator run after "Row"/"Rows", then split it.
GAP_ROW_REF_RE = re.compile(r"\*\*Rows?\s+([\d/,\s]+)\*\*")


def real_test_files() -> set[str]:
    """Every tests/test_*.py basename that actually exists on disk."""
    if not TESTS_DIR.is_dir():
        raise SystemExit(f"no tests dir at {TESTS_DIR}")
    return {p.name for p in TESTS_DIR.glob("test_*.py")}


def referenced_patterns() -> list[str]:
    """Every test-filename token the map names (literal or glob), de-duped, in order."""
    if not MAP.exists():
        raise SystemExit(f"no test map at {MAP}")
    text = MAP.read_text(encoding="utf-8")
    seen: dict[str, None] = {}
    for m in REF_RE.findall(text):
        seen.setdefault(m, None)
    return list(seen)


def row_statuses(text: str) -> dict[int, str]:
    """Row number -> current Status column value, read straight from the table."""
    return {int(m.group(1)): m.group(2) for m in TABLE_ROW_RE.finditer(text)}


def stale_gap_refs(text: str) -> list[str]:
    """Rows the '## Known highest-value gaps' section still cites as owed, that the
    table above it already marks `covered` — the gaps section rotting silently out of
    sync with its own table (this file's own admission: it "cannot judge whether a
    row's status is truthful", so nothing else catches this)."""
    if GAPS_HEADING not in text:
        return []
    gaps_section = text.split(GAPS_HEADING, 1)[1].split("\n## ", 1)[0]
    statuses = row_statuses(text)
    stale: list[str] = []
    for m in GAP_ROW_REF_RE.finditer(gaps_section):
        for n in re.findall(r"\d+", m.group(1)):
            row_num = int(n)
            if statuses.get(row_num) == "covered":
                stale.append(f"Row {row_num}")
    return stale


def analyse() -> dict[str, Any]:
    if not MAP.exists():
        raise SystemExit(f"no test map at {MAP}")
    text = MAP.read_text(encoding="utf-8")
    existing = real_test_files()
    patterns = referenced_patterns()

    # A pattern is dangling if it matches no real file (a deleted/renamed test still cited).
    dangling = [p for p in patterns if not any(fnmatch.fnmatch(f, p) for f in existing)]

    # A file is unreferenced if no pattern (literal or glob) in the map matches it.
    referenced_files = {f for f in existing if any(fnmatch.fnmatch(f, p) for p in patterns)}
    unreferenced = sorted(existing - referenced_files)

    problems = {
        "dangling_rows": sorted(dangling),
        "unreferenced_files": unreferenced,
        "stale_gap_refs": stale_gap_refs(text),
    }
    return {
        "map": str(MAP.relative_to(REPO_ROOT)),
        "test_files_on_disk": len(existing),
        "patterns_in_map": len(patterns),
        "ok": not any(problems.values()),
        "problems": problems,
    }


def render(report: dict[str, Any]) -> str:
    p = report["problems"]
    out = [
        f"test map: {report['test_files_on_disk']} test files on disk, "
        f"{report['patterns_in_map']} referenced in {report['map']}",
        "",
    ]
    if p["dangling_rows"]:
        out.append("  DANGLING ROWS (map names a test file that does not exist):")
        out += [f"    ✗ {n}" for n in p["dangling_rows"]]
    if p["unreferenced_files"]:
        out.append("  UNREFERENCED (test file on disk, in no map row — coverage the map is blind to):")
        out += [f"    ✗ {n}" for n in p["unreferenced_files"]]
    if p["stale_gap_refs"]:
        out.append("  STALE GAP REFS ('Known highest-value gaps' cites a row the table already marks covered):")
        out += [f"    ✗ {n}" for n in p["stale_gap_refs"]]
    if report["ok"]:
        out.append("  ✓ every map row resolves to a real test file, and every test file is mapped")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Structural check for .agents/test-map.md.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 if any problem")
    args = ap.parse_args()

    report = analyse()
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["ok"] or not args.check else 1


if __name__ == "__main__":
    sys.exit(main())
