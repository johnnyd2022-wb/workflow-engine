"""Fast contract tests for the install-time NZ Alcohol module catalogue."""

from types import SimpleNamespace
from uuid import uuid4

from app.features.compliance_checks.routes.corechecks import CoreChecksRunner
from app.features.compliant.frameworks import NZ_ALCOHOL_FRAMEWORKS, framework_by_slug
from app.features.compliant.modules.nz_alcohol.catalogue import capture_requirements, framework_for_profile
from app.features.compliant.modules.nz_alcohol.councils import TRADE_WASTE_CATALOGUES
from app.features.compliant.registry import CHECK_ID
from app.features.compliant.service import build_priority_actions, calculate_customs_reconciliation


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
        # Trade waste is bound to a selected council during setup, not to a fictional
        # nationwide source.
        if framework["slug"] != "trade-waste":
            assert framework["source_url"].startswith("https://")


def test_trade_waste_catalogues_are_source_linked_and_bind_the_framework():
    trade_waste = framework_by_slug("trade-waste")
    assert trade_waste is not None
    assert {"auckland-watercare", "wellington-city", "christchurch", "hamilton", "dunedin"}.issubset(
        TRADE_WASTE_CATALOGUES
    )
    for catalogue in TRADE_WASTE_CATALOGUES.values():
        assert catalogue["source_url"].startswith("https://")
        assert catalogue["version"]
        assert catalogue["controls"]
    bound = framework_for_profile(trade_waste, {"trade_waste_council": "auckland-watercare"})
    assert bound["source_url"] == TRADE_WASTE_CATALOGUES["auckland-watercare"]["source_url"]


def test_control_capture_contract_enforces_essential_proof_without_generic_json():
    assert capture_requirements("customs-alcohol", "period-lodgement") == {
        "record_types": ("lodgement",),
        "period": True,
        "evidence": True,
    }
    assert capture_requirements("trade-waste", "monitoring", {"require_core_source_refs": True})["source_refs"]


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
    assert result["unprofiled_inventory_names"] == ["Unmapped RTD"]
    assert result["unsupported_inventory_units"] == ["Gin (kg)"]


def test_priority_actions_lead_with_live_value_then_the_smallest_evidence_gaps():
    first_run = build_priority_actions(None, [], {})
    assert first_run[0]["kind"] == "profile"

    profile = SimpleNamespace(enabled=True, settings={"alcohol_product_types": ["spirits"]})
    frameworks = [
        {
            "name": "Customs alcohol reconciliation",
            "slug": "customs-alcohol",
            "controls": [
                {
                    "control_id": "period-lodgement",
                    "state": "setup",
                    "reason": "Evidence or configuration required",
                    "description": "Record each lodgement period.",
                    "capture": {"period": True},
                },
                {
                    "control_id": "movement-evidence",
                    "state": "attention",
                    "reason": "Open or failed record",
                    "description": "Retain dispatch evidence.",
                    "capture": {"source_refs": True},
                },
            ],
        }
    ]

    actions = build_priority_actions(profile, frameworks, {"unprofiled_inventory_names": ["House Gin"]})

    assert actions[0]["kind"] == "product"
    assert actions[0]["suggestions"] == ["House Gin"]
    assert actions[1]["control_id"] == "movement-evidence"
