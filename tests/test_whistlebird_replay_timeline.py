"""Unit tests for the replay ordering algorithm -- no database, pure data in/out.

`build_timeline()` itself (DB + manifest reading) is exercised as an integration check
in `scripts/whistlebird_replay.py`'s own dry-run; these tests only cover
`date_prioritised_topological_sort`, since that's the part where a subtle bug would
silently reorder a 600+ event replay instead of loudly failing.
"""

import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_migration as wm  # noqa: E402
from whistlebird_replay_timeline import (  # noqa: E402
    NGS_LEGACY_POOL_CUTOFF,
    ReplayEvent,
    _assign_flask_codes,
    _batch_events,
    _enrich_ingredient_codes,
    _flask_ngs_and_water_l,
    _foraged_botanical_inputs,
    _ngs_allocations,
    _ngs_purchase_event,
    _split_legacy_generic_juniper_receipts,
    _vat_fill_ngs_and_water_l,
    count_dedicated_ngs_purchases,
    date_prioritised_topological_sort,
    manifest_ngs_receipts,
)


def test_splits_legacy_generic_juniper_into_the_two_recipe_origins():
    record = wm.RawMaterialRecord(
        source_table="purchases_ingredients",
        source_id=1,
        source_date=date(2023, 11, 29),
        name="juniper berries",
        quantity=Decimal("500"),
        unit="g",
        supplier="Davis Trading",
        supplier_batch_number="JB001",
        expiry_date=None,
        extra_data={},
    )
    batches = [
        _wildflower_batch(date(2024, 1, 1), product_line="wildflower"),
        _wildflower_batch(date(2024, 1, 2), product_line="solstice"),
    ]

    split = _split_legacy_generic_juniper_receipts([record], batches)

    assert [row.name for row in split] == ["Juniper Berries (Macedonian)", "Juniper Berries (Himalayan)"]
    assert sum((row.quantity for row in split), Decimal("0")) == Decimal("500")
    assert all(row.extra_data["source_material_name"] == "juniper berries" for row in split)


def _event(event_id: str, real_date: str, depends_on: tuple[str, ...] = ()) -> ReplayEvent:
    return ReplayEvent(
        event_id=event_id,
        event_type="complete_step",
        real_date=date.fromisoformat(real_date),
        depends_on=depends_on,
    )


def test_sorts_independent_events_purely_by_date():
    events = [
        _event("c", "2025-03-01"),
        _event("a", "2025-01-01"),
        _event("b", "2025-02-01"),
    ]
    ordered = date_prioritised_topological_sort(events)
    assert [e.event_id for e in ordered] == ["a", "b", "c"]


def test_dependency_wins_over_a_later_dependent_date():
    # b depends on a, but a is dated AFTER b -- the hard dependency must still win:
    # a comes first in the output regardless of the date ordering.
    events = [
        _event("a", "2025-06-01"),
        _event("b", "2025-01-01", depends_on=("a",)),
    ]
    ordered = date_prioritised_topological_sort(events)
    assert [e.event_id for e in ordered] == ["a", "b"]


def test_dependency_chain_within_one_execution_stays_in_step_order():
    events = [
        _event("step5", "2025-01-05", depends_on=("step4",)),
        _event("step1", "2025-01-01"),
        _event("step3", "2025-01-03", depends_on=("step2",)),
        _event("step2", "2025-01-02", depends_on=("step1",)),
        _event("step4", "2025-01-04", depends_on=("step3",)),
    ]
    ordered = date_prioritised_topological_sort(events)
    assert [e.event_id for e in ordered] == ["step1", "step2", "step3", "step4", "step5"]


def test_two_independent_chains_interleave_by_date():
    events = [
        _event("a1", "2025-01-01"),
        _event("a2", "2025-01-10", depends_on=("a1",)),
        _event("b1", "2025-01-05"),
        _event("b2", "2025-01-06", depends_on=("b1",)),
    ]
    ordered = date_prioritised_topological_sort(events)
    # a1 (Jan 1) first; then b1 (Jan 5) and b2 (Jan 6) both become/stay ready before a2
    # (Jan 10) is reachable, so the whole b-chain runs before a2.
    assert [e.event_id for e in ordered] == ["a1", "b1", "b2", "a2"]


def test_missing_dependency_raises():
    events = [_event("a", "2025-01-01", depends_on=("ghost",))]
    with pytest.raises(ValueError, match="unknown event"):
        date_prioritised_topological_sort(events)


def test_dependency_cycle_raises():
    events = [
        _event("a", "2025-01-01", depends_on=("b",)),
        _event("b", "2025-01-02", depends_on=("a",)),
    ]
    with pytest.raises(ValueError, match="cycle"):
        date_prioritised_topological_sort(events)


def test_empty_timeline_is_fine():
    assert date_prioritised_topological_sort([]) == []


def test_tiebreak_on_identical_dates_is_deterministic_by_event_id():
    events = [_event("z", "2025-01-01"), _event("a", "2025-01-01"), _event("m", "2025-01-01")]
    ordered1 = date_prioritised_topological_sort(list(events))
    ordered2 = date_prioritised_topological_sort(list(reversed(events)))
    assert [e.event_id for e in ordered1] == [e.event_id for e in ordered2] == ["a", "m", "z"]


def _wildflower_batch(step_date: date, global_vat: int = 27, product_line: str = "wildflower") -> wm.ProductionBatch:
    return wm.ProductionBatch(
        global_vat=global_vat,
        product_line=product_line,
        batch_label=f"VAT{global_vat}",
        steps={
            "maceration": wm.BatchStep("maceration", step_date, "clean"),
            "distilling": wm.BatchStep("distilling", step_date, "clean"),
            "aging": wm.BatchStep("aging", step_date, "clean"),
            "bottling": wm.BatchStep("bottling", step_date, "clean"),
            "labelling": wm.BatchStep("labelling", step_date, "clean"),
        },
        vat_volume_l=Decimal("55"),
        vat_abv=Decimal("44"),
        bottlings=({"bottles": "78.5", "bottle_size_ml": "700"},),
        ingredient_codes=(),
        base_vat=None,
        extra_data={},
    )


def test_wildflower_recipe_uses_founder_confirmed_ngs_water_and_foraged_inputs():
    flask_ngs, flask_water = _flask_ngs_and_water_l()
    fill_ngs, fill_water = _vat_fill_ngs_and_water_l("wildflower")

    assert (flask_ngs, flask_water) == (Decimal("0.746"), Decimal("2.854"))
    # 24.456 L initial dilution, plus the NGS portion of the 1.260 L / 66.6% top-up.
    assert (fill_ngs, fill_water) == (Decimal("25.326"), Decimal("30.787"))
    assert _foraged_botanical_inputs("wildflower") == [
        {"name": "Lemon juice", "quantity": "34", "unit": "mL"},
        {"name": "Grapefruit (pink) juice", "quantity": "54", "unit": "mL"},
        {"name": "Lemon peel", "quantity": "3.0", "unit": "g"},
    ]
    assert _foraged_botanical_inputs("solstice") == [
        {"name": "Kawakawa leaf", "quantity": "8", "unit": "g"},
        {"name": "Orange peel", "quantity": "5.0", "unit": "g"},
        {"name": "Orange juice", "quantity": "108", "unit": "mL"},
    ]


def test_post_cutoff_ngs_purchase_is_created_before_maceration_consumes_it():
    batch = _wildflower_batch(NGS_LEGACY_POOL_CUTOFF)
    events = _batch_events(batch, {}, {batch.global_vat: batch.marker}, {})
    purchase = next(event for event in events if event.event_id.startswith("purchase:NGS-"))
    maceration = next(event for event in events if event.event_id.endswith(":maceration"))

    assert purchase.real_date == date(2025, 3, 30)
    assert purchase.payload["record"]["quantity"] == "26.072"
    assert purchase.event_id in maceration.depends_on
    assert maceration.payload["dedicated_ngs_quantity_l"] == "0.746"
    assert maceration.payload["dedicated_ngs_marker"] == "raw-manifest-NGS-wildflower-vat27"
    assert maceration.payload["other_material_inputs"][0] == {"name": "Water", "quantity": "2.854", "unit": "L"}
    aging = next(event for event in events if event.event_id.endswith(":aging"))
    assert aging.payload["dedicated_ngs_quantity_l"] == "25.326"
    assert aging.payload["other_material_inputs"] == [{"name": "Water", "quantity": "30.787", "unit": "L"}]


def test_distillation_flask_codes_are_line_specific_and_follow_distillation_dates():
    later_wildflower = _wildflower_batch(date(2025, 2, 2), global_vat=27)
    earlier_wildflower = _wildflower_batch(date(2025, 2, 1), global_vat=28)
    solstice = _wildflower_batch(date(2025, 2, 3), global_vat=29, product_line="solstice")

    codes = _assign_flask_codes([later_wildflower, solstice, earlier_wildflower])

    assert codes[earlier_wildflower.marker] == ("WBWF01", "WBWF02")
    assert codes[later_wildflower.marker] == ("WBWF03", "WBWF04")
    assert codes[solstice.marker] == ("WBSS01", "WBSS02")


def test_bottling_and_labelling_share_batch_numbers_and_distilling_carries_flask_codes():
    batch = _wildflower_batch(NGS_LEGACY_POOL_CUTOFF)
    events = _batch_events(
        batch,
        {},
        {batch.global_vat: batch.marker},
        {},
        {batch.marker: [(1, Decimal("60")), (2, Decimal("18.5"))]},
        {batch.marker: ("WBWF01", "WBWF02")},
    )

    distilling = next(event for event in events if event.event_id.endswith(":distilling"))
    bottling = next(event for event in events if event.event_id.endswith(":bottling"))
    labelling = next(event for event in events if event.event_id.endswith(":labelling"))

    assert distilling.payload["flask_codes"] == ("WBWF01", "WBWF02")
    assert bottling.payload["label_batches"] == [(1, "60"), (2, "18.5")]
    assert labelling.payload["label_batches"] == [(1, "60"), (2, "18.5")]


def test_pre_cutoff_batch_does_not_invent_a_dedicated_ngs_purchase():
    batch = _wildflower_batch(NGS_LEGACY_POOL_CUTOFF.replace(day=1))
    assert _ngs_purchase_event(batch, batch.steps["maceration"].step_date) is None


def test_enrich_ingredient_codes_preserves_pending_steps():
    # Regression: _enrich_ingredient_codes used to rebuild ProductionBatch field-by-field
    # and silently dropped pending_steps whenever a batch had raw-material codes attached
    # -- a batch with real linked ingredients would wrongly complete its pending bottling/
    # labelling steps. dataclasses.replace fixes this structurally.
    batch = replace(
        _wildflower_batch(NGS_LEGACY_POOL_CUTOFF),
        pending_steps=frozenset({"bottling", "labelling"}),
    )

    (enriched,) = _enrich_ingredient_codes([batch], {batch.global_vat: ["CP015"]})

    assert enriched.ingredient_codes == ("CP015",)
    assert enriched.pending_steps == frozenset({"bottling", "labelling"})


def test_batch_events_stop_before_the_first_pending_step():
    batch = replace(
        _wildflower_batch(NGS_LEGACY_POOL_CUTOFF),
        pending_steps=frozenset({"bottling", "labelling"}),
    )

    events = _batch_events(batch, {}, {batch.global_vat: batch.marker}, {})

    step_ids = [e.event_id for e in events if e.event_type == "complete_step"]
    assert step_ids == [
        f"step:{batch.marker}:maceration",
        f"step:{batch.marker}:distilling",
        f"step:{batch.marker}:aging",
    ]
    assert f"step:{batch.marker}:bottling" not in step_ids
    assert f"step:{batch.marker}:labelling" not in step_ids
    # The execution itself and the NGS shortfall purchase (aging is still completed, so
    # its VAT-fill NGS is genuinely consumed) are unaffected by the truncation.
    assert any(e.event_type == "create_execution" for e in events)


def test_ngs_allocation_uses_only_dated_source_receipts_before_creating_shortfall():
    first = _wildflower_batch(date(2025, 1, 10), global_vat=2)
    second = _wildflower_batch(date(2025, 1, 20), global_vat=1)
    receipts = [
        wm.RawMaterialRecord(
            "purchases_gns", 1, date(2025, 1, 5), "Neutral grain spirit", Decimal("20"), "L", None, None, None, {}
        ),
        wm.RawMaterialRecord(
            "purchases_gns", 2, date(2025, 1, 15), "Neutral grain spirit", Decimal("50"), "L", None, None, None, {}
        ),
    ]

    allocations = _ngs_allocations([second, first], receipts)

    assert allocations == {
        first.marker: (Decimal("20"), Decimal("6.072")),
        second.marker: (Decimal("26.072"), Decimal("0")),
    }
    assert count_dedicated_ngs_purchases([second, first], receipts) == 1


def test_manifest_ngs_receipts_converts_only_ngs_records_and_ignores_other_ingredients():
    raw_records = [
        {
            "code": "GNS-2023-04-24-1",
            "ingredient": "Neutral grain spirit",
            "quantity": 2,
            "unit": "L",
            "date": "2023-04-24",
            "supplier": "Southern Grain Spirits",
            "supplier_batch_number": "GNS-2023-04-24-1",
        },
        {
            "code": "JBM004",
            "ingredient": "Juniper Berries (Macedonian)",
            "quantity": 1000,
            "unit": "g",
            "date": "2025-08-10",
            "supplier": "Alembics",
            "supplier_batch_number": "MJUN-PP440328",
        },
    ]

    receipts = manifest_ngs_receipts(raw_records)

    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.name == "Neutral grain spirit"
    assert receipt.source_date == date(2023, 4, 24)
    assert receipt.quantity == Decimal("2")
    assert receipt.unit == "L"
    assert receipt.supplier == "Southern Grain Spirits"
    assert receipt.supplier_batch_number == "GNS-2023-04-24-1"


def test_ngs_allocation_pools_manifest_receipts_the_same_way_as_legacy_ones():
    batch = _wildflower_batch(date(2025, 1, 20), global_vat=1)
    raw_records = [
        {
            "code": "GNS-2025-01-05-1",
            "ingredient": "Neutral grain spirit",
            "quantity": 30,
            "unit": "L",
            "date": "2025-01-05",
            "supplier": "Southern Grain Spirits",
            "supplier_batch_number": "GNS-2025-01-05-1",
        }
    ]

    allocations = _ngs_allocations([batch], manifest_ngs_receipts(raw_records))

    # flask NGS (0.746) + VAT-fill NGS (25.326), same figures as the legacy-receipt test.
    assert allocations == {batch.marker: (Decimal("26.072"), Decimal("0"))}
