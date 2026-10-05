"""Replay real, currently-in-progress production batches for Whistlebird Ltd.

Unlike the historical timeline (`whistlebird_replay_timeline.py`, sourced from the founder's
old spreadsheet of batches that have already finished every step), a "recent batch" here is a
real execution that started recently and has NOT finished every step yet -- e.g. a maceration
put on tonight, whose distilling/aging/bottling genuinely haven't happened. It draws its
tracked ingredients from whatever real stock the live tenant currently holds (FIFO, oldest
`purchase_date` first, via `MarkerStore.consume_available_raw_material` -- the same read-only
live-inventory lookup the historical replay itself uses for its NGS shortfall draws), not from
a historical purchase ledger, since these ARE that stock.

Maceration, distilling and aging (the VAT fill) are supported, on Wildflower or Solstice (the
recipe already defined in `whistlebird_migration.py`). A step is replayed only once the founder
has actually performed it: distilling needs the two flask codes, aging needs the VAT number
chosen at the fill, and each may carry its own date in `step_dates`. Bottling and labelling
remain a deliberate follow-up -- `load_manifest` refuses any other step name.

Source of truth for the manifest: `docs/whistlebird-recent-batches-source.json`.

Idempotent: an execution is identified by `execution_data->>'batch_ref'` (the same convention
`whistlebird_replay.py` uses), via `MarkerStore.existing_execution_id`/`step_already_completed`,
so a full rebuild replays a given batch's maceration exactly once, and a later step (once this
script supports it) will complete on the *same* execution rather than creating a new one.

The timestamp-correction pass dates these replayed operations to the manifest’s
`started` date (or the step's own `step_dates` entry), including their audit events. Rebuilding later must not make a recorded
September maceration appear as new production in October.

    uv run python scripts/whistlebird_recent_batches.py apply \\
        --base-url https://localhost:8005 --insecure --target-url postgresql://...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).parent))
import whistlebird_migration as wm  # noqa: E402

if TYPE_CHECKING:
    # whistlebird_replay imports this module (for its DEFAULT_RECENT_BATCHES_MANIFEST /
    # replay_recent_batches), so this side stays lazy (see main()) to avoid a circular import.
    import whistlebird_replay as replay

DEFAULT_RECENT_BATCHES_MANIFEST = Path(__file__).parents[1] / "docs" / "whistlebird-recent-batches-source.json"

# product_line -> (workflow name, maceration recipe inputs)
_MACERATION_RECIPE_BY_PRODUCT_LINE: dict[str, tuple[str, tuple[dict[str, Any], ...]]] = {
    "solstice": (wm.SOLSTICE_WORKFLOW, wm._SOLSTICE_MACERATION_INPUTS),
    "wildflower": (wm.WILDFLOWER_WORKFLOW, wm._WILDFLOWER_MACERATION_INPUTS),
}
# product_line -> (tracked NGS, untracked water) for the VAT fill at aging
_VAT_FILL_BY_PRODUCT_LINE: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "solstice": (wm._SOLSTICE_FILL_NGS_INPUT, wm._SOLSTICE_FILL_WATER_INPUT),
    "wildflower": (wm._WILDFLOWER_FILL_NGS_INPUT, wm._WILDFLOWER_FILL_WATER_INPUT),
}
# In workflow order: a batch's completed steps are always a prefix of this.
_SUPPORTED_STEPS = ("maceration", "distilling", "aging")
_AGING_OUTPUT_NAME = "Aged Gin"


class RecentBatchesError(RuntimeError):
    """The manifest is malformed, or asks for a step this script does not support yet."""


@dataclass(frozen=True)
class RecentBatch:
    marker: str
    product_line: str
    workflow: str
    started: date
    steps_completed: tuple[str, ...]
    note: str
    step_dates: tuple[tuple[str, date], ...] = ()
    flask_codes: tuple[str, ...] = ()
    vat_number: int | None = None

    def date_of(self, step: str) -> date:
        """The day a step was really done: its own recorded date, else the day the batch started."""
        return dict(self.step_dates).get(step, self.started)

    @property
    def batch_label(self) -> str:
        """The VAT label once one has been chosen at the fill; the marker until then."""
        return f"VAT{self.vat_number}" if self.vat_number is not None else self.marker


def parse_recent_batches_manifest(data: Any) -> tuple[RecentBatch, ...]:
    if not isinstance(data, dict) or not isinstance(data.get("batches"), list):
        raise RecentBatchesError('manifest must be an object with a "batches" list')
    unknown = sorted(set(data) - {"batches", "_comment"})
    if unknown:
        raise RecentBatchesError(f"manifest: unknown key(s) {', '.join(unknown)}")
    batches: list[RecentBatch] = []
    seen: set[str] = set()
    for index, entry in enumerate(data["batches"]):
        where = f"batches[{index}]"
        if not isinstance(entry, dict):
            raise RecentBatchesError(f"{where}: must be an object")
        marker = str(entry.get("marker") or "").strip()
        if not marker:
            raise RecentBatchesError(f"{where}: marker is required")
        if marker in seen:
            raise RecentBatchesError(f"{where}: duplicate marker {marker!r}")
        seen.add(marker)
        product_line = str(entry.get("product_line") or "")
        if product_line not in _MACERATION_RECIPE_BY_PRODUCT_LINE:
            raise RecentBatchesError(
                f"{where}: product_line must be one of {tuple(_MACERATION_RECIPE_BY_PRODUCT_LINE)}"
            )
        steps = tuple(entry.get("steps_completed") or ())
        unsupported = [step for step in steps if step not in _SUPPORTED_STEPS]
        if unsupported:
            raise RecentBatchesError(f"{where}: step(s) {unsupported} are not supported yet (only {_SUPPORTED_STEPS})")
        if steps != _SUPPORTED_STEPS[: len(steps)]:
            raise RecentBatchesError(f"{where}: steps_completed must follow the workflow order {_SUPPORTED_STEPS}")
        try:
            started = date.fromisoformat(str(entry.get("started")))
        except (TypeError, ValueError):
            raise RecentBatchesError(f"{where}: started must be a YYYY-MM-DD date") from None
        raw_dates = entry.get("step_dates") or {}
        if not isinstance(raw_dates, dict) or set(raw_dates) - set(steps):
            raise RecentBatchesError(f"{where}: step_dates may only date steps listed in steps_completed")
        try:
            step_dates = tuple((step, date.fromisoformat(str(raw_dates[step]))) for step in steps if step in raw_dates)
        except (TypeError, ValueError):
            raise RecentBatchesError(f"{where}: step_dates must be YYYY-MM-DD dates") from None
        ordered = [started] + [dict(step_dates).get(step, started) for step in steps]
        if ordered != sorted(ordered):
            raise RecentBatchesError(f"{where}: step_dates must not run backwards from started")
        flask_codes = tuple(str(code).strip() for code in entry.get("flask_codes") or ())
        if "distilling" in steps and (len(flask_codes) != 2 or not all(flask_codes)):
            raise RecentBatchesError(f"{where}: distilling needs the two flask_codes used")
        vat_number = entry.get("vat_number")
        if "aging" in steps and (not isinstance(vat_number, int) or isinstance(vat_number, bool) or vat_number <= 0):
            raise RecentBatchesError(f"{where}: aging needs the vat_number chosen at the fill")
        batches.append(
            RecentBatch(
                marker=marker,
                product_line=product_line,
                workflow=_MACERATION_RECIPE_BY_PRODUCT_LINE[product_line][0],
                started=started,
                steps_completed=steps,
                note=str(entry.get("note") or ""),
                step_dates=step_dates,
                flask_codes=flask_codes,
                vat_number=vat_number if "aging" in steps else None,
            )
        )
    return tuple(batches)


def load_recent_batches_manifest(path: Path = DEFAULT_RECENT_BATCHES_MANIFEST) -> tuple[RecentBatch, ...]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecentBatchesError(f"cannot read recent-batches manifest {path}: {exc}") from exc
    return parse_recent_batches_manifest(data)


def _maceration_actual_inputs(store: replay.MarkerStore, batch: RecentBatch) -> list[dict[str, Any]]:
    """Real stock, FIFO, for every tracked ingredient; the recipe's fixed value for the rest."""
    _workflow, recipe_inputs = _MACERATION_RECIPE_BY_PRODUCT_LINE[batch.product_line]
    actual_inputs: list[dict[str, Any]] = []
    for item in recipe_inputs:
        quantity = Decimal(str(item["quantity"]))
        if item.get("requires_inventory_selection"):
            actual_inputs.extend(
                store.consume_available_raw_material(item["name"], quantity, item["unit"], as_of=batch.started)
            )
        else:
            actual_inputs.append({"name": item["name"], "quantity": str(quantity), "unit": item["unit"]})
    return actual_inputs


def _previous_output(store: replay.MarkerStore, steps: list[dict[str, Any]], step_number: int, name: str):
    """Consume, whole, what the step before this one produced."""
    previous = next(s for s in steps if s["step_number"] == step_number - 1)
    item = store.produced_item_for_step(previous["id"], name)
    if item is None:
        raise RecentBatchesError(f"step {step_number} has no {name!r} from the step before it to consume")
    return {
        "inventory_item_id": str(item["id"]),
        "name": item["name"],
        "quantity": str(item["quantity"]),
        "unit": item["unit"],
    }


def _step_completion(
    store: replay.MarkerStore, batch: RecentBatch, step: str, steps: list[dict[str, Any]], step_number: int
) -> dict[str, Any]:
    """What the founder would record in the app for this step."""
    execution_data: dict[str, Any] = {"batch_ref": batch.marker, "batch_label": batch.marker}
    if step == "maceration":
        inputs = _maceration_actual_inputs(store, batch)
        output = (wm._MACERATION_OUTPUT_NAME, wm._MACERATION_OUTPUT_QUANTITY, wm._MACERATION_OUTPUT_UNIT)
    elif step == "distilling":
        inputs = [_previous_output(store, steps, step_number, wm._MACERATION_OUTPUT_NAME)]
        output = (wm._DISTILLATE_OUTPUT_NAME, wm._DISTILLATE_OUTPUT_QUANTITY, wm._DISTILLATE_OUTPUT_UNIT)
        execution_data["Flask code"] = ", ".join(batch.flask_codes)
    else:
        # The VAT fill: the concentrate, plus the product line's usual NGS (real stock, FIFO) and water.
        ngs, water = _VAT_FILL_BY_PRODUCT_LINE[batch.product_line]
        ngs_l, water_l = Decimal(ngs["quantity"]), Decimal(water["quantity"])
        inputs = [_previous_output(store, steps, step_number, wm._DISTILLATE_OUTPUT_NAME)]
        inputs.extend(store.consume_available_raw_material(ngs["name"], ngs_l, ngs["unit"], as_of=batch.date_of(step)))
        inputs.append({"name": water["name"], "quantity": str(water_l), "unit": water["unit"]})
        # Same convention as the historical VATs: the VAT's volume is its NGS plus water fill.
        output = (_AGING_OUTPUT_NAME, str(ngs_l + water_l), "L")
        execution_data.update(batch_label=batch.batch_label, global_vat=batch.vat_number)
        execution_data["VAT number"] = batch.vat_number
    return {
        "actual_inputs": inputs,
        "actual_outputs": [{"name": output[0], "quantity": output[1], "unit": output[2]}],
        "execution_data": execution_data,
    }


def replay_recent_batches(
    client: replay.ReplayClient, store: replay.MarkerStore, batches: tuple[RecentBatch, ...]
) -> dict[str, int]:
    counts = {"executions_created": 0, "steps_completed": 0, "skipped": 0}
    for batch in batches:
        execution_id = store.existing_execution_id(batch.marker)
        if execution_id is None:
            process_id = store.process_id_for_workflow(batch.workflow)
            response = client.post("/api/core/executions", {"process_id": str(process_id)})
            execution_id = response["id"]
            store.note_created_execution(batch.marker, execution_id)
            counts["executions_created"] += 1
        for step in batch.steps_completed:
            step_number = _SUPPORTED_STEPS.index(step) + 1
            if store.step_already_completed(execution_id, step_number):
                counts["skipped"] += 1
                continue
            # Re-read each time: completing a step is what makes the next one's inputs exist.
            steps = store.execution_steps(execution_id)
            step_row = next(s for s in steps if s["step_number"] == step_number)
            client.post(
                f"/api/core/executions/{execution_id}/steps/{step_row['id']}/complete",
                _step_completion(store, batch, step, steps, step_number),
            )
            counts["steps_completed"] += 1
    return counts


def expected_verification_contribution(
    batches: tuple[RecentBatch, ...],
) -> tuple[dict[str, int], int, list[str]]:
    """What an API replay of these batches adds on top of the historical-import baseline
    that `whistlebird_migration.build_import_verification` otherwise checks against:
    one execution per batch, its still-pending steps counted as incomplete, and its
    markers. Their replay timestamps are corrected to the recorded start date, while
    genuinely unfinished steps remain unfinished.

    A batch's pending count is "every workflow step it has not listed as completed" --
    this falls out of the workflow's real step list rather than assuming a fixed shape.
    """
    workflow_counts: dict[str, int] = {}
    incomplete_steps = 0
    markers: list[str] = []
    for batch in batches:
        workflow_counts[batch.workflow] = workflow_counts.get(batch.workflow, 0) + 1
        total_steps = len(wm.PRODUCT_WORKFLOWS[batch.workflow][1])
        incomplete_steps += total_steps - len(batch.steps_completed)
        markers.append(batch.marker)
    return workflow_counts, incomplete_steps, markers


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("validate", "apply"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RECENT_BATCHES_MANIFEST)
    parser.add_argument("--target-url", default=os.environ.get("BIZE_MIGRATION_DATABASE_URL"))
    parser.add_argument("--org-name", default=wm.WHISTLEBIRD_ORG_NAME)
    parser.add_argument("--base-url", default="https://localhost:8005")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verification (self-signed local certs).")
    parser.add_argument("--admin-email", default=wm.DEFAULT_ADMIN_EMAIL)
    parser.add_argument("--admin-password-env", default="WHISTLEBIRD_ADMIN_PASSWORD")
    args = parser.parse_args(argv)
    if args.command == "apply" and not args.target_url:
        parser.error("--target-url is required (or set BIZE_MIGRATION_DATABASE_URL)")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    import whistlebird_replay as replay  # noqa: PLC0415 (avoids a circular import; see the TYPE_CHECKING import above)

    try:
        batches = load_recent_batches_manifest(args.manifest)
        if args.command == "validate":
            print(f"ok: {len(batches)} batch(es)")
            return 0
        from sqlalchemy import create_engine, text

        engine = create_engine(args.target_url)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT id FROM organisations WHERE name = :name"), {"name": args.org_name}
                ).first()
        finally:
            engine.dispose()
        if not row:
            raise RecentBatchesError(f"org {args.org_name!r} does not exist")
        org_id = row[0]
        password = os.environ.get(args.admin_password_env) or wm._keepass_password(wm.WHISTLEBIRD_ADMIN_KEEPASS_ENTRY)
        client = replay.ReplayClient(args.base_url, verify_tls=not args.insecure)
        client.login(args.admin_email, password)
        store = replay.MarkerStore(args.target_url, org_id)
        counts = replay_recent_batches(client, store, batches)
        print(json.dumps(counts, indent=2))
        return 0
    except (RecentBatchesError, replay.ReplayRejectedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
