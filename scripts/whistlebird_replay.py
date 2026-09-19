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
import whistlebird_crm as crm  # noqa: E402
import whistlebird_legacy as legacy  # noqa: E402
import whistlebird_migration as wm  # noqa: E402
import whistlebird_np3 as np3  # noqa: E402
from whistlebird_replay_timeline import ReplayEvent, build_timeline  # noqa: E402

CSRF_META_RE = re.compile(r'<meta\s+name="csrf-token"\s+content="([^"]+)"')


class ReplayRejectedError(RuntimeError):
    """A real API call was rejected. Stop -- don't paper over it."""


_MATERIAL_NAME_ALIASES = {
    # The legacy purchase register uses "Macedonia" while the fixed production recipe
    # uses "Macedonian".  They are the same botanical, and the alias keeps reset/replay
    # allocation deterministic without rewriting the source receipt's display name.
    "juniper berries (macedonia)": "juniper berries (macedonian)",
}

# Recipe input names are the tenant's canonical display names. Legacy receipts use
# lower-case source labels while the curated manifest uses these names; inventory must
# not create a second botanical merely because source capitalization differs.
_CANONICAL_MATERIAL_DISPLAY_NAMES = {
    " ".join(entry["name"].lower().split()): entry["name"]
    for recipe in (wm._WILDFLOWER_MACERATION_INPUTS, wm._SOLSTICE_MACERATION_INPUTS)
    for entry in recipe
}


def _canonical_material_name(name: str) -> str:
    normalized = " ".join(name.lower().split())
    return _MATERIAL_NAME_ALIASES.get(normalized, normalized)


def _canonical_material_display_name(name: str) -> str:
    """Return the stable inventory label for a recipe botanical receipt."""
    return _CANONICAL_MATERIAL_DISPLAY_NAMES.get(_canonical_material_name(name), name)


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
        # "/" is the public marketing page and carries no CSRF meta tag; the SPA shell
        # (with it) only renders behind auth, at /core/dashboard.
        page = self.session.get(f"{self.base_url}/core/dashboard", timeout=30)
        match = CSRF_META_RE.search(page.text)
        if not match:
            raise ReplayRejectedError("could not find csrf-token meta tag on authenticated page")
        self._csrf_token = match.group(1)

    def _headers(self) -> dict[str, str]:
        assert self._csrf_token, "login() must run before any mutating call"
        # Flask-WTF's CSRF protection requires a same-origin Referer on HTTPS requests
        # in addition to the token; a script has no natural referring page, so supply
        # one explicitly, matching what a real same-origin browser request would send.
        return {"X-CSRFToken": self._csrf_token, "Referer": f"{self.base_url}/core/dashboard"}

    def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(f"{self.base_url}{path}", json=json_body, headers=self._headers(), timeout=60)
        if response.status_code not in (200, 201):
            raise ReplayRejectedError(f"POST {path} -> {response.status_code}: {response.text[:1000]}")
        return response.json()

    def put(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.put(f"{self.base_url}{path}", json=json_body, headers=self._headers(), timeout=60)
        if response.status_code not in (200, 201):
            raise ReplayRejectedError(f"PUT {path} -> {response.status_code}: {response.text[:1000]}")
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

    def raw_material_for_marker(self, marker: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, name, unit, quantity FROM inventory_items "
                    "WHERE org_id = :org_id AND inventory_type = 'raw_material' "
                    "AND extra_data->>'import_ref' = :marker LIMIT 1"
                ),
                {"org_id": str(self.org_id), "marker": marker},
            ).first()
            return {"id": row[0], "name": row[1], "unit": row[2], "quantity": row[3]} if row else None

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
        # execution_steps.status is stored as the Python enum's member NAME (upper-case,
        # e.g. "COMPLETED"), not its lower-case .value the app compares against
        # internally -- a raw SQL read sees the former, so normalise case here.
        for step in self.execution_steps(execution_id):
            if step["step_number"] == step_number:
                return step["status"].lower() == "completed"
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
                    "SELECT enabled FROM compliance_profiles "
                    "WHERE org_id = :org_id AND industry_module = 'nz_alcohol' LIMIT 1"
                ),
                {"org_id": str(self.org_id)},
            ).first()
            return bool(row and row[0])

    def execution_id_for_global_vat(self, global_vat: int) -> str | None:
        """Find an execution by its global_vat marker regardless of product line -- a
        Rosella conversion's base VAT was distilled as Solstice, not Rosella, so
        `f"{batch.product_line}-vat{base_vat}"` (the Rosella record's OWN product line)
        is the wrong marker to guess; this looks the base execution up by its own
        recorded global_vat instead of assuming a product line at all."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT DISTINCT execution_id FROM execution_steps "
                    "WHERE org_id = :org_id AND (execution_data->>'global_vat')::int = :vat LIMIT 1"
                ),
                {"org_id": str(self.org_id), "vat": global_vat},
            ).first()
            return str(row[0]) if row else None

    def consume_available_raw_material(self, name: str, quantity_needed: Decimal, unit: str) -> list[dict[str, Any]]:
        """Greedily consume canonical-name-matched raw material FIFO lots.

        Receipt display names remain faithful to their sources, while allocation ignores
        harmless spelling/case variants such as ``Macedonia``/``Macedonian``.  This makes
        a destroy-and-replay run allocate the same historical recipe quantities every time.
        """
        consumed, remaining = self.consume_available_raw_material_up_to(name, quantity_needed, unit)
        if remaining > 0:
            raise ReplayRejectedError(
                f"not enough {name!r} stock to consume {quantity_needed} {unit} (short by {remaining} {unit})"
            )
        return consumed

    def consume_available_raw_material_up_to(
        self, name: str, quantity_needed: Decimal, unit: str
    ) -> tuple[list[dict[str, Any]], Decimal]:
        """Return canonical FIFO consumption plus any source-evidenced shortfall."""
        remaining = Decimal(str(quantity_needed))
        consumed: list[dict[str, Any]] = []
        canonical_name = _canonical_material_name(name)
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, name, unit, quantity FROM inventory_items "
                    "WHERE org_id = :org_id AND inventory_type = 'raw_material' "
                    "AND quantity > 0 ORDER BY purchase_date ASC NULLS LAST, created_at ASC"
                ),
                {"org_id": str(self.org_id)},
            ).fetchall()
        for row in rows:
            if remaining <= 0:
                break
            if row[2] != unit or _canonical_material_name(row[1]) != canonical_name:
                continue
            available = Decimal(str(row[3]))
            take = min(available, remaining)
            if take <= 0:
                continue
            consumed.append({"inventory_item_id": str(row[0]), "name": row[1], "quantity": str(take), "unit": unit})
            remaining -= take
        return consumed, remaining

    def consume_marked_raw_material(self, marker: str, quantity_needed: Decimal, unit: str) -> list[dict[str, Any]]:
        item = self.raw_material_for_marker(marker)
        if item is None:
            raise ReplayRejectedError(f"no raw-material item carries import_ref={marker!r} yet")
        if item["unit"] != unit or Decimal(str(item["quantity"])) < quantity_needed:
            raise ReplayRejectedError(f"raw-material item {marker!r} cannot supply {quantity_needed} {unit}")
        return [
            {
                "inventory_item_id": str(item["id"]),
                "name": item["name"],
                "quantity": str(quantity_needed),
                "unit": unit,
            }
        ]

    def most_recently_created_execution_id(self) -> str | None:
        """The execution this replay itself created last, so far.

        Timestamps only reflect real historical dates after
        whistlebird_replay_correct_timestamps.py's later pass -- during replay every row's
        created_at is "now" -- so this can't filter by a real-history cutoff date. It
        doesn't need to: replay processes every event in real chronological order, so
        whatever execution was inserted most recently (by insertion order, i.e. this
        row's own created_at during THIS run) is, by construction, the one that happened
        last in real history among everything loaded so far. Used as a customs
        lodgement's required Core source_ref -- the legacy customs data carries no
        per-lodgement link to a specific batch, so this is a real, existing link to
        whatever production activity preceded that lodgement, not a fabricated one.
        """
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM executions WHERE org_id = :org_id ORDER BY created_at DESC LIMIT 1"),
                {"org_id": str(self.org_id)},
            ).first()
            return str(row[0]) if row else None


def _execute_purchase(client: ReplayClient, store: MarkerStore, event: ReplayEvent) -> bool:
    record = event.payload["record"]
    marker = event.payload["marker"]
    if store.existing_inventory_item_id(marker):
        return False
    source_name = record.get("name") or record.get("ingredient")
    name = _canonical_material_display_name(source_name)
    # Context-resolved records keep ``quantity`` as the exact amount consumed by
    # their linked VAT.  When a physical supplier lot has subsequently been
    # identified, ``purchase_quantity`` records the actual receipt without
    # changing that historical consumption.
    quantity = record.get("purchase_quantity", record.get("quantity"))
    unit = record.get("unit")
    supplier = record.get("supplier")
    purchase_date = record["date"] if isinstance(record["date"], str) else record["date"].isoformat()
    expiry_date = record.get("expiry_date")
    if hasattr(expiry_date, "isoformat"):
        expiry_date = expiry_date.isoformat()
    supplier_batch_number = record.get("supplier_batch_number")
    extra_data = dict(record.get("extra_data") or {})
    if source_name and source_name != name:
        extra_data.setdefault("source_material_name", source_name)
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


def _recipe_botanical_inputs(batch: wm.ProductionBatch) -> list[tuple[str, Decimal, str]]:
    recipe = wm._WILDFLOWER_MACERATION_INPUTS if batch.product_line == "wildflower" else wm._SOLSTICE_MACERATION_INPUTS
    return [
        (entry["name"], Decimal(entry["quantity"]), entry["unit"])
        for entry in recipe
        if entry["requires_inventory_selection"] and entry["name"] != "Neutral grain spirit"
    ]


def _recipe_fallback_inputs(
    store: MarkerStore, batch: wm.ProductionBatch, precise_inputs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Use the fixed VAT recipe for botanical amounts not precisely source-linked.

    Curated inferred purchases remain pinned through ``ingredient_code``.  For earlier
    source receipts that only establish availability, consume the residual recipe demand
    from canonical-name FIFO lots instead of leaving every historical receipt on hand.
    """
    precise_by_material: dict[tuple[str, str], Decimal] = {}
    for item in precise_inputs:
        key = (_canonical_material_name(item["name"]), item["unit"])
        precise_by_material[key] = precise_by_material.get(key, Decimal("0")) + Decimal(str(item["quantity"]))

    fallback: list[dict[str, Any]] = []
    for name, recipe_quantity, unit in _recipe_botanical_inputs(batch):
        known_quantity = precise_by_material.get((_canonical_material_name(name), unit), Decimal("0"))
        if known_quantity > recipe_quantity:
            raise ReplayRejectedError(
                f"precisely linked {name!r} quantity {known_quantity} exceeds recipe quantity {recipe_quantity}"
            )
        remaining = recipe_quantity - known_quantity
        if remaining > 0:
            allocated, shortfall = store.consume_available_raw_material_up_to(name, remaining, unit)
            fallback.extend(allocated)
            if shortfall > 0:
                # A recipe predates every matching receipt in the source database.  Keep
                # its documented material use without falsely tying it to a later lot.
                fallback.append({"name": name, "quantity": str(shortfall), "unit": unit})
    return fallback


def _produced_item_for_step(store: MarkerStore, execution_step_id: UUID, name: str) -> dict[str, Any] | None:
    items = _produced_items_for_step(store, execution_step_id, name)
    return items[0] if items else None


def _produced_items_for_step(store: MarkerStore, execution_step_id: UUID, name: str) -> list[dict[str, Any]]:
    """Return every item a step produced with this name.

    Bottling can straddle a 500-label-roll boundary and therefore creates two
    separately batch-numbered ``Bottled product`` items.  Labelling must consume both,
    not silently select the first one and leave the rest stranded in WIP.
    """
    with store._engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, name, unit, quantity FROM inventory_items "
                "WHERE org_id = :org_id AND source_execution_step_id = :step_id AND name = :name "
                "ORDER BY created_at, id"
            ),
            {"org_id": str(store.org_id), "step_id": str(execution_step_id), "name": name},
        ).fetchall()
        return [{"id": row[0], "name": row[1], "unit": row[2], "quantity": row[3]} for row in rows]


def _consume_whole_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "inventory_item_id": str(item["id"]),
        "name": item["name"],
        "quantity": str(item["quantity"]),
        "unit": item["unit"],
    }


def _consume_item_quantity(item: dict[str, Any], quantity: Decimal) -> dict[str, Any]:
    """Record a source-evidenced partial draw without consuming the VAT remainder."""
    if quantity <= 0 or Decimal(str(item["quantity"])) < quantity:
        raise ReplayRejectedError(
            f"inventory item {item['id']} cannot supply {quantity} {item['unit']} (available {item['quantity']})"
        )
    return {
        "inventory_item_id": str(item["id"]),
        "name": item["name"],
        "quantity": str(quantity),
        "unit": item["unit"],
    }


def _batch_number_prompt_value(label_batches: list[tuple[int, str]] | None) -> str:
    """Render the recorded label-batch allocation for the required step prompt.

    Each individual output continues to receive its own integer ``batch_number``. A
    single execution can straddle a physical 500-label roll, however, so the step-level
    text prompt records all affected numbers. An unbottled VAT has no number to invent;
    retain that source fact explicitly while satisfying the workflow's required prompt.
    """
    if label_batches:
        return ", ".join(str(number) for number, _quantity in label_batches)
    return "Not applicable — no bottled output recorded"


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


def _aging_output_name(batch: wm.ProductionBatch) -> str:
    """Name aging WIP according to its documented next production use."""
    if batch.product_line == "rosella" or batch.extra_data.get("diverted_to"):
        return "VAT batch"
    return "Aged Gin"


def _execute_create_execution(client: ReplayClient, store: MarkerStore, event: ReplayEvent) -> bool:
    batch = event.payload.get("batch")
    trial = event.payload.get("trial")
    green_gold = event.payload.get("green_gold")
    record = batch or trial or green_gold
    if record is None:
        raise ReplayRejectedError(f"{event.event_id} has no replay record")
    marker = record.marker
    if store.existing_execution_id(marker):
        return False
    workflow_name = record.workflow_name
    process_id = store.process_id_for_workflow(workflow_name)
    response = client.post("/api/core/executions", {"process_id": str(process_id)})
    store.note_created_execution(marker, response["id"])
    return True


def _execute_complete_step(client: ReplayClient, store: MarkerStore, event: ReplayEvent) -> bool:
    batch = event.payload.get("batch")
    trial = event.payload.get("trial")
    green_gold = event.payload.get("green_gold")
    record = batch or trial or green_gold
    if record is None:
        raise ReplayRejectedError(f"{event.event_id} has no replay record")
    marker = record.marker
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
            precise_inputs = _ingredient_inputs_for_step(store, event.payload.get("known_input_quantities", {}))
            actual_inputs.extend(precise_inputs)
            if not is_rosella:
                actual_inputs.extend(_recipe_fallback_inputs(store, batch, precise_inputs))

        # Neutral grain spirit (real inventory draw) and water/foraged botanicals ("other
        # materials" -- no inventory_item_id, matching the UI's "Other materials" input
        # concept: real usage the app records without tracking as purchased stock).
        legacy_ngs_quantity_l = event.payload.get("legacy_ngs_quantity_l")
        if legacy_ngs_quantity_l:
            actual_inputs.extend(
                store.consume_available_raw_material("Neutral grain spirit", Decimal(legacy_ngs_quantity_l), "L")
            )
        dedicated_ngs_quantity_l = event.payload.get("dedicated_ngs_quantity_l")
        if dedicated_ngs_quantity_l:
            actual_inputs.extend(
                store.consume_marked_raw_material(
                    event.payload["dedicated_ngs_marker"], Decimal(dedicated_ngs_quantity_l), "L"
                )
            )
        for other_input in event.payload.get("other_material_inputs", []):
            actual_inputs.append(dict(other_input))

        if step_key == "distilling":
            for step in steps:
                if step["step_number"] < step_number:
                    maceration_item = _produced_item_for_step(store, step["id"], wm._MACERATION_OUTPUT_NAME)
                    if maceration_item:
                        actual_inputs.append(_consume_whole_item(maceration_item))

        if step_key == "aging" and not is_rosella:
            for step in steps:
                if step["step_number"] < step_number:
                    concentrate_item = _produced_item_for_step(store, step["id"], wm._DISTILLATE_OUTPUT_NAME)
                    if concentrate_item:
                        actual_inputs.append(_consume_whole_item(concentrate_item))

        if step_key == "rhubarb_maceration" and batch.base_vat is not None:
            base_execution_id = store.execution_id_for_global_vat(batch.base_vat)
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

        if step_key == "maceration":
            actual_outputs.append(
                {
                    "name": wm._MACERATION_OUTPUT_NAME,
                    "quantity": wm._MACERATION_OUTPUT_QUANTITY,
                    "unit": wm._MACERATION_OUTPUT_UNIT,
                }
            )

        if step_key == "distilling":
            actual_outputs.append(
                {
                    "name": wm._DISTILLATE_OUTPUT_NAME,
                    "quantity": wm._DISTILLATE_OUTPUT_QUANTITY,
                    "unit": wm._DISTILLATE_OUTPUT_UNIT,
                }
            )

        if produces_vat:
            volume = _vat_batch_volume_l(batch) or "1"
            output_name = _aging_output_name(batch)
            actual_outputs.append({"name": output_name, "quantity": volume, "unit": "L"})

        if produces_bottles:
            vat_item = None
            for s in steps:
                if s["step_number"] < step_number:
                    output_name = _aging_output_name(batch)
                    candidate = _produced_item_for_step(store, s["id"], output_name)
                    if candidate:
                        vat_item = candidate
            if vat_item is not None:
                actual_inputs.append(_consume_whole_item(vat_item))
            if batch.bottlings:
                total_bottles = sum((Decimal(str(b["bottles"])) for b in batch.bottlings), Decimal("0"))
                if total_bottles > 0:
                    # The same physical label-batch allocation must follow bottles
                    # through both Bottling and Labelling.  Splitting here also keeps
                    # a run crossing a 500-label boundary from becoming stranded WIP.
                    label_batches = event.payload.get("label_batches") or [(None, str(total_bottles))]
                    for batch_number, quantity in label_batches:
                        output = {"name": "Bottled product", "quantity": str(quantity), "unit": "units"}
                        if batch_number is not None:
                            output["batch_number"] = batch_number
                        actual_outputs.append(output)

        if step_key == "labelling":
            bottled_items: list[dict[str, Any]] = []
            for s in steps:
                if s["step_number"] < step_number:
                    bottled_items.extend(_produced_items_for_step(store, s["id"], "Bottled product"))
            if bottled_items:
                actual_inputs.extend(_consume_whole_item(item) for item in bottled_items)
                # Labelling is the terminal step: what goes on-hand as finished stock is
                # exactly what came in as bottled product (breakages, if any, are already
                # netted into the recorded bottled-product count -- see the founder's
                # 2026-09-16 note). Without this, labelling only ever consumed and never
                # produced, so finished stock vanished from the UI entirely.
                #
                # One output per label batch this VAT's bottles fall into (almost always
                # one; more when the run crosses a 500-bottle label-roll boundary) -- see
                # whistlebird_replay_timeline._assign_label_batches. batch_number lands on
                # the created item's extra_data (backend.py's complete_step) and is what
                # InventoryRepository.consume_final_product_fifo later drains oldest-first.
                label_batches = event.payload.get("label_batches") or [
                    (None, str(sum((Decimal(str(item["quantity"])) for item in bottled_items), Decimal("0"))))
                ]
                product_name = f"{batch.product_line.capitalize()} - final product"
                for batch_number, quantity in label_batches:
                    output = {"name": product_name, "quantity": str(quantity), "unit": bottled_items[0]["unit"]}
                    if batch_number is not None:
                        output["batch_number"] = batch_number
                    actual_outputs.append(output)

    elif green_gold is not None:
        source_execution_id = store.execution_id_for_global_vat(green_gold.source_vat)
        if source_execution_id is None:
            raise ReplayRejectedError(f"{marker} needs source VAT{green_gold.source_vat}, which was never loaded")
        source_item = None
        for source_step in store.execution_steps(source_execution_id):
            candidate = _produced_item_for_step(store, source_step["id"], "Aged Gin")
            if candidate is not None:
                source_item = candidate
        if source_item is None:
            raise ReplayRejectedError(f"VAT{green_gold.source_vat} has no aged Wildflower output to divert")
        actual_inputs.append(_consume_item_quantity(source_item, green_gold.source_quantity_l))
        actual_outputs.append(
            {"name": "Green Gold - final product", "quantity": str(green_gold.bottles), "unit": "units"}
        )

    elif trial is not None and step_key == "library_stock" and trial.library_ml:
        actual_outputs.append({"name": "Library stock", "quantity": str(trial.library_ml), "unit": "mL"})

    execution_data = {
        "batch_ref": marker,
        "batch_label": (batch.batch_label if batch else trial.label if trial else green_gold.batch_label),
        "global_vat": (batch.global_vat if batch else None),
    }
    if green_gold is not None:
        execution_data.update(
            {
                "source_vat": green_gold.source_vat,
                "source_quantity_l": str(green_gold.source_quantity_l),
                "bottle_size_ml": str(green_gold.bottle_size_ml),
            }
        )
    if batch is not None and step_key == "aging" and batch.product_line != "rosella":
        execution_data["VAT number"] = batch.global_vat
    if batch is not None and step_key == "distilling":
        flask_codes = event.payload.get("flask_codes")
        if flask_codes:
            execution_data["Flask code"] = ", ".join(flask_codes)
    if batch is not None and batch.product_line in ("wildflower", "solstice") and step_key in ("bottling", "labelling"):
        execution_data["Batch number"] = _batch_number_prompt_value(event.payload.get("label_batches"))

    client.post(
        f"/api/core/executions/{execution_id}/steps/{step_row['id']}/complete",
        {
            "actual_inputs": actual_inputs,
            "actual_outputs": actual_outputs,
            "execution_data": execution_data,
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
    # date_period is a "YYYY-MM" label, not a real date (400s the endpoint's YYYY-MM-DD
    # parser) -- the actual period bounds are the real lodgement date column, same as
    # the existing ORM-direct script (apply_customs_lodgements uses source_date for
    # both period_start and period_end; date_period is only ever a human-readable label).
    lodgement_date = row["date"]
    lodgement_date_iso = lodgement_date.isoformat() if hasattr(lodgement_date, "isoformat") else lodgement_date
    period_label = row.get("date_period") or lodgement_date_iso
    source_execution_id = store.most_recently_created_execution_id()
    client.post(
        "/api/compliant/records",
        {
            "framework_slug": "customs-alcohol",
            "control_id": "period-lodgement",
            "record_type": "lodgement",
            "status": "complete",
            "source_refs": [source_execution_id] if source_execution_id else [],
            "title": f"Customs lodgement — {period_label}",
            "period_start": lodgement_date_iso,
            "period_end": lodgement_date_iso,
            "evidence_reference": f"Customs alcohol reconciliation lodgement for period {period_label}.",
            "measured_value": str(row["lal"]) if row.get("lal") is not None else None,
            "details": {
                "import_ref": marker,
                "period_label": period_label,
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
    legacy_source: str | Path,
    target_url: str,
    production_manifest_path: Path,
    admin_email: str,
    admin_password: str,
    org_name: str,
    verify_tls: bool = True,
    limit: int | None = None,
    np3_manifest_path: Path | None = np3.DEFAULT_NP3_MANIFEST,
    crm_manifest_path: Path | None = crm.DEFAULT_CRM_MANIFEST,
) -> dict[str, Any]:
    # Validate before the first request so a bad NP3 manifest fails now, not after the
    # long Core replay has already run.
    np3_manifest = np3.load_np3_manifest(np3_manifest_path) if np3_manifest_path else None
    crm_manifest = crm.load_crm_manifest(crm_manifest_path) if crm_manifest_path else None
    events = build_timeline(legacy_source, production_manifest_path)
    if limit is not None:
        events = events[:limit]

    # Keep the account's actual password in sync with KeePass before every run, rather
    # than trusting whatever it was last set to -- self-healing, so it never silently
    # drifts out from under whoever needs to log in and check on this tenant by hand.
    wm.sync_whistlebird_test_admin_password(target_url, org_name, admin_email)

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

    # CRM mappings need each final product to exist, so they follow the Core history.
    if crm_manifest is not None and limit is None:
        try:
            counts["crm"] = crm.replay_crm_config(client, crm_manifest)
        except crm.CrmReplayError as exc:
            raise ReplayRejectedError(str(exc)) from exc

    # NP3 evidence goes last: an `np3_execution_evidence_mode: required` profile (part of
    # the manifest) would otherwise block the Core step completions above.
    if np3_manifest is not None and limit is None:
        np3_store = np3.Np3Store(target_url, org_id)
        try:
            counts["np3"] = np3.replay_np3(client, np3_store, np3_manifest)
        finally:
            np3_store.dispose()
    return counts


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://localhost:8001")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verification (self-signed local certs).")
    parser.add_argument(
        "--legacy-url",
        "--legacy-source",
        dest="legacy_source",
        default=legacy.DEFAULT_LEGACY_SNAPSHOT,
        help="Where the prior inventory data comes from: a path to a snapshot JSON (default: the committed "
        "docs/whistlebird-legacy-source.json) or a postgresql:// URL to read the live legacy database.",
    )
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--production-manifest", type=Path, default=wm.DEFAULT_PRODUCTION_MANIFEST)
    parser.add_argument("--admin-email", default=wm.DEFAULT_TEST_ADMIN_EMAIL)
    parser.add_argument("--admin-password-env", default="WHISTLEBIRD_TEST_ADMIN_PASSWORD")
    parser.add_argument("--org-name", default=wm.RESET_ORG_NAME)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only issue the first N Core events (smoke-testing); skips the NP3 phase.",
    )
    parser.add_argument("--np3-manifest", type=Path, default=np3.DEFAULT_NP3_MANIFEST)
    parser.add_argument("--skip-np3", action="store_true", help="Replay Core history only.")
    parser.add_argument("--crm-manifest", type=Path, default=crm.DEFAULT_CRM_MANIFEST)
    parser.add_argument("--skip-crm-config", action="store_true", help="Do not replay CRM product mappings/config.")
    args = parser.parse_args()
    if not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    args.admin_password = os.environ.get(args.admin_password_env)
    if not args.admin_password:
        # Same KeePassXC entry wm.sync_whistlebird_test_admin_password() keeps the
        # account synced with -- the env var remains a valid override, it's just no
        # longer required for local use.
        try:
            args.admin_password = wm._keepass_password(wm.WHISTLEBIRD_TEST_ADMIN_KEEPASS_ENTRY)
        except ValueError as e:
            parser.error(f"{args.admin_password_env} is not set and KeePassXC fallback failed: {e}")
    return args


def main() -> int:
    args = _arguments()
    result = run_replay(
        args.base_url,
        args.legacy_source,
        args.target_url,
        args.production_manifest,
        args.admin_email,
        args.admin_password,
        args.org_name,
        verify_tls=not args.insecure,
        limit=args.limit,
        np3_manifest_path=None if args.skip_np3 else args.np3_manifest,
        crm_manifest_path=None if args.skip_crm_config else args.crm_manifest,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
