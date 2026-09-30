"""Focused payload tests for the HTTP replay client, without issuing HTTP requests."""

import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_migration as wm  # noqa: E402
import whistlebird_replay as replay  # noqa: E402
from whistlebird_replay_timeline import ReplayEvent, _batch_events  # noqa: E402


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

    def consume_available_raw_material_up_to(self, name, quantity, unit, as_of=None, reserved_codes=frozenset()):
        return self.consume_available_raw_material(name, quantity, unit), Decimal("0")

    def consume_marked_raw_material(self, marker, quantity, unit):
        return [{"inventory_item_id": marker, "name": "Neutral grain spirit", "quantity": str(quantity), "unit": unit}]


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


def test_replay_uses_vat_batch_wip_for_a_documented_rosella_diversion():
    solstice_base = replace(_batch(), product_line="solstice", extra_data={"diverted_to": "Rosella VAT48"})

    assert replay._aging_output_name(solstice_base) == "VAT batch"
    assert replay._aging_output_name(_batch()) == "Aged Gin"


def test_replay_uses_canonical_recipe_fallback_and_dedicated_ngs():
    batch = _batch()
    store = _Store()
    precise_inputs = [{"inventory_item_id": "cardamom", "name": "Cardamom pods", "quantity": "43.2", "unit": "g"}]

    fallback = replay._recipe_fallback_inputs(store, batch, precise_inputs)

    assert not any(item["name"] == "Cardamom pods" for item in fallback)
    assert any(item["name"] == "Juniper Berries (Macedonian)" for item in fallback)


def test_replay_records_untracked_recipe_shortfall_without_backdating_a_purchase():
    class _ShortfallStore:
        def consume_available_raw_material_up_to(self, _name, quantity, _unit, _as_of=None, _reserved=frozenset()):
            return [], quantity

    fallback = replay._recipe_fallback_inputs(_ShortfallStore(), _batch(), [])

    juniper = next(item for item in fallback if item["name"] == "Juniper Berries (Macedonian)")
    assert juniper == {"name": "Juniper Berries (Macedonian)", "quantity": "59.4", "unit": "g"}


def test_replay_uses_physical_lot_quantity_without_changing_linked_consumption():
    class _PurchaseStore:
        def existing_inventory_item_id(self, _marker):
            return None

    event = ReplayEvent(
        event_id="purchase:CP019",
        event_type="create_inventory_item",
        real_date=date(2026, 9, 14),
        depends_on=(),
        payload={
            "marker": "raw-manifest-CP019",
            "record": {
                "code": "CP019",
                "ingredient": "Cardamom pods",
                "quantity": 43.2,
                "purchase_quantity": 500,
                "unit": "g",
                "date": "2026-09-14",
                "supplier": "Davis Trading",
                "supplier_batch_number": "393456",
                "expiry_date": "2027-11-30",
            },
        },
    )
    client = _Client()

    assert replay._execute_purchase(client, _PurchaseStore(), event) is True
    assert client.calls[0][1]["quantity"] == "500"
    assert event.payload["record"]["quantity"] == 43.2


def test_replay_canonicalises_legacy_botanical_display_names():
    class _PurchaseStore:
        def existing_inventory_item_id(self, _marker):
            return None

    event = ReplayEvent(
        event_id="purchase:legacy-purchases_ingredients-42",
        event_type="create_inventory_item",
        real_date=date(2024, 12, 5),
        depends_on=(),
        payload={
            "marker": "raw-legacy-purchases_ingredients-42",
            "record": {"name": "coriander seeds", "quantity": 1000, "unit": "g", "date": "2024-12-05"},
        },
    )
    client = _Client()

    assert replay._execute_purchase(client, _PurchaseStore(), event) is True
    payload = client.calls[0][1]
    assert payload["name"] == "Coriander seeds"
    assert payload["metadata"]["source_material_name"] == "coriander seeds"


def test_replay_carries_wip_outputs_required_prompts_and_batch_numbers(monkeypatch):
    batch = _batch()
    events = _batch_events(
        batch,
        {},
        {batch.global_vat: batch.marker},
        {},
        {batch.marker: [(1, Decimal("60")), (2, Decimal("18"))]},
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
                {"id": "bottle-2", "name": name, "quantity": "18", "unit": "units"},
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
    assert any(
        item["inventory_item_id"] == "raw-manifest-NGS-wildflower-vat27"
        for item in payloads["maceration"]["actual_inputs"]
    )
    assert payloads["distilling"]["execution_data"]["Flask code"] == "WBWF01, WBWF02"
    assert payloads["distilling"]["actual_outputs"] == [
        {"name": wm._DISTILLATE_OUTPUT_NAME, "quantity": "2.16", "unit": "L"}
    ]
    assert payloads["aging"]["execution_data"]["VAT number"] == 27
    assert payloads["aging"]["actual_outputs"] == [{"name": "Aged Gin", "quantity": "55", "unit": "L"}]
    assert payloads["bottling"]["actual_outputs"] == [
        {"name": "Bottled product", "quantity": "60", "unit": "units", "batch_number": 1},
        # The source's half bottle (78.5 x 700 mL) is Library stock, not a fractional count.
        {
            "name": "Bottled product",
            "quantity": "18",
            "unit": "units",
            "batch_number": 2,
            "library_remainder_ml": "350.0",
        },
    ]
    assert payloads["bottling"]["execution_data"]["Batch number"] == "1, 2"
    assert payloads["labelling"]["actual_outputs"] == [
        {"name": "Wildflower - final product", "quantity": "60", "unit": "units", "batch_number": 1},
        {"name": "Wildflower - final product", "quantity": "18", "unit": "units", "batch_number": 2},
    ]
    assert payloads["labelling"]["execution_data"]["Batch number"] == "1, 2"


def test_replay_sizes_a_sheet_sourced_half_bottle_at_the_default_700ml(monkeypatch):
    # Production-sheet bottlings carry no bottle_size_ml; the half bottle must not vanish.
    batch = replace(_batch(), bottlings=({"bottles": "56.5"},))
    events = _batch_events(batch, {}, {batch.global_vat: batch.marker}, {}, {batch.marker: [(1, Decimal("56"))]}, {})
    bottling = next(e for e in events if e.event_type == "complete_step" and e.payload["step_key"] == "bottling")
    client = _Client()
    monkeypatch.setattr(
        replay,
        "_produced_item_for_step",
        lambda _store, _step_id, name: {"id": "vat", "name": name, "quantity": "55", "unit": "L"},
    )

    assert replay._execute_complete_step(client, _Store(), bottling) is True

    assert client.calls[0][1]["actual_outputs"] == [
        {
            "name": "Bottled product",
            "quantity": "56",
            "unit": "units",
            "batch_number": 1,
            "library_remainder_ml": "350.0",
        }
    ]


def test_replay_converts_the_documented_vat53_draw_into_green_gold(monkeypatch):
    record = wm.GreenGoldRecord(
        source_vat=53,
        source_date=date(2026, 7, 31),
        source_quantity_l=Decimal("35.875"),
        bottles=Decimal("126"),
        bottle_size_ml=Decimal("500"),
        batch_label="GG01",
        source_table="production_sheet",
        source_id=2035,
    )
    event = ReplayEvent(
        event_id="green-gold-step:green-gold-gg01:bottling",
        event_type="complete_step",
        real_date=record.source_date,
        depends_on=(),
        payload={"green_gold": record, "step_key": "bottling", "step_index": 0},
    )

    class GreenGoldStore(_Store):
        def execution_id_for_global_vat(self, vat):
            assert vat == 53
            return "vat53-execution"

    monkeypatch.setattr(
        replay,
        "_produced_item_for_step",
        lambda _store, _step_id, name: {"id": "vat53-aged", "name": name, "quantity": "55.7", "unit": "L"}
        if name == "Aged Gin"
        else None,
    )
    client = _Client()

    assert replay._execute_complete_step(client, GreenGoldStore(), event) is True
    payload = client.calls[0][1]
    assert payload["actual_inputs"] == [
        {"inventory_item_id": "vat53-aged", "name": "Aged Gin", "quantity": "35.875", "unit": "L"}
    ]
    assert payload["actual_outputs"] == [{"name": "Green Gold - final product", "quantity": "126", "unit": "units"}]
    assert payload["execution_data"]["source_vat"] == 53
    assert payload["execution_data"]["bottle_size_ml"] == "500"


def test_replay_marks_unbottled_vat_as_not_applicable_for_required_batch_prompt():
    assert replay._batch_number_prompt_value(None) == "Not applicable — no bottled output recorded"
