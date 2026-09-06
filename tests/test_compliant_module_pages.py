"""Module navigation and NZ Alcohol applicability contracts."""

from pathlib import Path
from types import SimpleNamespace

from app.features.compliant.modules.nz_alcohol.catalogue import framework_applies
from app.features.compliant.modules.nz_alcohol.np3_audit import NP3_AUDIT_CATEGORIES, build_np3_audit_rows

ROOT = Path(__file__).resolve().parents[1]


def test_nz_alcohol_module_has_a_dedicated_page():
    """The module workspace is addressable independently of the Compliant index."""
    dashboard = (
        ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "dashboard.html"
    ).read_text(encoding="utf-8")
    configuration = (
        ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "configuration.html"
    ).read_text(encoding="utf-8")
    routes = (ROOT / "app" / "features" / "compliant" / "routes" / "page_routes.py").read_text(encoding="utf-8")
    assert 'route("/compliant/nz-alcohol"' in routes
    assert "COMPLIANT / NZ ALCOHOL" in dashboard
    assert "Food safety programme" in configuration
    assert "Liquor licence" in configuration


def test_complaint_spelling_redirects_to_the_compliant_workspace():
    routes = (ROOT / "app" / "features" / "compliant" / "routes" / "page_routes.py").read_text(encoding="utf-8")
    assert 'route("/complaint"' in routes
    assert 'redirect("/compliant", code=302)' in routes


def test_compliant_navigation_uses_full_documents_for_page_specific_assets():
    """Compliant CSS/JS are subscription-protected and only enter <head> on a full load."""
    tabs = (
        ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "_nz_alcohol_tabs.html"
    ).read_text(encoding="utf-8")
    audit = (
        ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "np3_audit.html"
    ).read_text(encoding="utf-8")
    sidebar = (ROOT / "app" / "ui" / "shared" / "sidebar-v2.html").read_text(encoding="utf-8")
    assert tabs.count('hx-boost="false"') == 3
    assert 'href="/compliant" hx-boost="false"' in sidebar
    assert 'href="/api/compliant/np3-audit?format=csv" hx-boost="false"' in audit


def test_selected_national_programme_is_the_only_programme_in_the_plan():
    settings = {"alcohol_product_types": ["beer"], "food_control_programme": "np2"}
    assert framework_applies(("national-programme-2", "beer"), settings, None)
    assert not framework_applies(("national-programme-1", "beer"), settings, None)
    assert not framework_applies(("national-programme-3", "beer"), settings, None)


def test_alcohol_licence_framework_requires_selected_licence_activity():
    assert not framework_applies("liquor-licence-required", {}, None)
    assert framework_applies("liquor-licence-required", {"liquor_licence_types": ["off"]}, None)


def test_np3_audit_register_covers_every_topic_from_the_verifier_checklist():
    records = [
        SimpleNamespace(
            control_id="registration-scope",
            status="complete",
            due_date=None,
            title="Current NP3 registration",
            evidence_reference="Registration certificate",
            created_at=None,
        )
    ]
    rows = build_np3_audit_rows(records)
    expected_count = sum(len(topics) for _category, topics in NP3_AUDIT_CATEGORIES)
    assert len(rows) == expected_count
    registration = next(row for row in rows if row["topic"] == "Registration / scope of operations")
    assert registration["state"] == "ready"
    assert registration["evidence_references"] == ["Registration certificate"]
    assert any(row["topic"] == "Food allergen management" for row in rows)
    assert any(row["topic"] == "Cleaning and sanitising" for row in rows)
