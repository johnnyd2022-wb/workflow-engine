#!/usr/bin/env python3
"""Record sourced market indicator observations in the shared development metrics DB.

Usage:
  uv run python scripts/market_research_metrics.py record --file observations.json
  uv run python scripts/market_research_metrics.py history --scope craft-spirits-new-zealand

The input is a JSON object with scope_key, report_path, and indicators (an array).
Each indicator needs metric_key, measured_on, unit, geography, source_ref, confidence,
and at least one of value/lower_bound/upper_bound. See the market-research skill.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import metrics_db

REQUIRED = ("metric_key", "measured_on", "unit", "geography", "source_ref", "confidence")
DATES = ("measured_on", "period_start", "period_end", "source_published_on")
NUMBERS = ("value", "lower_bound", "upper_bound", "threshold_value")
FIELDS = set(metrics_db._INDICATOR_COLS)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _report_path(value: Any) -> str:
    raw = Path(_nonempty(value, "report_path"))
    resolved = (raw if raw.is_absolute() else REPO_ROOT / raw).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as e:
        raise ValueError("report_path must be within this repository; save a local copy first") from e


def parse_batch(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ValueError("input must be a JSON object")
    scope = _nonempty(raw.get("scope_key"), "scope_key")
    report = _report_path(raw.get("report_path"))
    items = raw.get("indicators")
    if not isinstance(items, list) or not items:
        raise ValueError("indicators must be a non-empty array")
    records = []
    seen = set()
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"indicator {i} must be an object")
        unknown = set(item) - FIELDS
        if unknown:
            raise ValueError(f"indicator {i} has unknown fields: {sorted(unknown)}")
        row = {key: item.get(key) for key in FIELDS}
        row.update(scope_key=scope, report_path=report)
        for key in REQUIRED:
            row[key] = _nonempty(row[key], f"indicator {i} {key}")
        if row["confidence"] not in {"low", "medium", "high"}:
            raise ValueError(f"indicator {i} confidence must be low, medium, or high")
        if row["refresh_cadence"] is not None:
            row["refresh_cadence"] = _nonempty(row["refresh_cadence"], f"indicator {i} refresh_cadence")
        for key in DATES:
            if row[key] is not None:
                try:
                    row[key] = date.fromisoformat(str(row[key])).isoformat()
                except ValueError as e:
                    raise ValueError(f"indicator {i} {key} must be YYYY-MM-DD") from e
        for key in NUMBERS:
            if row[key] is not None:
                try:
                    row[key] = Decimal(str(row[key]))
                except (InvalidOperation, ValueError) as e:
                    raise ValueError(f"indicator {i} {key} must be numeric") from e
                if not row[key].is_finite():
                    raise ValueError(f"indicator {i} {key} must be finite")
        if all(row[k] is None for k in ("value", "lower_bound", "upper_bound")):
            raise ValueError(f"indicator {i} needs a value or estimate bound")
        lo, val, hi = row["lower_bound"], row["value"], row["upper_bound"]
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"indicator {i} lower_bound exceeds upper_bound")
        if val is not None and ((lo is not None and val < lo) or (hi is not None and val > hi)):
            raise ValueError(f"indicator {i} value falls outside its bounds")
        op = row["threshold_operator"]
        if (op is None) != (row["threshold_value"] is None) or op not in {None, "above", "below"}:
            raise ValueError(f"indicator {i} threshold needs an above/below operator and value")
        if row["period_start"] and row["period_end"] and row["period_start"] > row["period_end"]:
            raise ValueError(f"indicator {i} period_start exceeds period_end")
        key = row["metric_key"]
        if key in seen:
            raise ValueError(f"duplicate metric_key in report: {key}")
        seen.add(key)
        for number in NUMBERS:
            if row[number] is not None:
                row[number] = str(row[number])  # JSON-safe for the outage spool
        records.append(row)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="validate and append observations")
    record.add_argument("--file", required=True, help="JSON file, or - for stdin")
    record.add_argument("--dry-run", action="store_true", help="validate without writing")
    history = sub.add_parser("history", help="show observations for one scope")
    history.add_argument("--scope", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            raw = json.load(sys.stdin) if args.file == "-" else json.loads(Path(args.file).read_text(encoding="utf-8"))
            rows = parse_batch(raw)
            if args.dry_run:
                print(f"valid: {len(rows)} indicators")
                return 0
            destinations = [metrics_db.store("indicator", row) for row in rows]
            print(
                f"recorded: {destinations.count('inserted')} inserted, "
                f"{destinations.count('already-present')} already present, "
                f"{destinations.count('spooled')} spooled"
            )
        else:
            rows = metrics_db.market_indicator_history(_nonempty(args.scope, "scope"))
            print(json.dumps(rows, default=str, indent=2))
        return 0
    except (
        ValueError,
        OSError,
        json.JSONDecodeError,
        metrics_db.MetricsDBUnavailableError,
        metrics_db.IndicatorConflictError,
    ) as e:
        print(f"market_research_metrics: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
