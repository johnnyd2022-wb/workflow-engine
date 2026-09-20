"""The prior Whistlebird inventory database, kept in version control.

The replay used to read twelve tables straight from the prior database (`whistlebird_inventory`
on :5401), so it could not run anywhere that database was not also running. This module makes
the repository self-contained: it exports exactly the rows and columns the replay reads into
`docs/whistlebird-legacy-source.json`, and the loaders in `whistlebird_migration.py` read that
file by default. Pass a `postgresql://` URL instead to read the live database.

    uv run python scripts/whistlebird_legacy.py snapshot --legacy-url postgresql://...
    uv run python scripts/whistlebird_legacy.py verify   --legacy-url postgresql://...

One registry (`LEGACY_TABLES`) defines the columns for both the export and every loader, so
there is no SQL to keep in sync with the snapshot. Values are stored so they round-trip
exactly: dates as ISO strings, integers as integers, and floats as JSON numbers (Python's float
repr is exact). Only columns the replay actually reads are exported; `uid`, `action` and the like
are not.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, create_engine, text

DEFAULT_LEGACY_SNAPSHOT = Path(__file__).parents[1] / "docs" / "whistlebird-legacy-source.json"
SNAPSHOT_VERSION = 1


class LegacySnapshotError(ValueError):
    """The snapshot file is malformed or does not match the registry."""


@dataclass(frozen=True)
class TableSpec:
    columns: tuple[str, ...]
    date_columns: frozenset[str] = frozenset({"date"})
    order_by: str = "id"


# Exactly the columns each loader in whistlebird_migration.py reads. Adding a column to a
# loader means adding it here and re-running `snapshot`.
LEGACY_TABLES: dict[str, TableSpec] = {
    "purchases_gns": TableSpec(("id", "date", "supplier", "gns_purchased_l", "abv")),
    "purchases_empty_bottles": TableSpec(("id", "date", "supplier", "bottle_size_ml", "empty_bottles_stored")),
    "purchases_ingredients": TableSpec(
        (
            "id",
            "date",
            "supplier",
            "ingredients",
            "ingredients_amount",
            "ingredients_code",
            "ingredients_expiry",
        ),
        date_columns=frozenset({"date", "ingredients_expiry"}),
    ),
    "product_actions_create_premix": TableSpec(
        ("id", "date", "notes", "alcohol_volume", "alcohol_abv", "lal", "container_id")
    ),
    "customs_lodgements": TableSpec(("id", "date", "date_period", "lodged_volume", "lodged_abv", "lal", "bottles")),
    "product_actions_flavors": TableSpec(("id", "date", "flavor_code", "flavor_batch", "ingredient_codes")),
    "product_actions_bottling": TableSpec(
        ("id", "date", "bottles_stored", "abv", "bottle_size_ml", "vat_batch", "bottle_batch"),
        order_by="date, id",
    ),
    "product_actions_flavor_vat": TableSpec(("id", "date", "abv", "vat_batch", "volume_amount", "flavor_batch")),
    "product_actions_samples_consumed": TableSpec(
        ("id", "date", "flavor_code", "number_of_bottles", "abv", "bottle_size_ml")
    ),
    "product_actions_flavor_experiments": TableSpec(
        ("id", "date", "flavor_code", "flavor_stored_ml", "clearing_amount", "clearing_abv")
    ),
    "product_actions_distillation_experiments": TableSpec(
        ("id", "date", "experiment_id", "alcohol_yield_l", "alcohol_yield_abv", "alcohol_used_l", "lal", "notes")
    ),
    "product_actions_samples_created": TableSpec(
        ("id", "date", "flavor_code", "number_of_bottles", "abv", "bottle_size_ml")
    ),
}


class LegacySnapshot:
    """The committed export, presented to the loaders as if it were the database."""

    def __init__(self, tables: dict[str, list[dict[str, Any]]]):
        self._tables = tables

    def rows(self, table: str) -> list[dict[str, Any]]:
        try:
            return [dict(row) for row in self._tables[table]]
        except KeyError as exc:
            raise LegacySnapshotError(f"snapshot has no table {table!r}") from exc


# --- encoding ---------------------------------------------------------------------


def _encode(value: Any, where: str) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise LegacySnapshotError(f"{where}: non-finite number cannot be stored")
        return value
    if isinstance(value, date):
        return value.isoformat()
    # Failing loudly beats silently changing a type the loaders depend on (Decimal, datetime...).
    raise LegacySnapshotError(f"{where}: unsupported value type {type(value).__name__}")


def _decode(value: Any, column: str, spec: TableSpec, where: str) -> Any:
    if value is None:
        return None
    if column in spec.date_columns:
        if not isinstance(value, str):
            raise LegacySnapshotError(f"{where}: {column} must be an ISO date string")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise LegacySnapshotError(f"{where}: {column} is not an ISO date: {value!r}") from exc
    return value


def parse_snapshot(data: dict[str, Any]) -> LegacySnapshot:
    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        raise LegacySnapshotError("snapshot must be an object with a 'tables' object")
    if data.get("version") != SNAPSHOT_VERSION:
        raise LegacySnapshotError(f"unsupported snapshot version {data.get('version')!r}")
    tables_in = data["tables"]
    missing = sorted(set(LEGACY_TABLES) - set(tables_in))
    unknown = sorted(set(tables_in) - set(LEGACY_TABLES))
    if missing or unknown:
        raise LegacySnapshotError(f"snapshot tables differ from the registry: missing {missing}, unknown {unknown}")

    tables: dict[str, list[dict[str, Any]]] = {}
    for name, spec in LEGACY_TABLES.items():
        block = tables_in[name]
        if not isinstance(block, dict) or list(block.get("columns", [])) != list(spec.columns):
            raise LegacySnapshotError(
                f"{name}: columns {block.get('columns') if isinstance(block, dict) else block!r} "
                f"do not match the registry {list(spec.columns)}; re-run `snapshot`"
            )
        rows: list[dict[str, Any]] = []
        for index, raw in enumerate(block.get("rows", [])):
            where = f"{name}[{index}]"
            if not isinstance(raw, list) or len(raw) != len(spec.columns):
                raise LegacySnapshotError(f"{where}: expected a row of {len(spec.columns)} values")
            rows.append({c: _decode(v, c, spec, where) for c, v in zip(spec.columns, raw, strict=True)})
        ids = [row["id"] for row in rows]
        if len(set(ids)) != len(ids):
            raise LegacySnapshotError(f"{name}: duplicate id")
        tables[name] = rows
    return LegacySnapshot(tables)


def load_snapshot(path: Path = DEFAULT_LEGACY_SNAPSHOT) -> LegacySnapshot:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacySnapshotError(f"cannot read legacy snapshot {path}: {exc}") from exc
    return parse_snapshot(data)


# --- reading (snapshot or live database) ------------------------------------------


def legacy_rows(source: Connection | LegacySnapshot, table: str) -> list[dict[str, Any]]:
    """Every row of `table` with the registry's columns, from either kind of source."""
    if isinstance(source, LegacySnapshot):
        return source.rows(table)
    spec = LEGACY_TABLES[table]
    sql = f"SELECT {', '.join(spec.columns)} FROM {table} ORDER BY {spec.order_by}"  # registry constants only
    return [dict(row) for row in source.execute(text(sql)).mappings()]


@contextmanager
def open_legacy(source: str | Path | LegacySnapshot) -> Iterator[Connection | LegacySnapshot]:
    """A URL opens the live database; a path (or a LegacySnapshot) uses the committed export."""
    if isinstance(source, LegacySnapshot):
        yield source
    elif "://" in str(source):
        engine = create_engine(str(source))
        try:
            with engine.connect() as connection:
                yield connection
        finally:
            engine.dispose()
    else:
        yield load_snapshot(Path(source))


# --- export and drift check -------------------------------------------------------


def export_snapshot(legacy_url: str, exported_on: date | None = None) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    with open_legacy(legacy_url) as connection:
        for name, spec in LEGACY_TABLES.items():
            rows = [[_encode(row[c], f"{name}.{c}") for c in spec.columns] for row in legacy_rows(connection, name)]
            tables[name] = {"columns": list(spec.columns), "rows": rows}
    return {
        "version": SNAPSHOT_VERSION,
        "exported_on": (exported_on or date.today()).isoformat(),
        "tables": tables,
    }


_COMMENT = (
    "Every row and column the Whistlebird Ltd replay reads from the prior Whistlebird inventory "
    "database (whistlebird_inventory), so the org can be rebuilt from this repository alone. "
    "Generated by scripts/whistlebird_legacy.py; the column list per table is that module's "
    "LEGACY_TABLES registry. Values are stored exactly (dates ISO, floats as recorded). Do not "
    "edit by hand: fix the source and re-run `snapshot`, or add curation to the other manifests "
    "in docs/. Purchases dated 2025-05-13 onward are curated in whistlebird-raw-material-source.json."
)


def render(snapshot: dict[str, Any]) -> str:
    """Stable, review-friendly JSON: one row per line so git diffs show exactly which rows changed."""
    lines = ["{", f'  "_comment": {json.dumps(_COMMENT)},']
    lines.append(f'  "version": {snapshot["version"]},')
    lines.append(f'  "exported_on": {json.dumps(snapshot["exported_on"])},')
    lines.append('  "tables": {')
    names = list(snapshot["tables"])
    for t_index, name in enumerate(names):
        block = snapshot["tables"][name]
        lines.append(f"    {json.dumps(name)}: {{")
        lines.append(f'      "columns": {json.dumps(block["columns"])},')
        lines.append('      "rows": [')
        for r_index, row in enumerate(block["rows"]):
            comma = "," if r_index < len(block["rows"]) - 1 else ""
            lines.append(f"        {json.dumps(row, ensure_ascii=False, allow_nan=False)}{comma}")
        lines.append("      ]")
        lines.append("    }" + ("," if t_index < len(names) - 1 else ""))
    lines.extend(["  }", "}", ""])
    return "\n".join(lines)


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    Path(path).write_text(render(snapshot), encoding="utf-8")


def diff_against(legacy_url: str, path: Path = DEFAULT_LEGACY_SNAPSHOT) -> list[str]:
    """Human-readable differences between the live database and the committed snapshot."""
    committed = load_snapshot(path)
    problems: list[str] = []
    with open_legacy(legacy_url) as connection:
        for name, spec in LEGACY_TABLES.items():
            live = {row["id"]: row for row in legacy_rows(connection, name)}
            kept = {row["id"]: row for row in committed.rows(name)}
            for row_id in sorted(set(live) - set(kept)):
                problems.append(f"{name}#{row_id}: in the database, not in the snapshot")
            for row_id in sorted(set(kept) - set(live)):
                problems.append(f"{name}#{row_id}: in the snapshot, no longer in the database")
            for row_id in sorted(set(live) & set(kept)):
                # Compare the type too: `2 == 2.0` in Python, but the loaders format values with
                # str(), so an int that came back as a float would change what is replayed.
                changed = [
                    c
                    for c in spec.columns
                    if type(live[row_id][c]) is not type(kept[row_id][c]) or live[row_id][c] != kept[row_id][c]
                ]
                if changed:
                    problems.append(f"{name}#{row_id}: differs in {changed}")
    return problems


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="Export the live legacy database into the committed JSON.")
    snap.add_argument("--legacy-url", required=True)
    snap.add_argument("--output", type=Path, default=DEFAULT_LEGACY_SNAPSHOT)
    snap.add_argument("--dry-run", action="store_true", help="Print row counts; write nothing.")
    check = sub.add_parser("verify", help="Compare the live legacy database with the committed JSON.")
    check.add_argument("--legacy-url", required=True)
    check.add_argument("--snapshot", type=Path, default=DEFAULT_LEGACY_SNAPSHOT)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if args.command == "snapshot":
        snapshot = export_snapshot(args.legacy_url)
        counts = {name: len(block["rows"]) for name, block in snapshot["tables"].items()}
        print(json.dumps(counts, indent=1))
        if args.dry_run:
            return 0
        write_snapshot(args.output, snapshot)
        print(f"wrote {args.output}")
        return 0
    problems = diff_against(args.legacy_url, args.snapshot)
    for problem in problems:
        print(problem, file=sys.stderr)
    print("legacy snapshot matches the database" if not problems else f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
