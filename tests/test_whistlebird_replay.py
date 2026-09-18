"""Focused payload tests for the HTTP replay client, without issuing HTTP requests."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_migration as wm  # noqa: E402
import whistlebird_replay as replay  # noqa: E402
from whistlebird_replay_timeline import _batch_events  # noqa: E402


class _Client:
    def __init__(self):
        self.calls = []

    def post(self, path, payload):
        self.calls.append((path, payload))
        return {}


class _Store:
    def existing_execution_id(self, _marker):
        return "execution-id"

    def step_already_completed(self, _execution_id, _step_number):
        return False

    def execution_steps(self, _execution_id):
        return [{"id": f"step-{number}", "step_number": number} for number in range(1, 6)]

    def consume_available_raw_material(self, name, quantity, unit):
        return [{"inventory_item_id": "ngs-id", "name": name, "quantity": str(quantity), "unit": unit}]


def _batch() -> wm.ProductionBatch:
    step_date = date(2025, 4, 2)
    return wm.ProductionBatch(
        global_vat=27,
        product_line="wildflower",
        batch_label="VAT27",
        steps={
            key: wm.BatchStep(key, step_date, "clean")
            for key in ("maceration", "distilling", "aging", "bottling", "labelling")
        },
        vat_volume_l=Decimal("55"),
        vat_abv=Decimal("44"),
        bottlings=({"bottles": "78.5", "bottle_size_ml": "700"},),
        ingredient_codes=(),
        base_vat=None,
        extra_data={},
    )


def test_replay_carries_wip_outputs_required_prompts_and_batch_numbers(monkeypatch):
    batch = _batch()
    events = _batch_events(
        batch,
        {},
        {batch.global_vat: batch.marker},
        {},
        {batch.marker: [(1, Decimal("60")), (2, Decimal("18.5"))]},
        {batch.marker: ("WBWF01", "WBWF02")},
    )
    by_key = {event.payload["step_key"]: event for event in events if event.event_type == "complete_step"}
    client = _Client()
    store = _Store()

    monkeypatch.setattr(
        replay,
        "_produced_item_for_step",
        lambda _store, _step_id, name: {
            wm._MACERATION_OUTPUT_NAME: {"id": "maceration-id", "name": name, "quantity": "3.6", "unit": "L"},
            wm._DISTILLATE_OUTPUT_NAME: {"id": "distillate-id", "name": name, "quantity": "2.16", "unit": "L"},
            "Aged Gin": {"id": "aged-id", "name": name, "quantity": "55", "unit": "L"},
        }.get(name),
    )
    monkeypatch.setattr(
        replay,
        "_produced_items_for_step",
        lambda _store, _step_id, name: (
            [
                {"id": "bottle-1", "name": name, "quantity": "60", "unit": "units"},
                {"id": "bottle-2", "name": name, "quantity": "18.5", "unit": "units"},
            ]
            if name == "Bottled product"
            else []
        ),
    )

    for key in ("maceration", "distilling", "aging", "bottling", "labelling"):
        assert replay._execute_complete_step(client, store, by_key[key]) is True

    payloads = {event.payload["step_key"]: call[1] for event, call in zip(by_key.values(), client.calls, strict=True)}
    assert payloads["maceration"]["actual_outputs"] == [
        {"name": wm._MACERATION_OUTPUT_NAME, "quantity": "3.6", "unit": "L"}
    ]
    assert payloads["distilling"]["execution_data"]["Flask code"] == "WBWF01, WBWF02"
    assert payloads["distilling"]["actual_outputs"] == [
        {"name": wm._DISTILLATE_OUTPUT_NAME, "quantity": "2.16", "unit": "L"}
    ]
    assert payloads["aging"]["execution_data"]["VAT number"] == 27
    assert payloads["aging"]["actual_outputs"] == [{"name": "Aged Gin", "quantity": "55", "unit": "L"}]
    assert payloads["bottling"]["actual_outputs"] == [
        {"name": "Bottled product", "quantity": "60", "unit": "units", "batch_number": 1},
        {"name": "Bottled product", "quantity": "18.5", "unit": "units", "batch_number": 2},
    ]
    assert payloads["labelling"]["actual_outputs"] == [
        {"name": "Wildflower - final product", "quantity": "60", "unit": "units", "batch_number": 1},
        {"name": "Wildflower - final product", "quantity": "18.5", "unit": "units", "batch_number": 2},
    ]
