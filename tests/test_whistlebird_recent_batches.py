"""Whistlebird recent-batches replay (scripts/whistlebird_recent_batches.py): manifest rules and
the maceration, distilling and VAT-fill replay logic, against a stub client/store (no real database or server)."""

import copy
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_recent_batches as rb  # noqa: E402

VALID = {
    "batches": [
        {
            "marker": "solstice-2026-09-22-maceration",
            "product_line": "solstice",
            "started": "2026-09-22",
            "steps_completed": ["maceration"],
            "note": "test",
        }
    ]
}


def test_committed_manifest_is_valid():
    batches = rb.load_recent_batches_manifest()

    assert len(batches) >= 1
    solstice = next(b for b in batches if b.marker == "solstice-2026-09-22-maceration")
    assert solstice.product_line == "solstice"
    assert solstice.steps_completed == ("maceration", "distilling", "aging")
    # 2026-09-29: distilled and VAT60 filled, a week after the maceration went on.
    assert solstice.date_of("maceration") == date(2026, 9, 22)
    assert solstice.date_of("distilling") == solstice.date_of("aging") == date(2026, 9, 29)
    assert (solstice.vat_number, solstice.batch_label, solstice.flask_codes) == (60, "VAT60", ("WBSS29", "WBSS30"))


def test_committed_production_manifest_records_vat57_bottling():
    batches, _excluded = rb.wm._load_manifest(rb.wm.DEFAULT_PRODUCTION_MANIFEST)
    batch = next(b for b in batches if b.global_vat == 57)

    assert [(b["date"], Decimal(str(b["bottles"]))) for b in batch.bottlings] == [("2026-09-29", Decimal("78"))]
    assert batch.pending_steps == frozenset({"labelling"})


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(extra=1), "unknown key"),
        (lambda d: d["batches"][0].update(marker=""), "marker is required"),
        (lambda d: d["batches"].append(copy.deepcopy(d["batches"][0])), "duplicate marker"),
        (lambda d: d["batches"][0].update(product_line="rosella"), "product_line must be one of"),
        (lambda d: d["batches"][0].update(steps_completed=["bottling"]), "not supported yet"),
        (lambda d: d["batches"][0].update(steps_completed=["distilling"]), "must follow the workflow order"),
        (lambda d: d["batches"][0].update(steps_completed=["maceration", "distilling"]), "two flask_codes"),
        (lambda d: d["batches"][0].update(**_through_aging(vat_number=None)), "vat_number chosen at the fill"),
        (lambda d: d["batches"][0].update(step_dates={"aging": "2026-09-29"}), "only date steps listed"),
        (lambda d: d["batches"][0].update(**_through_aging(step_dates={"aging": "2026-09-01"})), "run backwards"),
        (lambda d: d["batches"][0].update(started="22/09/2026"), "YYYY-MM-DD"),
    ],
)
def test_manifest_rejects_what_the_replay_cannot_do(mutate, message):
    data = copy.deepcopy(VALID)
    mutate(data)

    with pytest.raises(rb.RecentBatchesError, match=message):
        rb.parse_recent_batches_manifest(data)


def _through_aging(**overrides):
    fields = {
        "steps_completed": ["maceration", "distilling", "aging"],
        "step_dates": {"distilling": "2026-09-29", "aging": "2026-09-29"},
        "flask_codes": ["WBSS29", "WBSS30"],
        "vat_number": 60,
    }
    fields.update(overrides)
    return fields


class _Client:
    """Mimics the real API: completing a step is what makes it show as completed."""

    def __init__(self, store):
        self.calls = []
        self.store = store

    def post(self, path, body):
        self.calls.append((path, body))
        if path == "/api/core/executions":
            return {"id": "exec-1"}
        if path.endswith("/complete"):
            execution_id, step_id = path.split("/")[4], path.split("/")[6]
            step_number = int(step_id.rsplit("-", 1)[1])
            self.store._steps_completed.add((execution_id, step_number))
            for index, output in enumerate(body["actual_outputs"]):
                self.store._produced[(step_id, output["name"])] = {
                    "id": f"wip-{step_number}-{index}",
                    "name": output["name"],
                    "unit": output["unit"],
                    "quantity": Decimal(output["quantity"]),
                }
        return {}


class _Store:
    """Minimal stand-in for whistlebird_replay.MarkerStore's read-only surface."""

    def __init__(self, stock):
        self.stock = dict(stock)  # name -> (inventory_item_id, quantity available)
        self._executions = {}
        self._steps_completed = set()
        self._produced = {}

    def existing_execution_id(self, marker):
        return self._executions.get(marker)

    def note_created_execution(self, marker, execution_id):
        self._executions[marker] = execution_id

    def process_id_for_workflow(self, workflow_name):
        return "process-1"

    def execution_steps(self, execution_id):
        return [{"id": f"step-{number}", "step_number": number, "status": "ready"} for number in range(1, 6)]

    def produced_item_for_step(self, execution_step_id, name):
        return self._produced.get((execution_step_id, name))

    def step_already_completed(self, execution_id, step_number):
        return (execution_id, step_number) in self._steps_completed

    def consume_available_raw_material(self, name, quantity_needed, unit, as_of=None):
        item_id, available = self.stock[name]
        assert available >= quantity_needed, f"{name}: only {available} {unit} available, need {quantity_needed}"
        return [{"inventory_item_id": item_id, "name": name, "quantity": str(quantity_needed), "unit": unit}]


def _solstice_stock():
    return {
        "Juniper Berries (Macedonian)": ("inv-1", Decimal("718.8352")),
        "Juniper Berries (Himalayan)": ("inv-2", Decimal("271")),
        "Whole nutmeg (organic)": ("inv-3", Decimal("49.6")),
        "Cinnamon": ("inv-4", Decimal("94.24")),
        "Liquorice root": ("inv-5", Decimal("340.8")),
        "Szechuan pepper": ("inv-6", Decimal("449.6")),
        "Neutral grain spirit": ("inv-7", Decimal("51.596")),
    }


def test_replay_creates_the_execution_and_completes_maceration_from_real_stock():
    batches = rb.parse_recent_batches_manifest(VALID)
    store = _Store(_solstice_stock())
    client = _Client(store)

    counts = rb.replay_recent_batches(client, store, batches)

    assert counts == {"executions_created": 1, "steps_completed": 1, "skipped": 0}
    assert client.calls[0] == ("/api/core/executions", {"process_id": "process-1"})
    complete_path, complete_body = client.calls[1]
    assert complete_path == "/api/core/executions/exec-1/steps/step-1/complete"
    tracked = {i["name"]: i for i in complete_body["actual_inputs"] if "inventory_item_id" in i}
    assert tracked["Juniper Berries (Macedonian)"] == {
        "inventory_item_id": "inv-1",
        "name": "Juniper Berries (Macedonian)",
        "quantity": "226.8",
        "unit": "g",
    }
    untracked = {i["name"]: i for i in complete_body["actual_inputs"] if "inventory_item_id" not in i}
    assert untracked["Water"] == {"name": "Water", "quantity": "2.854", "unit": "L"}
    assert complete_body["actual_outputs"] == [
        {"name": "Maceration charge (2 x 1.8L, 20% ABV)", "quantity": "3.6", "unit": "L"}
    ]
    assert complete_body["execution_data"]["batch_ref"] == "solstice-2026-09-22-maceration"


def test_replay_is_idempotent():
    batches = rb.parse_recent_batches_manifest(VALID)
    store = _Store(_solstice_stock())
    client = _Client(store)
    rb.replay_recent_batches(client, store, batches)

    second = rb.replay_recent_batches(client, store, batches)

    assert second == {"executions_created": 0, "steps_completed": 0, "skipped": 1}


def test_replay_raises_clearly_when_real_stock_is_short():
    batches = rb.parse_recent_batches_manifest(VALID)
    stock = _solstice_stock()
    stock["Cinnamon"] = ("inv-4", Decimal("1"))  # recipe needs 5.76g
    store = _Store(stock)
    client = _Client(store)

    with pytest.raises(AssertionError, match="Cinnamon"):
        rb.replay_recent_batches(client, store, batches)


def test_expected_verification_contribution_counts_one_execution_and_its_pending_steps():
    """A full rebuild's verification (whistlebird_migration.build_import_verification)
    must expect what an API replay of these batches actually creates, or a real
    in-progress batch (this MR's Solstice maceration) makes every rebuild fail forever:
    one execution for its workflow, and every step past the ones it lists as done
    counted as still-incomplete -- not zero, which is what the historical-only baseline
    assumes for a workflow it doesn't know is missing steps on purpose."""
    batches = rb.parse_recent_batches_manifest(VALID)

    workflow_counts, incomplete_steps, markers = rb.expected_verification_contribution(batches)

    total_solstice_steps = len(rb.wm.PRODUCT_WORKFLOWS[rb.wm.SOLSTICE_WORKFLOW][1])
    assert workflow_counts == {rb.wm.SOLSTICE_WORKFLOW: 1}
    assert incomplete_steps == total_solstice_steps - 1  # only "maceration" is done
    assert markers == ["solstice-2026-09-22-maceration"]


def test_expected_verification_contribution_sums_across_multiple_batches():
    two_batches = {
        "batches": [
            VALID["batches"][0],
            {
                "marker": "wildflower-2026-09-22-maceration",
                "product_line": "wildflower",
                "started": "2026-09-22",
                "steps_completed": ["maceration"],
                "note": "test",
            },
        ]
    }
    batches = rb.parse_recent_batches_manifest(two_batches)

    workflow_counts, incomplete_steps, markers = rb.expected_verification_contribution(batches)

    assert workflow_counts == {rb.wm.SOLSTICE_WORKFLOW: 1, rb.wm.WILDFLOWER_WORKFLOW: 1}
    solstice_steps = len(rb.wm.PRODUCT_WORKFLOWS[rb.wm.SOLSTICE_WORKFLOW][1])
    wildflower_steps = len(rb.wm.PRODUCT_WORKFLOWS[rb.wm.WILDFLOWER_WORKFLOW][1])
    assert incomplete_steps == (solstice_steps - 1) + (wildflower_steps - 1)
    assert set(markers) == {"solstice-2026-09-22-maceration", "wildflower-2026-09-22-maceration"}


def _through_aging_manifest():
    data = copy.deepcopy(VALID)
    data["batches"][0].update(_through_aging())
    return rb.parse_recent_batches_manifest(data)


def test_replay_carries_a_batch_through_distilling_and_the_vat_fill():
    """AC: 'Distilled Solstice (VAT60)' and 'Filled VAT60 with the usual Solstice VAT measurements'."""
    store = _Store(_solstice_stock())
    client = _Client(store)

    counts = rb.replay_recent_batches(client, store, _through_aging_manifest())

    assert counts == {"executions_created": 1, "steps_completed": 3, "skipped": 0}
    (_, _maceration), (distil_path, distilling), (aging_path, aging) = client.calls[1:]
    assert distil_path == "/api/core/executions/exec-1/steps/step-2/complete"
    assert distilling["actual_inputs"] == [
        {
            "inventory_item_id": "wip-1-0",
            "name": "Maceration charge (2 x 1.8L, 20% ABV)",
            "quantity": "3.6",
            "unit": "L",
        }
    ]
    assert distilling["actual_outputs"] == [{"name": "Gin concentrate", "quantity": "2.16", "unit": "L"}]
    assert distilling["execution_data"]["Flask code"] == "WBSS29, WBSS30"

    assert aging_path == "/api/core/executions/exec-1/steps/step-3/complete"
    assert aging["actual_inputs"] == [
        {"inventory_item_id": "wip-2-0", "name": "Gin concentrate", "quantity": "2.16", "unit": "L"},
        {"inventory_item_id": "inv-7", "name": "Neutral grain spirit", "quantity": "17.776", "unit": "L"},
        {"name": "Water", "quantity": "25.064", "unit": "L"},
    ]
    assert aging["actual_outputs"] == [{"name": "Aged Gin", "quantity": "42.840", "unit": "L"}]
    assert aging["execution_data"] == {
        "batch_ref": "solstice-2026-09-22-maceration",
        "batch_label": "VAT60",
        "global_vat": 60,
        "VAT number": 60,
    }


def test_replay_adds_only_the_new_steps_to_a_batch_already_macerated():
    """The live tenant already holds the maceration; a later manifest must only add to it."""
    store = _Store(_solstice_stock())
    client = _Client(store)
    rb.replay_recent_batches(client, store, rb.parse_recent_batches_manifest(VALID))

    counts = rb.replay_recent_batches(client, store, _through_aging_manifest())

    assert counts == {"executions_created": 0, "steps_completed": 2, "skipped": 1}
    assert rb.replay_recent_batches(client, store, _through_aging_manifest()) == {
        "executions_created": 0,
        "steps_completed": 0,
        "skipped": 3,
    }


def test_vat_fill_refuses_to_run_without_the_concentrate():
    store = _Store(_solstice_stock())
    batch = _through_aging_manifest()[0]

    with pytest.raises(rb.RecentBatchesError, match="Gin concentrate"):
        rb._step_completion(store, batch, "aging", store.execution_steps("exec-1"), 3)


def test_verification_expects_two_pending_steps_once_the_vat_is_filled():
    _workflows, incomplete_steps, _markers = rb.expected_verification_contribution(_through_aging_manifest())

    assert incomplete_steps == len(rb.wm.PRODUCT_WORKFLOWS[rb.wm.SOLSTICE_WORKFLOW][1]) - 3
