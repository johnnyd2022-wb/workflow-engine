"""Fast contract tests for the install-time NZ Alcohol module catalogue."""

from types import SimpleNamespace
from uuid import uuid4

from app.core.backend.corechecks import CoreChecksRunner
from app.features.compliant.frameworks import NZ_ALCOHOL_FRAMEWORKS, framework_by_slug
from app.features.compliant.registry import CHECK_ID
from app.features.compliant.service import calculate_customs_reconciliation


def test_nz_alcohol_catalog_covers_the_primary_production_types():
    np3 = framework_by_slug("np3-food-control")
    wine = framework_by_slug("wine-standards")
    customs = framework_by_slug("customs-alcohol")

    assert np3 is not None and {"beer", "spirits", "cider", "mead", "rtd"}.issubset(np3["applies_to"])
    assert wine is not None and wine["applies_to"] == ("wine",)
    assert customs is not None and customs["applies_to"] == "all_alcohol"


def test_each_framework_has_versioned_official_source_metadata():
    for framework in NZ_ALCOHOL_FRAMEWORKS:
        assert framework["version"]
        assert framework["source_title"]
        # Trade waste is deliberately council-configured; the user must bind its
        # official bylaw/consent source during setup instead of inheriting fiction.
        if framework["slug"] != "trade-waste":
            assert framework["source_url"].startswith("https://")


def test_compliant_registers_through_the_public_core_check_seam():
    runner = CoreChecksRunner(org_id=uuid4(), session=None)
    assert CHECK_ID in runner._checks


def test_customs_lal_calculation_is_exact_and_exposes_coverage_gaps():
    profiles = {"Gin": SimpleNamespace(abv_percent="40"), "Beer": SimpleNamespace(abv_percent="5")}
    movements = [
        (SimpleNamespace(movement_type="PRODUCTION", quantity="100", unit="L"), "Gin"),
        (SimpleNamespace(movement_type="PRODUCTION", quantity="50000", unit="mL"), "Beer"),
        (SimpleNamespace(movement_type="WASTAGE", quantity="2", unit="L"), "Gin"),
        (SimpleNamespace(movement_type="PRODUCTION", quantity="3", unit="kg"), "Gin"),
        (SimpleNamespace(movement_type="PRODUCTION", quantity="5", unit="L"), "Unmapped RTD"),
    ]

    result = calculate_customs_reconciliation(profiles, movements)

    assert result["production_litres_of_alcohol"] == "42.5000"
    assert result["wastage_litres_of_alcohol"] == "0.8000"
    assert result["unprofiled_movement_count"] == 1
    assert result["unsupported_unit_movement_count"] == 1
