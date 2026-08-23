"""Focused tests for the safe, reusable Whistlebird migration primitives."""

import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

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


def test_derived_timestamp_uses_agreed_nz_noon(migration_module):
    assert migration_module._derived_timestamp(date(2025, 6, 15)) == datetime(2025, 6, 15, 0, 0, tzinfo=UTC)


def test_decimal_rejects_negative_legacy_quantities(migration_module):
    with pytest.raises(ValueError, match="invalid quantity"):
        migration_module._decimal(-1, "quantity", "legacy_table", 42)


def test_reset_rejects_any_tenant_except_whistlebird_test(migration_module):
    with pytest.raises(ValueError, match="only permitted"):
        migration_module.reset_target_org("postgresql://unused", "another_tenant")


def test_reused_supplier_batches_are_disambiguated_without_losing_source_code(migration_module):
    first = migration_module.ReceiptSourceRecord(
        legacy_table="purchases_ingredients",
        legacy_id=1,
        legacy_date=date(2024, 1, 1),
        name="Juniper",
        quantity=migration_module.Decimal("100"),
        unit="g",
        supplier="Supplier",
        supplier_batch_number="JB001",
        expiry_date=None,
        process_name="Legacy ingredient receipt",
        extra_data={},
    )
    second = migration_module.ReceiptSourceRecord(
        **{**first.__dict__, "legacy_id": 2, "legacy_date": date(2024, 2, 1)}
    )

    result = migration_module._disambiguate_reused_supplier_batches([first, second])

    assert result[0].supplier_batch_number != result[1].supplier_batch_number
    assert result[0].extra_data["legacy_supplier_batch_number"] == "JB001"
    assert result[1].extra_data["legacy_supplier_batch_number"] == "JB001"


def _write_manifest(tmp_path: Path, records: list[dict], excluded: list[dict] | None = None) -> Path:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"records": records, "excluded": excluded or []}), encoding="utf-8")
    return manifest_path


def _sample_record(**overrides) -> dict:
    record = {
        "id": 1936,
        "record_type": "bottling",
        "process_name": "Sheet: bottling",
        "product_line": "wildflower",
        "batch_label": "VAT47",
        "legacy_date": "2026-05-07",
        "date_confidence": "resolved_by_context",
        "quantity": "78.5",
        "unit": "units",
        "input_references": [],
        "linked_legacy_source": None,
        "notes": "test record",
    }
    record.update(overrides)
    return record


def test_production_sheet_records_parses_a_valid_manifest(migration_module, tmp_path):
    manifest_path = _write_manifest(tmp_path, [_sample_record()])

    records = migration_module._production_sheet_records(manifest_path)

    assert len(records) == 1
    assert records[0].manifest_id == 1936
    assert records[0].batch_label == "VAT47"
    assert records[0].legacy_date == date(2026, 5, 7)
    assert records[0].quantity == migration_module.Decimal("78.5000")


def test_production_sheet_records_rejects_unresolved_date_confidence(migration_module, tmp_path):
    manifest_path = _write_manifest(tmp_path, [_sample_record(date_confidence="unresolved")])

    with pytest.raises(ValueError, match="unresolved date_confidence"):
        migration_module._production_sheet_records(manifest_path)


def test_production_sheet_records_parses_input_references(migration_module, tmp_path):
    manifest_path = _write_manifest(
        tmp_path, [_sample_record(id=1786, input_references=[["vat_batch", "VAT48"]])]
    )

    records = migration_module._production_sheet_records(manifest_path)

    assert records[0].input_references == (("vat_batch", "VAT48"),)


def test_production_sheet_provenance_uses_distinct_source_system(migration_module):
    record = migration_module.ProductionSheetRecord(
        manifest_id=1936,
        record_type="bottling",
        process_name="Sheet: bottling",
        product_line="wildflower",
        batch_label="VAT47",
        legacy_date=date(2026, 5, 7),
        date_confidence="resolved_by_context",
        quantity=migration_module.Decimal("78.5"),
        unit="units",
        input_references=(),
        linked_legacy_source=None,
        notes="",
    )

    provenance = migration_module._production_sheet_provenance(record)

    assert provenance["source_system"] == "whistlebird_production_sheet"
    assert provenance["legacy_source"] == {"table": "production_sheet", "id": 1936}
    assert provenance["date_confidence"] == "resolved_by_context"


def test_apply_production_sheet_rejects_any_tenant_except_whistlebird_test(migration_module, tmp_path):
    manifest_path = _write_manifest(tmp_path, [_sample_record()])

    with pytest.raises(ValueError, match="only permitted"):
        migration_module.apply_production_sheet(manifest_path, "postgresql://unused", "another_tenant")


def test_curated_production_sheet_manifest_loads_without_error(migration_module):
    manifest_path = Path(__file__).parents[1] / "docs" / "whistlebird-production-sheet-source.json"

    records = migration_module._production_sheet_records(manifest_path)

    assert len(records) >= 1
    assert all(record.date_confidence in migration_module.PRODUCTION_SHEET_DATE_CONFIDENCE for record in records)
