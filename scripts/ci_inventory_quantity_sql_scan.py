#!/usr/bin/env python3
"""Optional CI scan: flag raw SQL patterns that touch inventory_items.quantity.

Excludes Alembic migrations (DDL/DML under app.migration_mode) and this guard module.
Run from repo root: python scripts/ci_inventory_quantity_sql_scan.py [--strict]

With --strict, exit 1 when any match is found (for CI gates). Default: print and exit 0.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Obvious bypass patterns (not exhaustive).
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bUPDATE\s+inventory_items\b", re.IGNORECASE), "UPDATE inventory_items"),
    (re.compile(r"\bINSERT\s+INTO\s+inventory_items\b", re.IGNORECASE), "INSERT INTO inventory_items"),
]

SKIP_SUBSTR = (
    str(Path("app/core/db/migrations/versions")),
    "inventory_quantity_guard.py",
    "ci_inventory_quantity_sql_scan.py",
)


def _should_skip(path: Path) -> bool:
    rel = path.as_posix()
    return any(s in rel for s in SKIP_SUBSTR)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 if any match is found under app/ (excluding migrations).",
    )
    args = p.parse_args(argv)

    bad: list[tuple[str, str]] = []
    for py in ROOT.joinpath("app").rglob("*.py"):
        if _should_skip(py):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for pat, label in PATTERNS:
            if pat.search(text):
                bad.append((py.relative_to(ROOT).as_posix(), label))

    if not bad:
        return 0

    for rel, label in sorted(bad):
        print(f"{rel}: {label}")
    print(f"ci_inventory_quantity_sql_scan: {len(bad)} file(s) — review; use ORM allow path or migration_mode.")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
