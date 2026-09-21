"""Replayable suppliers for Whistlebird Ltd.

The suppliers an organisation buys from live in the Core address book (`suppliers`). This module
rebuilds Whistlebird's from version control, the same way the Core history and NP3 evidence are:

1. **Replay** (`replay_suppliers`, called by `scripts/whistlebird_replay.py` after the Core
   history) creates each supplier in `docs/whistlebird-suppliers-source.json` through the real
   API, so each one is audited exactly as if it had been added in the app.
2. **Dating** (`date_suppliers`, run by `scripts/whistlebird_rebuild_api.py` after the timestamp
   passes) moves each supplier's creation, and its audit entries, to the date the business first
   bought from them (their earliest inventory lot) instead of the day the tenant was rebuilt.
   Internal tooling for the disposable Whistlebird Ltd tenant only; the app itself always stamps
   an action when it happens.

Supplier names match the `supplier` text on inventory items exactly, so "import from inventory"
never adds a second copy. Details were taken from each business's own website; where a business
publishes no phone, email or street address the field is left empty rather than guessed. No supplier
has a main contact.

    uv run python scripts/whistlebird_suppliers.py validate
    uv run python scripts/whistlebird_suppliers.py apply  --base-url https://localhost:8005 --insecure
    uv run python scripts/whistlebird_suppliers.py verify --target-url postgresql://...

`apply` is idempotent: it adds only the suppliers that are missing, then dates and verifies them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_migration as wm  # noqa: E402

DEFAULT_SUPPLIERS_MANIFEST = Path(__file__).parents[1] / "docs" / "whistlebird-suppliers-source.json"


class SuppliersManifestError(ValueError):
    """The suppliers manifest is malformed, or asks for something the API would reject."""


class SuppliersReplayError(RuntimeError):
    """The suppliers could not be replayed or verified."""


@dataclass(frozen=True)
class SuppliersManifest:
    suppliers: tuple[dict[str, str | None], ...]


def parse_suppliers_manifest(data: Any) -> SuppliersManifest:
    """Validate with the API's own rules, so a bad manifest fails before any destructive step."""
    from app.core.backend.suppliers import FIELDS, SupplierError, clean_fields

    if not isinstance(data, dict) or set(data) != {"suppliers"} or not isinstance(data["suppliers"], list):
        raise SuppliersManifestError('manifest must be an object with a "suppliers" list')
    suppliers: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for index, entry in enumerate(data["suppliers"]):
        where = f"suppliers[{index}]"
        if not isinstance(entry, dict):
            raise SuppliersManifestError(f"{where}: must be an object")
        unknown = sorted(set(entry) - set(FIELDS))
        if unknown:
            raise SuppliersManifestError(f"{where}: unknown key(s) {', '.join(unknown)}")
        try:
            cleaned = clean_fields(entry)
        except SupplierError as exc:
            raise SuppliersManifestError(f"{where}: {exc}") from None
        if not cleaned.get("name"):
            raise SuppliersManifestError(f"{where}: name is required")
        if cleaned["name"].casefold() in seen:
            raise SuppliersManifestError(f"{where}: duplicate supplier {cleaned['name']!r}")
        seen.add(cleaned["name"].casefold())
        suppliers.append({key: cleaned.get(key) for key in FIELDS})
    return SuppliersManifest(suppliers=tuple(suppliers))


def load_suppliers_manifest(path: Path = DEFAULT_SUPPLIERS_MANIFEST) -> SuppliersManifest:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SuppliersManifestError(f"cannot read suppliers manifest {path}: {exc}") from exc
    return parse_suppliers_manifest(data)


def replay_suppliers(client: Any, manifest: SuppliersManifest) -> dict[str, int]:
    """Issue the manifest through the real API. Resumable: suppliers already present are skipped."""
    present = {str(row["name"]).casefold() for row in client.get("/api/core/suppliers").get("suppliers", [])}
    counts = {"created": 0, "skipped": 0}
    for supplier in manifest.suppliers:
        if str(supplier["name"]).casefold() in present:
            counts["skipped"] += 1
            continue
        client.post("/api/core/suppliers", {key: value for key, value in supplier.items() if value})
        counts["created"] += 1
    return counts


def _require_test_tenant(org_name: str) -> None:
    if org_name != wm.WHISTLEBIRD_ORG_NAME:
        raise SuppliersReplayError(f"suppliers may only be dated for {wm.WHISTLEBIRD_ORG_NAME!r}, not {org_name!r}")


def _org_id(conn: Any, org_name: str) -> Any:
    org_id = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).scalar()
    if org_id is None:
        raise SuppliersReplayError(f"organisation {org_name!r} does not exist")
    return org_id


# A supplier's first purchase: the earliest inventory lot naming them (already dated by the timestamp pass).
_FIRST_PURCHASE = (
    "SELECT s.id, min(i.created_at) FROM suppliers s JOIN inventory_items i "
    "ON i.org_id = s.org_id AND lower(i.supplier) = lower(s.name) WHERE s.org_id = :org GROUP BY s.id"
)


def date_suppliers(target_url: str, org_name: str) -> dict[str, int]:
    """Date each supplier's creation, and its create audit entries, to their first purchase.

    Only creation is moved. A later edit made in the app keeps its real time, so re-running this
    after real use never rewrites history."""
    _require_test_tenant(org_name)
    engine = create_engine(target_url)
    dated = 0
    try:
        with engine.begin() as conn:
            org_id = _org_id(conn, org_name)
            for supplier_id, at in conn.execute(text(_FIRST_PURCHASE), {"org": org_id}).all():
                params = {"at": at, "id": supplier_id, "org": org_id}
                edited = conn.execute(
                    text(
                        "SELECT count(*) FROM entity_events WHERE org_id = :org AND entity_id = :id "
                        "AND event_type = 'supplier.updated'"
                    ),
                    params,
                ).scalar_one()
                conn.execute(
                    text(
                        "UPDATE suppliers SET created_at = :at, updated_at = CASE WHEN :edited THEN updated_at "
                        "ELSE :at END WHERE org_id = :org AND id = :id"
                    ),
                    {**params, "edited": bool(edited)},
                )
                conn.execute(
                    text(
                        "UPDATE entity_events SET created_at = :at WHERE org_id = :org AND entity_id = :id "
                        "AND event_type = 'supplier.created'"
                    ),
                    params,
                )
                conn.execute(
                    text(
                        "UPDATE audit_logs SET timestamp = :at WHERE org_id = :org AND entity = 'supplier' "
                        "AND action = 'create' AND entity_id = :id"
                    ),
                    params,
                )
                dated += 1
    finally:
        engine.dispose()
    return {"suppliers_dated": dated}


def verify_suppliers(target_url: str, org_name: str, manifest: SuppliersManifest) -> dict[str, Any]:
    """`{expected, actual}` pairs in the shape `_require_matching_import` checks."""
    _require_test_tenant(org_name)
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            org_id = _org_id(conn, org_name)
            present = {
                str(name).casefold()
                for (name,) in conn.execute(text("SELECT name FROM suppliers WHERE org_id = :org"), {"org": org_id})
            }
            uncovered = conn.execute(
                text(
                    "SELECT count(DISTINCT lower(trim(i.supplier))) FROM inventory_items i WHERE i.org_id = :org "
                    "AND trim(coalesce(i.supplier, '')) <> '' AND NOT EXISTS (SELECT 1 FROM suppliers s "
                    "WHERE s.org_id = i.org_id AND lower(s.name) = lower(trim(i.supplier)))"
                ),
                {"org": org_id},
            ).scalar_one()
            undated = conn.execute(
                text(
                    f"SELECT count(*) FROM suppliers s JOIN ({_FIRST_PURCHASE}) f ON f.id = s.id "
                    "WHERE s.created_at <> f.min"
                ),
                {"org": org_id},
            ).scalar_one()
    finally:
        engine.dispose()
    wanted = {str(supplier["name"]).casefold() for supplier in manifest.suppliers}
    return {
        "suppliers": {"expected": len(wanted), "actual": len(wanted & present)},
        "inventory_suppliers_without_a_record": {"expected": 0, "actual": uncovered},
        "supplier_creation_dates": {"expected": 0, "actual": undated},
    }


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("validate", "apply", "verify"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_SUPPLIERS_MANIFEST)
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--org-name", default=wm.WHISTLEBIRD_ORG_NAME)
    parser.add_argument("--base-url", default="https://localhost:8005")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verification (self-signed local certs).")
    parser.add_argument("--admin-email", default=wm.DEFAULT_ADMIN_EMAIL)
    parser.add_argument("--admin-password-env", default="WHISTLEBIRD_ADMIN_PASSWORD")
    args = parser.parse_args(argv)
    if args.command != "validate" and not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        manifest = load_suppliers_manifest(args.manifest)
        if args.command == "validate":
            print(f"ok: {len(manifest.suppliers)} suppliers")
            return 0
        report: dict[str, Any] = {}
        if args.command == "apply":
            import whistlebird_replay as replay  # noqa: PLC0415 (it imports this module)

            password = os.environ.get(args.admin_password_env) or wm._keepass_password(
                wm.WHISTLEBIRD_ADMIN_KEEPASS_ENTRY
            )
            client = replay.ReplayClient(args.base_url, verify_tls=not args.insecure)
            client.login(args.admin_email, password)
            report["replay"] = replay_suppliers(client, manifest)
            report["dated"] = date_suppliers(args.target_url, args.org_name)
        report["verification"] = verify_suppliers(args.target_url, args.org_name, manifest)
        print(json.dumps(report, indent=2, default=str))
        pairs = report["verification"].values()
        return 0 if all(pair["expected"] == pair["actual"] for pair in pairs) else 1
    except (SuppliersManifestError, SuppliersReplayError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
