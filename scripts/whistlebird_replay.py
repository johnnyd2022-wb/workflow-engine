"""Replay whistlebird_test's curated history through the real application API.

Every event from `whistlebird_replay_timeline.build_timeline()` is issued as a real HTTP
request against a running instance of this app -- the same route, auth, validation, and
business logic (including real inventory consumption) a browser would hit. No timestamp
override exists anywhere in this script or the API it calls: everything lands with
`created_at`/`completed_at` at "now" (replay time), by design, exactly like a real user's
action would. `scripts/whistlebird_replay_correct_timestamps.py` is the only place real
historical dates get applied, as a separate pass, after this script finishes.

No `date_confidence`/`timestamp_policy`/"derived" language is written into any request
this script sends -- the app receiving this data has no way to know (and does not need
to know) which of its rows came from a clean receipt versus an inferred one. That
distinction lives only in the curation docs (`docs/whistlebird-import-decisions.md`) and
the JSON manifests, never in the loaded data itself.

Usage:
    uv run python scripts/whistlebird_replay.py \\
        --base-url http://localhost:8001 \\
        --legacy-url postgresql://wb_admin:whistlebird@localhost:5401/whistlebird_inventory \\
        --target-url postgresql://workflow_rw:...@localhost:8401/workflow-engine-test \\
        --admin-email whistlebird_test_admin@whistlebird.test \\
        --admin-password-env WHISTLEBIRD_TEST_ADMIN_PASSWORD

Resumable: before issuing any event, the script checks the target database directly
(read-only) for a row already carrying that event's marker, and skips it. Re-running
after a partial run (crash, quota interruption, a rejected request you've now fixed)
picks up where it left off rather than double-creating anything.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import requests
import urllib3
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_migration as wm  # noqa: E402
from whistlebird_replay_timeline import ReplayEvent, build_timeline  # noqa: E402

CSRF_META_RE = re.compile(r'<meta\s+name="csrf-token"\s+content="([^"]+)"')


class ReplayRejectedError(RuntimeError):
    """A real API call was rejected. Stop -- don't paper over it."""


class ReplayClient:
    def __init__(self, base_url: str, verify_tls: bool = True):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = verify_tls
        if not verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._csrf_token: str | None = None

    def login(self, email: str, password: str) -> None:
        response = self.session.post(
            f"{self.base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
        if response.status_code != 200 or response.json().get("requires_2fa"):
            raise ReplayRejectedError(f"login failed or requires 2FA: {response.status_code} {response.text[:500]}")
        page = self.session.get(f"{self.base_url}/", timeout=30)
        match = CSRF_META_RE.search(page.text)
        if not match:
            raise ReplayRejectedError("could not find csrf-token meta tag on authenticated page")
        self._csrf_token = match.group(1)

    def _headers(self) -> dict[str, str]:
        assert self._csrf_token, "login() must run before any mutating call"
        return {"X-CSRFToken": self._csrf_token}

    def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(f"{self.base_url}{path}", json=json_body, headers=self._headers(), timeout=60)
        if response.status_code not in (200, 201):
            raise ReplayRejectedError(f"POST {path} -> {response.status_code}: {response.text[:1000]}")
        return response.json()

    def get(self, path: str) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}{path}", timeout=60)
        if response.status_code != 200:
            raise ReplayRejectedError(f"GET {path} -> {response.status_code}: {response.text[:1000]}")
        return response.json()


class MarkerStore:
    """Read-only lookups against the target DB to make the replay idempotent/resumable.

    `execution_data->>'batch_ref'` is only stamped once an execution's FIRST step
    completes (see `_execute_complete_step`) -- `POST /api/core/executions` itself has
    no marker field. `_created_this_run` closes that gap within a single process by
    caching the id `_execute_create_execution` gets back from the API directly, so nothing
    tries to create the same execution twice in one run. Across separate runs, a crash
    landing exactly between "execution created" and "its first step completed" could in
    principle leave one orphaned, marker-less execution with zero completed steps behind;
    accepted as a known, narrow, low-harm gap (documented in whistlebird-replay-plan.md)
    rather than adding more machinery to close a one-request-wide window.
    """

    def __init__(self, target_url: str, org_id: UUID):
        self._engine = create_engine(target_url)
        self.org_id = org_id
        self._created_this_run: dict[str, str] = {}

    def note_created_execution(self, marker: str, execution_id: str) -> None:
        self._created_this_run[marker] = execution_id

    def existing_inventory_item_id(self, marker: str) -> UUID | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM inventory_items "
                    "WHERE org_id = :org_id AND extra_data->>'import_ref' = :marker LIMIT 1"
                ),
                {"org_id": str(self.org_id), "marker": marker},
            ).first()
            return row[0] if row else None

    def existing_execution_id(self, marker: str) -> str | None:
        if marker in self._created_this_run:
            return self._created_this_run[marker]
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT DISTINCT execution_id FROM execution_steps "
                    "WHERE org_id = :org_id AND execution_data->>'batch_ref' = :marker LIMIT 1"
                ),
                {"org_id": str(self.org_id), "marker": marker},
            ).first()
            return str(row[0]) if row else None

    def execution_steps(self, execution_id: UUID) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, step_number, status FROM execution_steps "
                    "WHERE org_id = :org_id AND execution_id = :execution_id ORDER BY step_number"
                ),
                {"org_id": str(self.org_id), "execution_id": str(execution_id)},
            ).fetchall()
            return [{"id": r[0], "step_number": r[1], "status": r[2]} for r in rows]

    def step_already_completed(self, execution_id: UUID, step_number: int) -> bool:
        for step in self.execution_steps(execution_id):
            if step["step_number"] == step_number:
                return step["status"] == "completed"
        return False

    def existing_compliance_record(self, marker: str) -> bool:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM compliance_records "
                    "WHERE org_id = :org_id AND details->>'import_ref' = :marker LIMIT 1"
                ),
                {"org_id": str(self.org_id), "marker": marker},
            ).first()
            return row is not None

    def process_id_for_workflow(self, workflow_name: str) -> UUID:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM processes WHERE org_id = :org_id AND name = :name LIMIT 1"),
                {"org_id": str(self.org_id), "name": workflow_name},
            ).first()
            if not row:
                raise ReplayRejectedError(f"no process named {workflow_name!r} exists for org {self.org_id}")
            return row[0]

    def compliant_profile_enabled(self) -> bool:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT enabled FROM compliant_profiles "
                    "WHERE org_id = :org_id AND framework_slug = 'customs-alcohol' LIMIT 1"
                ),
                {"org_id": str(self.org_id)},
            ).first()
            return bool(row and row[0])


def _execute_purchase(client: ReplayClient, store: MarkerStore, event: ReplayEvent) -> bool:
    record = event.payload["record"]
    marker = event.payload["marker"]
    if store.existing_inventory_item_id(marker):
        return False
    name = record.get("name") or record.get("ingredient")
    quantity = record.get("quantity")
    unit = record.get("unit")
    supplier = record.get("supplier")
    purchase_date = record["date"] if isinstance(record["date"], str) else record["date"].isoformat()
    expiry_date = record.get("expiry_date")
    if hasattr(expiry_date, "isoformat"):
        expiry_date = expiry_date.isoformat()
    supplier_batch_number = record.get("supplier_batch_number")
    extra_data = dict(record.get("extra_data") or {})
    code = record.get("code")
    if code:
        extra_data.setdefault("ingredient_code", code)
    client.post(
        "/api/core/inventory",
        {
            "name": name,
            "quantity": str(quantity),
            "unit": unit,
            "inventory_type": "raw_material",
            "supplier": supplier,
            "purchase_date": purchase_date,
            "expiry_date": expiry_date,
            "supplier_batch_number": supplier_batch_number,
            "source_method": "manual",
            "metadata": {**extra_data, "import_ref": marker},
        },
    )
    return True


def _ingredient_inputs_for_step(
    store: MarkerStore, known_input_quantities: dict[str, tuple[str, str]]
) -> list[dict[str, Any]]:
    """Consume exactly the codes with a known per-batch amount (the inferred raw-material
    tier). Legacy-evidence and clean-tier codes are ordering-only, per the "real
    constraint that changes scope" decision in docs/whistlebird-replay-plan.md -- they
    are never fabricated into a consumption quantity here.
    """
    if not known_input_quantities:
        return []
    inputs = []
    with store._engine.connect() as conn:
        for code, (quantity, unit) in known_input_quantities.items():
            row = conn.execute(
                text(
                    "SELECT id, name FROM inventory_items "
                    "WHERE org_id = :org_id AND extra_data->>'ingredient_code' = :code LIMIT 1"
                ),
                {"org_id": str(store.org_id), "code": code},
            ).first()
            if row is None:
                raise ReplayRejectedError(f"no inventory item carries ingredient_code={code!r} yet")
            inputs.append({"inventory_item_id": str(row[0]), "name": row[1], "quantity": quantity, "unit": unit})
    return inputs


def _produced_item_for_step(store: MarkerStore, execution_step_id: UUID, name: str) -> dict[str, Any] | None:
    with store._engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, name, unit, quantity FROM inventory_items "
                "WHERE org_id = :org_id AND source_execution_step_id = :step_id AND name = :name LIMIT 1"
            ),
            {"org_id": str(store.org_id), "step_id": str(execution_step_id), "name": name},
        ).first()
        if row is None:
            return None
        return {"id": row[0], "name": row[1], "unit": row[2], "quantity": row[3]}


def _consume_whole_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "inventory_item_id": str(item["id"]),
        "name": item["name"],
        "quantity": str(item["quantity"]),
        "unit": item["unit"],
    }


def _vat_batch_volume_l(batch: wm.ProductionBatch) -> str | None:
    """Best-available real number, never a fabricated one. See the replay plan's
    "VAT-batch output volume" note for the fallback order and why."""
    if batch.vat_volume_l is not None and batch.vat_volume_l > 0:
        return str(batch.vat_volume_l)
    if batch.bottlings:
        size_ml = batch.bottlings[0].get("bottle_size_ml")
        if size_ml:


            total_bottles = sum((Decimal(str(b["bottles"])) for b in batch.bottlings), Decimal("0"))
            computed = total_bottles * Decimal(str(size_ml)) / Decimal("1000")
            if computed > 0:
                return str(computed)
    return None  # caller falls back to the documented last-resort placeholder


def _execute_create_execution(client: ReplayClient, store: MarkerStore, event: ReplayEvent) -> bool:
    batch = event.payload.get("batch")
    trial = event.payload.get("trial")
    marker = batch.marker if batch else trial.marker
    if store.existing_execution_id(marker):
        return False
    workflow_name = batch.workflow_name if batch else trial.workflow_name
    process_id = store.process_id_for_workflow(workflow_name)
    response = client.post("/api/core/executions", {"process_id": str(process_id)})
    store.note_created_execution(marker, response["id"])
    return True


def _execute_complete_step(client: ReplayClient, store: MarkerStore, event: ReplayEvent) -> bool:
    batch = event.payload.get("batch")
    trial = event.payload.get("trial")
    marker = batch.marker if batch else trial.marker
    step_key = event.payload["step_key"]
    step_index = event.payload["step_index"]
    step_number = step_index + 1

    execution_id = store.existing_execution_id(marker)
    if execution_id is None:
        raise ReplayRejectedError(f"execution for {marker!r} not found -- create_execution event must run first")
    if store.step_already_completed(execution_id, step_number):
        return False

    steps = store.execution_steps(execution_id)
    step_row = next((s for s in steps if s["step_number"] == step_number), None)
    if step_row is None:
        raise ReplayRejectedError(f"{marker} has no step_number={step_number}")

    actual_inputs: list[dict[str, Any]] = []
    actual_outputs: list[dict[str, Any]] = []

    if batch is not None:
        is_rosella = batch.product_line == "rosella"
        produces_vat = (step_key == "rhubarb_maceration") if is_rosella else (step_key == "aging")
        produces_bottles = step_key == "bottling"

        if step_key in ("maceration", "rhubarb_maceration"):
            actual_inputs.extend(
                _ingredient_inputs_for_step(store, event.payload.get("known_input_quantities", {}))
            )
        if step_key == "rhubarb_maceration" and batch.base_vat is not None:
            base_marker = f"{batch.product_line}-vat{batch.base_vat}"
            base_execution_id = store.existing_execution_id(base_marker)
            if base_execution_id is None:
                raise ReplayRejectedError(f"{marker} needs base VAT{batch.base_vat}, which was never loaded")
            base_steps = store.execution_steps(base_execution_id)
            base_vat_item = None
            for s in base_steps:
                candidate = _produced_item_for_step(store, s["id"], "VAT batch")
                if candidate:
                    base_vat_item = candidate
            if base_vat_item is None:
                raise ReplayRejectedError(f"base VAT{batch.base_vat}'s VAT batch item was never produced")
            actual_inputs.append(_consume_whole_item(base_vat_item))

        if produces_vat:
            volume = _vat_batch_volume_l(batch) or "1"
            actual_outputs.append(
                {"name": "VAT batch", "quantity": volume, "unit": "L"}
            )

        if produces_bottles:
            vat_item = None
            for s in steps:
                if s["step_number"] < step_number:
                    candidate = _produced_item_for_step(store, s["id"], "VAT batch")
                    if candidate:
                        vat_item = candidate
            if vat_item is not None:
                actual_inputs.append(_consume_whole_item(vat_item))
            if batch.bottlings:
                total_bottles = sum((Decimal(str(b["bottles"])) for b in batch.bottlings), Decimal("0"))
                if total_bottles > 0:
                    actual_outputs.append(
                        {"name": "Bottled product", "quantity": str(total_bottles), "unit": "units"}
                    )

        if step_key == "labelling":
            bottled_item = None
            for s in steps:
                if s["step_number"] < step_number:
                    candidate = _produced_item_for_step(store, s["id"], "Bottled product")
                    if candidate:
                        bottled_item = candidate
            if bottled_item is not None:
                actual_inputs.append(_consume_whole_item(bottled_item))

    elif trial is not None and step_key == "library_stock" and trial.library_ml:
        actual_outputs.append({"name": "Library stock", "quantity": str(trial.library_ml), "unit": "mL"})

    client.post(
        f"/api/core/executions/{execution_id}/steps/{step_row['id']}/complete",
        {
            "actual_inputs": actual_inputs,
            "actual_outputs": actual_outputs,
            "execution_data": {
                "batch_ref": marker,
                "batch_label": (batch.batch_label if batch else trial.label),
                "global_vat": (batch.global_vat if batch else None),
            },
        },
    )
    return True


def _execute_customs(client: ReplayClient, store: MarkerStore, event: ReplayEvent) -> bool:
    row = event.payload["row"]
    marker = f"customs-{row['id']}"
    if store.existing_compliance_record(marker):
        return False
    if not store.compliant_profile_enabled():
        raise ReplayRejectedError("customs-alcohol compliant profile is not enabled for this org yet")
    client.post(
        "/api/compliant/records",
        {
            "framework_slug": "customs-alcohol",
            "control_id": "period-lodgement",
            "record_type": "lodgement",
            "status": "complete",
            "title": f"Customs lodgement {row['date']}",
            "period_start": row["date_period"],
            "period_end": row["date_period"],
            "measured_value": str(row["lal"]) if row.get("lal") is not None else None,
            "details": {
                "import_ref": marker,
                "lodged_volume": str(row.get("lodged_volume")),
                "lodged_abv": str(row.get("lodged_abv")),
                "bottles": str(row.get("bottles")),
            },
        },
    )
    return True


DISPATCH = {
    "create_inventory_item": _execute_purchase,
    "create_execution": _execute_create_execution,
    "complete_step": _execute_complete_step,
    "create_customs_lodgement": _execute_customs,
}


def run_replay(
    base_url: str,
    legacy_url: str,
    target_url: str,
    production_manifest_path: Path,
    admin_email: str,
    admin_password: str,
    org_name: str,
    verify_tls: bool = True,
    limit: int | None = None,
) -> dict[str, int]:
    events = build_timeline(legacy_url, production_manifest_path)
    if limit is not None:
        events = events[:limit]

    engine = create_engine(target_url)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM organisations WHERE name = :name"), {"name": org_name}).first()
        if not row:
            raise ReplayRejectedError(f"org {org_name!r} does not exist -- run --ensure-test-tenant first")
        org_id = row[0]
    engine.dispose()

    store = MarkerStore(target_url, org_id)
    client = ReplayClient(base_url, verify_tls=verify_tls)
    client.login(admin_email, admin_password)

    counts = {"issued": 0, "skipped": 0, "total": len(events)}
    for index, event in enumerate(events):
        handler = DISPATCH[event.event_type]
        try:
            issued = handler(client, store, event)
        except ReplayRejectedError:
            print(f"[{index + 1}/{len(events)}] REJECTED at {event.event_id} ({event.real_date})", file=sys.stderr)
            raise
        if not issued:
            counts["skipped"] += 1
        else:
            counts["issued"] += 1
        if (index + 1) % 25 == 0:
            print(f"[{index + 1}/{len(events)}] {event.event_id} ({event.real_date})")
    return counts


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://localhost:8001")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verification (self-signed local certs).")
    parser.add_argument("--legacy-url", default=os.environ.get("WB_LEGACY_DATABASE_URL"))
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--production-manifest", type=Path, default=wm.DEFAULT_PRODUCTION_MANIFEST)
    parser.add_argument("--admin-email", default=wm.DEFAULT_TEST_ADMIN_EMAIL)
    parser.add_argument("--admin-password-env", default="WHISTLEBIRD_TEST_ADMIN_PASSWORD")
    parser.add_argument("--org-name", default=wm.RESET_ORG_NAME)
    parser.add_argument("--limit", type=int, default=None, help="Only issue the first N events (smoke-testing).")
    args = parser.parse_args()
    if not args.legacy_url or not args.target_url:
        parser.error("--legacy-url and --target-url are required")
    args.admin_password = os.environ.get(args.admin_password_env)
    if not args.admin_password:
        parser.error(f"{args.admin_password_env} must be set")
    return args


def main() -> int:
    args = _arguments()
    result = run_replay(
        args.base_url,
        args.legacy_url,
        args.target_url,
        args.production_manifest,
        args.admin_email,
        args.admin_password,
        args.org_name,
        verify_tls=not args.insecure,
        limit=args.limit,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
