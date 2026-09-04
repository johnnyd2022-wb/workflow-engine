"""Focused tests for the safe, reusable Whistlebird migration primitives."""

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


def test_derived_timestamp_uses_agreed_nz_noon(migration_module):
    assert migration_module._derived_timestamp(date(2025, 6, 15)) == datetime(2025, 6, 15, 0, 0, tzinfo=UTC)


def test_decimal_rejects_negative_legacy_quantities(migration_module):
    with pytest.raises(ValueError, match="invalid quantity"):
        migration_module._decimal(-1, "quantity", "legacy_table", 42)


def test_reset_rejects_any_tenant_except_whistlebird_test(migration_module):
    with pytest.raises(ValueError, match="only permitted"):
        migration_module.reset_target_org("postgresql://unused", "another_tenant")


def test_tenant_setup_rejects_any_tenant_except_whistlebird_test(migration_module):
    with pytest.raises(ValueError, match="only permitted"):
        migration_module.ensure_target_org_admin(
            "postgresql://unused", "another_tenant", "admin@example.test", "not-used"
        )


def test_target_tenant_scope_is_active_only_for_target_orm_work(migration_module):
    """Standalone migration ORM work must not fall through to tenant_filter.no_context."""
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


def test_bootstrap_rejects_any_tenant_except_whistlebird_test(migration_module, tmp_path):
    with pytest.raises(ValueError, match="only permitted"):
        migration_module.bootstrap_whistlebird_test(
            "postgresql://unused",
            "postgresql://unused",
            "another_tenant",
            "admin@example.test",
            "not-used",
            tmp_path / "manifest.json",
        )


def test_bootstrap_runs_preflight_before_scoped_replay(migration_module, monkeypatch, tmp_path):
    calls = []

    def record(name, result):
        def operation(*_args):
            calls.append(name)
            return result

        return operation

    monkeypatch.setattr(migration_module, "build_core_dry_run", record("dry_core", {"dry_run": True}))
    monkeypatch.setattr(migration_module, "build_production_dry_run", record("dry_production", {"dry_run": True}))
    monkeypatch.setattr(migration_module, "build_traceability_dry_run", record("dry_traceability", {"dry_run": True}))
    monkeypatch.setattr(migration_module, "build_production_sheet_dry_run", record("dry_sheet", {"dry_run": True}))
    monkeypatch.setattr(
        migration_module, "ensure_target_org_admin", record("ensure", {"org_created": True, "admin_created": True})
    )
    monkeypatch.setattr(migration_module, "reset_target_org", record("reset", {"deleted_rows": {}}))
    monkeypatch.setattr(migration_module, "setup_historical_process_templates", record("templates", {}))
    monkeypatch.setattr(migration_module, "apply_core_receipts_and_lodgements", record("core", {}))
    monkeypatch.setattr(migration_module, "apply_evidenced_production", record("production", {}))
    monkeypatch.setattr(migration_module, "apply_sample_history", record("samples", {}))
    monkeypatch.setattr(migration_module, "apply_production_sheet", record("sheet", {}))
    matching_import = {
        "inventory": {"purchases_gns": {"expected": 1, "actual": 1}},
        "samples": {},
        "customs_lodgements": {"expected": 1, "actual": 1},
        "date_mismatches": {"inventory": 0, "execution_steps": 0},
    }
    matching_sheet = {
        "by_record_type": {"bottling": {"expected": 1, "actual": 1}},
        "date_mismatches": 0,
    }
    monkeypatch.setattr(migration_module, "build_import_verification", record("verify_import", matching_import))
    monkeypatch.setattr(migration_module, "build_production_sheet_verification", record("verify_sheet", matching_sheet))

    migration_module.bootstrap_whistlebird_test(
        "legacy-url",
        "target-url",
        "whistlebird_test",
        "admin@example.test",
        "safe-password",
        tmp_path / "manifest.json",
    )

    assert calls == [
        "dry_core",
        "dry_production",
        "dry_traceability",
        "dry_sheet",
        "ensure",
        "reset",
        "templates",
        "core",
        "production",
        "samples",
        "sheet",
        "verify_import",
        "verify_sheet",
    ]


def test_bootstrap_rejects_mismatched_verification(migration_module):
    with pytest.raises(RuntimeError, match="verification failed"):
        migration_module._require_matching_import(
            {"inventory": {"purchases_gns": {"expected": 1, "actual": 0}}}, "Legacy import"
        )


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
    monkeypatch.setenv("WHISTLEBIRD_TEST_ADMIN_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "whistlebird_migration.py",
            "--target-url",
            "postgresql://unused",
            "--ensure-test-tenant",
            "--org-name",
            "another_tenant",
        ],
    )

    with pytest.raises(SystemExit):
        migration_module._arguments()


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
    second = migration_module.ReceiptSourceRecord(**{**first.__dict__, "legacy_id": 2, "legacy_date": date(2024, 2, 1)})

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
    manifest_path = _write_manifest(tmp_path, [_sample_record(id=1786, input_references=[["vat_batch", "VAT48"]])])

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
