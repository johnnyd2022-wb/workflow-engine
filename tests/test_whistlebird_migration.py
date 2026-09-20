"""Focused tests for the Whistlebird production-history load primitives."""

import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture(scope="module")
def migration_module():
    script_path = Path(__file__).parents[1] / "scripts" / "whistlebird_migration.py"
    spec = importlib.util.spec_from_file_location("whistlebird_migration", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- deterministic helpers -----------------------------------------------------


def test_derived_timestamp_uses_agreed_nz_noon(migration_module):
    # June is NZST (+12), so noon Pacific/Auckland is midnight UTC.
    assert migration_module._derived_timestamp(date(2025, 6, 15)) == datetime(2025, 6, 15, 0, 0, tzinfo=UTC)


def test_decimal_rejects_negative_quantities(migration_module):
    with pytest.raises(ValueError, match="invalid quantity"):
        migration_module._decimal(-1, "quantity", "source_table", 42)


def test_monotonic_step_dates_fills_gaps_and_never_goes_backwards(migration_module):
    resolved, adjusted = migration_module._monotonic_step_dates(
        [date(2025, 1, 1), None, date(2024, 12, 1), date(2025, 3, 1), None]
    )
    assert resolved == [
        date(2025, 1, 1),
        date(2025, 1, 1),  # inherited from previous
        date(2025, 1, 1),  # pulled forward -- was earlier than previous
        date(2025, 3, 1),
        date(2025, 3, 1),  # inherited from previous
    ]
    assert adjusted == [False, True, True, False, True]


def test_monotonic_step_dates_backfills_a_leading_gap(migration_module):
    resolved, adjusted = migration_module._monotonic_step_dates([None, None, date(2026, 3, 26), None])
    assert resolved == [date(2026, 3, 26)] * 4
    assert adjusted == [True, True, False, True]


def test_monotonic_step_dates_requires_at_least_one_real_date(migration_module):
    with pytest.raises(ValueError, match="at least one real source date"):
        migration_module._monotonic_step_dates([None, None])


def test_import_marker_carries_no_legacy_wording(migration_module):
    marker = migration_module._import_marker("wildflower-vat7", "production_sheet", 7, step="bottling")
    assert marker[migration_module.IMPORT_MARKER_KEY] == "wildflower-vat7:bottling"
    assert marker[migration_module.BATCH_MARKER_KEY] == "wildflower-vat7"
    assert marker["step"] == "bottling"
    blob = json.dumps(marker).lower()
    assert "legacy" not in blob
    assert "historical" not in blob


def test_product_workflows_have_the_agreed_step_shape(migration_module):
    counts = {name: len(steps) for name, (_shape, steps) in migration_module.PRODUCT_WORKFLOWS.items()}
    assert counts == {
        "Wildflower gin": 5,
        "Solstice gin": 5,
        "Rosella gin": 4,
        "Green Gold Gin Liqueur": 1,
        "GG gin trials": 2,
        "WB recipe trials": 2,
        "SGS spirit trials": 2,
    }
    wildflower_steps = [s[0] for s in migration_module.PRODUCT_WORKFLOWS["Wildflower gin"][1]]
    assert wildflower_steps == ["Maceration", "Distilling", "Aging", "Bottling", "Labelling & packaging"]
    rosella_steps = [s[0] for s in migration_module.PRODUCT_WORKFLOWS["Rosella gin"][1]]
    assert rosella_steps[0] == "Rhubarb maceration" and "Distilling" not in rosella_steps


def test_wildflower_and_solstice_declare_inputs_on_every_step(migration_module):
    """2026-09-18: every step now consumes something -- the recipe at Maceration, and
    from Distilling onward, the immediately preceding step's own output (see
    _previous_step_output_input)."""
    for workflow_name in ("Wildflower gin", "Solstice gin"):
        _shape, steps = migration_module.PRODUCT_WORKFLOWS[workflow_name]
        for step in steps:
            assert step[4], f"{workflow_name}'s {step[0]!r} step should declare inputs"


def test_rosella_and_green_gold_workflows_declare_documented_chains(migration_module):
    for workflow_name in ("Rosella gin", "Green Gold Gin Liqueur", "GG gin trials", "WB recipe trials", "SGS spirit trials"):
        _shape, steps = migration_module.PRODUCT_WORKFLOWS[workflow_name]
        for index, step in enumerate(steps):
            if index == 0 and step[0] == "Rhubarb maceration":
                assert step[4], "Rhubarb maceration must declare inputs so botanicals are traceable"
            elif workflow_name == "Green Gold Gin Liqueur":
                assert step[4], "Green Gold bottling must declare its aged-Wildflower source"
            elif workflow_name in ("GG gin trials", "WB recipe trials", "SGS spirit trials"):
                assert step[4] == (), f"{step[0]} (step {index + 1}) should not declare inputs"

    rosella = migration_module.PRODUCT_WORKFLOWS["Rosella gin"][1]
    assert [step[2] for step in rosella] == ["VAT batch", "Aged Rosella", "Bottled product", "Rosella - final product"]
    assert all(step[4] for step in rosella)
    assert rosella[0][5] == rosella[1][5] == (migration_module._VAT_BATCH_PROMPT,)
    assert rosella[2][5] == rosella[3][5] == (migration_module._BATCH_NUMBER_PROMPT,)

    green_gold = migration_module.PRODUCT_WORKFLOWS["Green Gold Gin Liqueur"][1]
    assert {row["name"] for row in green_gold[0][4]} == {
        "Aged Wildflower gin", "Kawakawa", "Honey", "Sugar", "Water"
    }
    assert all(row["quantity"] is None for row in green_gold[0][4])
    assert green_gold[0][5] == (migration_module._BATCH_NUMBER_PROMPT,)
    assert green_gold[0][2:4] == ("Green Gold - final product", "units")


def test_wildflower_and_solstice_declare_an_output_on_every_step(migration_module):
    for workflow_name in ("Wildflower gin", "Solstice gin"):
        _shape, steps = migration_module.PRODUCT_WORKFLOWS[workflow_name]
        for step in steps:
            assert step[2], f"{workflow_name}'s {step[0]!r} step should declare an output"
    wildflower_outputs = [s[2] for s in migration_module.PRODUCT_WORKFLOWS["Wildflower gin"][1]]
    solstice_outputs = [s[2] for s in migration_module.PRODUCT_WORKFLOWS["Solstice gin"][1]]
    assert wildflower_outputs[-1] == "Wildflower - final product"
    assert solstice_outputs[-1] == "Solstice - final product"
    # Bottling's own output name is shared/generic -- what matters is the two
    # workflows' distinguishing final-product names above.
    assert wildflower_outputs[3] == solstice_outputs[3] == "Bottled product"


def test_distilling_and_aging_steps_from_index_1_wire_to_the_previous_step_output(migration_module):
    """Steps 2-5 (Distilling through Labelling) each carry a `_wire_previous_output`
    marker -- setup_product_workflows() resolves it into a real source_output_id once
    the preceding step's output actually exists in the database."""
    for workflow_name in ("Wildflower gin", "Solstice gin"):
        _shape, steps = migration_module.PRODUCT_WORKFLOWS[workflow_name]
        for step in steps[1:]:
            markers = [i for i in step[4] if i.get("_wire_previous_output")]
            assert markers, f"{workflow_name}'s {step[0]!r} step should wire the previous step's output"


def test_aging_has_the_vat_fill_ngs_and_water_inputs(migration_module):
    for workflow_name, expected_ngs, expected_water in (
        ("Wildflower gin", "25.326", "30.787"),
        ("Solstice gin", "17.776", "25.064"),
    ):
        _shape, steps = migration_module.PRODUCT_WORKFLOWS[workflow_name]
        aging = next(s for s in steps if s[0] == "Aging")
        by_name = {i["name"]: i for i in aging[4] if "name" in i}
        assert by_name["Neutral grain spirit"]["quantity"] == expected_ngs
        assert by_name["Neutral grain spirit"]["requires_inventory_selection"] is True
        assert by_name["Water"]["quantity"] == expected_water
        assert by_name["Water"]["requires_inventory_selection"] is False


def test_wildflower_and_solstice_carry_the_agreed_traceability_prompts(migration_module):
    for workflow_name in ("Wildflower gin", "Solstice gin"):
        _shape, steps = migration_module.PRODUCT_WORKFLOWS[workflow_name]
        by_name = {s[0]: s for s in steps}
        aging_prompts = by_name["Aging"][5]
        assert len(aging_prompts) == 1
        assert aging_prompts[0] == {"label": "VAT number", "type": "number", "unit": None, "required": True}
        distilling_prompts = by_name["Distilling"][5]
        assert len(distilling_prompts) == 1
        assert distilling_prompts[0] == {"label": "Flask code", "type": "text", "unit": None, "required": True}
        expected_batch_prompt = {"label": "Batch number", "type": "text", "unit": None, "required": True}
        assert by_name["Bottling"][5] == (expected_batch_prompt,)
        assert by_name["Labelling & packaging"][5] == (expected_batch_prompt,)
        assert by_name["Maceration"][5] == ()


def test_required_prompt_repair_preserves_unrelated_prompts(migration_module):
    existing = [
        {"label": "Batch number", "type": "text", "unit": None, "required": False},
        {"label": "Operator initials", "type": "text", "unit": None, "required": True},
    ]

    repaired = migration_module._merge_required_execution_prompts(existing, (migration_module._BATCH_NUMBER_PROMPT,))

    assert repaired == [
        {"label": "Batch number", "type": "text", "unit": None, "required": True},
        {"label": "Operator initials", "type": "text", "unit": None, "required": True},
    ]


def test_resolve_step_inputs_expands_the_previous_output_marker(migration_module):
    marker = migration_module._previous_step_output_input("3.6", "L")
    previous_output = {"id": "output-uuid-1", "name": "Maceration charge", "unit": "L"}
    resolved = migration_module._resolve_step_inputs((marker,), previous_output)
    assert resolved == [
        {
            "name": "Maceration charge",
            "source_output_id": "output-uuid-1",
            "quantity": "3.6",
            "unit": "L",
            "requires_inventory_selection": True,
            "is_variable": False,
        }
    ]


def test_resolve_step_inputs_raises_without_a_previous_output(migration_module):
    marker = migration_module._previous_step_output_input(None, "units")
    with pytest.raises(ValueError, match="previous step has no output"):
        migration_module._resolve_step_inputs((marker,), None)


def test_maceration_inputs_cover_the_tracked_botanicals_and_dont_fabricate_quantities(migration_module):
    wildflower = migration_module.PRODUCT_WORKFLOWS["Wildflower gin"][1][0][4]
    solstice = migration_module.PRODUCT_WORKFLOWS["Solstice gin"][1][0][4]
    rosella = migration_module.PRODUCT_WORKFLOWS["Rosella gin"][1][0][4]

    wildflower_by_name = {i["name"]: i for i in wildflower}
    assert wildflower_by_name["Juniper Berries (Macedonian)"]["requires_inventory_selection"] is True
    assert wildflower_by_name["Juniper Berries (Macedonian)"]["quantity"] == "59.4"
    assert wildflower_by_name["Lemon juice"]["requires_inventory_selection"] is False

    solstice_by_name = {i["name"]: i for i in solstice}
    assert solstice_by_name["Szechuan pepper"]["requires_inventory_selection"] is True
    assert solstice_by_name["Kawakawa leaf"]["requires_inventory_selection"] is False

    # Rosella's base VAT and rhubarb have no fixed per-batch quantity on record -- never
    # fabricate one (WB-018's policy), the template only marks whether it's selectable.
    rosella_by_name = {i["name"]: i for i in rosella}
    assert rosella_by_name["VAT batch"]["requires_inventory_selection"] is True
    assert rosella_by_name["VAT batch"]["quantity"] is None
    assert rosella_by_name["Rhubarb"]["requires_inventory_selection"] is False
    assert rosella_by_name["Rhubarb"]["quantity"] is None

    # Every input must carry a name/unit and an explicit selectability flag -- the shape
    # Step.inputs and the execution-recording UI both expect (app/core/db/models/step.py).
    for inputs in (wildflower, solstice, rosella):
        for item in inputs:
            assert item["name"] and item["unit"]
            assert isinstance(item["requires_inventory_selection"], bool)


# --- raw-material disambiguation ---------------------------------------------


def test_reused_supplier_batches_are_disambiguated_without_losing_source_code(migration_module):
    first = migration_module.RawMaterialRecord(
        source_table="purchases_ingredients",
        source_id=1,
        source_date=date(2024, 1, 1),
        name="Juniper",
        quantity=migration_module.Decimal("100"),
        unit="g",
        supplier="Supplier",
        supplier_batch_number="JB001",
        expiry_date=None,
        extra_data={},
    )
    second = migration_module.RawMaterialRecord(**{**first.__dict__, "source_id": 2, "source_date": date(2024, 2, 1)})

    result = migration_module._disambiguate_reused_supplier_batches([first, second])

    assert result[0].supplier_batch_number != result[1].supplier_batch_number
    assert "legacy" not in result[1].supplier_batch_number.lower()
    assert result[0].extra_data["recorded_supplier_batch_number"] == "JB001"
    assert result[1].extra_data["recorded_supplier_batch_number"] == "JB001"


# --- manifest ----------------------------------------------------------------


def _write_manifest(tmp_path: Path, records: list[dict], excluded: list[dict] | None = None) -> Path:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"records": records, "excluded": excluded or []}), encoding="utf-8")
    return manifest_path


def _solstice_batch(**overrides) -> dict:
    record = {
        "global_vat": 28,
        "batch_label": "VAT28",
        "product": "solstice",
        "steps": {
            "maceration": {"date": None, "confidence": "derived"},
            "distilling": {"date": None, "confidence": "derived"},
            "aging": {"date": "2025-06-25", "confidence": "clean"},
            "bottling": {"date": "2025-07-23", "confidence": "resolved_by_context"},
            "labelling": {"date": None, "confidence": "derived"},
        },
        "bottlings": [{"date": "2025-07-23", "bottles": "56.5", "sheet_row": 1206}],
        "vat_volume_l": "40",
    }
    record.update(overrides)
    return record


def test_load_manifest_parses_the_per_batch_shape(migration_module, tmp_path):
    manifest_path = _write_manifest(tmp_path, [_solstice_batch()])
    batches, excluded = migration_module._load_manifest(manifest_path)
    assert not excluded
    (batch,) = batches
    assert batch.global_vat == 28
    assert batch.product_line == "solstice"
    assert batch.workflow_name == "Solstice gin"
    assert batch.steps["aging"].step_date == date(2025, 6, 25)
    assert batch.steps["maceration"].step_date is None
    assert batch.bottlings[0]["bottles"] == "56.5000"


def test_manifest_marks_any_rosella_base_vat_as_diverted_wip(migration_module, tmp_path):
    rosella = {
        "global_vat": 1028,
        "batch_label": "VAT28",
        "product": "rosella",
        "rosella_base_vat": 28,
        "steps": {
            "rhubarb_maceration": {"date": "2025-07-24", "confidence": "clean"},
            "aging": {"date": "2025-07-24", "confidence": "derived"},
            "bottling": {"date": "2025-07-24", "confidence": "derived"},
            "labelling": {"date": "2025-07-24", "confidence": "derived"},
        },
        "bottlings": [],
    }

    batches, excluded = migration_module._load_manifest(_write_manifest(tmp_path, [_solstice_batch(), rosella]))

    assert not excluded
    assert batches[0].extra_data["diverted_to"] == "VAT28"


def test_load_manifest_excludes_unresolved_step_confidence(migration_module, tmp_path):
    bad = _solstice_batch()
    bad["steps"]["bottling"] = {"date": "2025-07-23", "confidence": "unresolved"}
    manifest_path = _write_manifest(tmp_path, [bad])
    batches, excluded = migration_module._load_manifest(manifest_path)
    assert batches == []
    assert "unresolved step dates" in excluded[0]["reason"]


def test_load_manifest_honours_an_explicit_exclude_flag(migration_module, tmp_path):
    manifest_path = _write_manifest(tmp_path, [_solstice_batch(exclude=True, notes="founder investigating")])
    batches, excluded = migration_module._load_manifest(manifest_path)
    assert batches == []
    assert excluded[0]["reason"] == "founder investigating"


def test_load_manifest_marks_a_pending_step_without_requiring_a_date(migration_module, tmp_path):
    in_progress = _solstice_batch(
        steps={
            "maceration": {"date": "2026-09-01", "confidence": "clean"},
            "distilling": {"date": "2026-09-03", "confidence": "clean"},
            "aging": {"date": "2026-09-08", "confidence": "clean"},
            "bottling": {"pending": True},
            "labelling": {"pending": True},
        },
        bottlings=[],
    )
    manifest_path = _write_manifest(tmp_path, [in_progress])

    batches, excluded = migration_module._load_manifest(manifest_path)

    assert not excluded
    (batch,) = batches
    assert batch.pending_steps == frozenset({"bottling", "labelling"})
    assert "bottling" not in batch.steps
    assert "labelling" not in batch.steps
    assert batch.steps["distilling"].step_date == date(2026, 9, 3)
    assert batch.bottlings == ()


def test_load_manifest_rejects_a_pending_step_that_isnt_a_suffix(migration_module, tmp_path):
    bad = _solstice_batch(
        steps={
            "maceration": {"date": "2026-09-01", "confidence": "clean"},
            "distilling": {"pending": True},
            "aging": {"date": "2026-09-08", "confidence": "clean"},
            "bottling": {"date": None, "confidence": "derived"},
            "labelling": {"date": None, "confidence": "derived"},
        }
    )
    manifest_path = _write_manifest(tmp_path, [bad])

    with pytest.raises(ValueError, match="pending steps must be a suffix"):
        migration_module._load_manifest(manifest_path)


def test_merge_batches_only_fills_missing_steps_on_a_prior_database_batch(migration_module, tmp_path):
    batch_step = migration_module.BatchStep
    production_batch = migration_module.ProductionBatch
    legacy = {
        24: production_batch(
            global_vat=24,
            product_line="wildflower",
            batch_label="WBWF24",
            steps={
                "maceration": batch_step("maceration", date(2025, 4, 23), "clean"),
                "distilling": batch_step("distilling", date(2025, 4, 23), "clean"),
                "aging": batch_step("aging", date(2025, 4, 23), "clean"),
                "bottling": batch_step("bottling", None, "derived"),
                "labelling": batch_step("labelling", None, "derived"),
            },
            vat_volume_l=migration_module.Decimal("54.6"),
            vat_abv=migration_module.Decimal("44"),
            bottlings=(),
            ingredient_codes=(),
            base_vat=None,
            extra_data={},
        )
    }
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "global_vat": 24,
                "batch_label": "VAT24",
                "product": "wildflower",
                "steps": {
                    "maceration": {"date": "2000-01-01", "confidence": "clean"},  # must NOT override
                    "bottling": {"date": "2025-05-22", "confidence": "clean"},
                    "labelling": {"date": None, "confidence": "derived"},
                },
                "bottlings": [{"date": "2025-05-22", "bottles": "77", "sheet_row": 1080}],
            }
        ],
    )
    manifest_batches, _ = migration_module._load_manifest(manifest_path)
    (merged,) = migration_module._merge_batches(legacy, manifest_batches)
    assert merged.steps["maceration"].step_date == date(2025, 4, 23)  # kept from prior database
    assert merged.steps["bottling"].step_date == date(2025, 5, 22)  # filled from manifest
    assert merged.bottlings[0]["bottles"] == "77.0000"


def test_merge_batches_adds_a_wholly_new_vat(migration_module, tmp_path):
    manifest_path = _write_manifest(tmp_path, [_solstice_batch()])
    manifest_batches, _ = migration_module._load_manifest(manifest_path)
    merged = migration_module._merge_batches({}, manifest_batches)
    assert [b.global_vat for b in merged] == [28]


def test_curated_manifest_in_docs_loads_and_every_step_is_resolved(migration_module):
    manifest_path = Path(__file__).parents[1] / "docs" / "whistlebird-production-sheet-source.json"
    batches, _excluded = migration_module._load_manifest(manifest_path)
    assert len(batches) >= 20
    for batch in batches:
        for step in batch.steps.values():
            assert step.confidence in migration_module.STEP_DATE_CONFIDENCE


def test_curated_manifest_includes_the_documented_green_gold_vat53_diversion(migration_module):
    manifest_path = Path(__file__).parents[1] / "docs" / "whistlebird-production-sheet-source.json"
    (record,) = migration_module._load_green_gold_records(manifest_path)

    assert record.marker == "green-gold-gg01"
    assert record.workflow_name == "Green Gold Gin Liqueur"
    assert record.source_vat == 53
    assert record.source_date == date(2026, 7, 31)
    assert record.source_quantity_l == migration_module.Decimal("35.875")
    assert record.bottles == migration_module.Decimal("126")
    assert record.bottle_size_ml == migration_module.Decimal("500")


def _stub_batch(workflow_name, pending=()):
    from types import SimpleNamespace

    return SimpleNamespace(workflow_name=workflow_name, pending_steps=frozenset(pending))


def test_expected_executions_count_green_gold_only_on_the_api_replay_path(migration_module):
    manifest_path = Path(__file__).parents[1] / "docs" / "whistlebird-production-sheet-source.json"
    records = migration_module._load_green_gold_records(manifest_path)
    batches = [_stub_batch("Wildflower gin"), _stub_batch("Wildflower gin", pending=("bottling",))]

    api_replay = migration_module._expected_workflow_executions(batches, records, api_replay=True)
    orm_direct = migration_module._expected_workflow_executions(batches, records, api_replay=False)

    assert api_replay["Green Gold Gin Liqueur"] == 1, "the API replay loads the documented VAT53 diversion"
    assert api_replay["Wildflower gin"] == 2, "the API replay also loads the in-progress batch"
    assert orm_direct["Green Gold Gin Liqueur"] == 0, "the ORM-direct rebuild has no Green Gold path"
    assert orm_direct["Wildflower gin"] == 1, "the ORM-direct rebuild skips the in-progress batch"


# --- tenant guards ---------------------------------------------------------------


def test_scoped_reset_deletes_dependent_tenant_data_before_its_parents(migration_module):
    """A deterministic replay cannot leave tenant-local references to old stock/cases."""
    reset_tables = migration_module.RESET_TABLES

    assert reset_tables.index("crm_sales_fifo_allocations") < reset_tables.index("xero_invoices")
    assert reset_tables.index("crm_sales_fifo_allocations") < reset_tables.index("inventory_items")
    assert reset_tables.index("core_tasks") < reset_tables.index("task_board_lanes")
    assert reset_tables.index("operational_case_events") < reset_tables.index("operational_case_links")
    assert reset_tables.index("operational_case_links") < reset_tables.index("operational_cases")
    assert reset_tables.index("operational_case_events") < reset_tables.index("entity_events")
    assert "core_task_configs" in reset_tables
    assert "system_findings_cache" in reset_tables


@pytest.mark.parametrize(
    "call",
    [
        lambda m: m.reset_target_org("postgresql://unused", "another_tenant"),
        lambda m: m.setup_product_workflows("postgresql://unused", "another_tenant"),
        lambda m: m.apply_raw_material_inventory("postgresql://u", "postgresql://u", "another_tenant"),
        lambda m: m.apply_production_batches("postgresql://u", "postgresql://u", "another_tenant", None),
        lambda m: m.apply_trial_batches("postgresql://u", "postgresql://u", "another_tenant"),
        lambda m: m.apply_customs_lodgements("postgresql://u", "postgresql://u", "another_tenant"),
        lambda m: m.ensure_compliant_nz_alcohol_setup("postgresql://unused", "another_tenant"),
    ],
)
def test_write_actions_reject_any_tenant_except_whistlebird_org(migration_module, call):
    with pytest.raises(ValueError, match="only permitted"):
        call(migration_module)


def test_tenant_setup_rejects_any_tenant_except_whistlebird_org(migration_module):
    with pytest.raises(ValueError, match="only permitted"):
        migration_module.ensure_target_org_admin(
            "postgresql://unused", "another_tenant", "admin@example.test", "not-used"
        )


def test_bootstrap_rejects_any_tenant_except_whistlebird_org(migration_module, tmp_path):
    with pytest.raises(ValueError, match="only permitted"):
        migration_module.bootstrap_whistlebird(
            "postgresql://unused",
            "postgresql://unused",
            "another_tenant",
            "admin@example.test",
            "not-used",
            tmp_path / "manifest.json",
        )


def test_target_tenant_scope_is_active_only_for_target_orm_work(migration_module):
    from contextlib import ExitStack

    from app.core.security.tenant_scope import get_current_org_id

    org = SimpleNamespace(id=uuid4())

    class Query:
        def filter(self, *_args):
            return self

        def one_or_none(self):
            return org

    class Session:
        def query(self, *_args):
            return Query()

    scope = ExitStack()
    assert get_current_org_id() is None
    assert migration_module._enter_target_tenant_scope(scope, Session(), "another_bize_org") is org
    assert get_current_org_id() == org.id
    scope.close()
    assert get_current_org_id() is None


# --- bootstrap orchestration ---------------------------------------------------


def test_bootstrap_runs_preflight_then_scoped_replay_then_verify(migration_module, monkeypatch, tmp_path):
    calls = []

    def record(name, result):
        def operation(*_args, **_kwargs):
            calls.append(name)
            return result

        return operation

    matching_verification = {
        "raw_material_items": {"expected": 1, "actual": 1},
        "batch_executions": {"Wildflower gin": {"expected": 1, "actual": 1}},
        "customs_lodgements": {"expected": 1, "actual": 1},
        "incomplete_batch_steps": {"expected": 0, "actual": 0},
        "date_mismatches": {"step_dates": 0, "steps_stamped_on_run_date": 0},
        "wording_leaks": {"process_names": 0, "step_names": 0},
    }
    monkeypatch.setattr(migration_module, "build_core_dry_run", record("dry_core", {"dry_run": True}))
    monkeypatch.setattr(migration_module, "build_production_dry_run", record("dry_production", {"dry_run": True}))
    monkeypatch.setattr(migration_module, "build_manifest_dry_run", record("dry_manifest", {"dry_run": True}))
    monkeypatch.setattr(
        migration_module, "ensure_target_org_admin", record("ensure", {"org_created": True, "admin_created": True})
    )
    monkeypatch.setattr(
        migration_module, "sync_whistlebird_admin_password", record("password_sync", {"synced": True})
    )
    monkeypatch.setattr(migration_module, "reset_target_org", record("reset", {"deleted_rows": {}}))
    monkeypatch.setattr(migration_module, "setup_product_workflows", record("workflows", {}))
    monkeypatch.setattr(migration_module, "apply_raw_material_inventory", record("raw_materials", {}))
    monkeypatch.setattr(migration_module, "apply_production_batches", record("batches", {}))
    monkeypatch.setattr(migration_module, "apply_trial_batches", record("trials", {}))
    monkeypatch.setattr(migration_module, "apply_customs_lodgements", record("customs", {}))
    monkeypatch.setattr(migration_module, "build_import_verification", record("verify_load", matching_verification))
    monkeypatch.setattr(migration_module, "build_manifest_verification", record("verify_manifest", {}))
    monkeypatch.setattr(
        migration_module,
        "ensure_compliant_nz_alcohol_setup",
        record("compliant", {"feature_key": "compliant", "active": True}),
    )

    migration_module.bootstrap_whistlebird(
        "legacy-url", "target-url", "Whistlebird Ltd", "admin@example.test", "safe-password", tmp_path / "m.json"
    )

    assert calls == [
        "dry_core",
        "dry_production",
        "dry_manifest",
        "ensure",
        "password_sync",
        "reset",
        "workflows",
        "raw_materials",
        "batches",
        "trials",
        "customs",
        "verify_load",
        "verify_manifest",
        "compliant",
    ]


def test_bootstrap_rejects_mismatched_verification(migration_module):
    with pytest.raises(RuntimeError, match="verification failed"):
        migration_module._require_matching_import(
            {"raw_material_items": {"expected": 71, "actual": 0}}, "Production history load"
        )


def test_bootstrap_rejects_a_wording_leak(migration_module):
    with pytest.raises(RuntimeError, match="verification failed"):
        migration_module._require_matching_import({"wording_leaks": {"process_names": 1}}, "Production history load")


# --- argument parsing ----------------------------------------------------------


def test_arguments_reject_ambiguous_actions(migration_module, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "whistlebird_migration.py",
            "--target-url",
            "postgresql://unused",
            "--legacy-url",
            "postgresql://unused",
            "--dry-run-core",
            "--dry-run-production",
        ],
    )
    with pytest.raises(SystemExit):
        migration_module._arguments()


def test_arguments_reject_wrong_tenant_before_any_database_work(migration_module, monkeypatch):
    monkeypatch.setenv("WHISTLEBIRD_ADMIN_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "whistlebird_migration.py",
            "--target-url",
            "postgresql://unused",
            "--ensure-whistlebird-org",
            "--org-name",
            "another_tenant",
        ],
    )
    with pytest.raises(SystemExit):
        migration_module._arguments()
