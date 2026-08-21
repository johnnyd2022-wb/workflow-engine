"""Focused tests for the safe, reusable Whistlebird migration primitives."""

import importlib.util
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
