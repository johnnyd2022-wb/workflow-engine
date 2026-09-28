"""Module navigation and NZ Alcohol applicability contracts."""

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.features.compliance_checks.routes.corechecks import CheckResult
from app.features.compliance_checks.system_status import _signals_from_results
from app.features.compliant.modules.nz_alcohol.catalogue import control_reference, framework_applies
from app.features.compliant.modules.nz_alcohol.module import _np3_workspace_summary
from app.features.compliant.modules.nz_alcohol.np3_audit import (
    NP3_AUDIT_CATEGORIES,
    NP3_EVIDENCE_PLAYBOOKS,
    NP3_GUIDANCE_VERSION,
    build_np3_audit_rows,
    evidence_playbook,
    np3_log_template,
)
from app.features.compliant.modules.nz_alcohol.workflow_rules import rules_for_profile
from app.features.compliant.routes.page_routes import _food_safety_programme
from app.features.compliant.service import build_priority_actions, module_summary_health, np3_audit_coverage

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


def test_module_alert_contract_projects_into_the_generic_core_health_bar():
    signals = _signals_from_results(
        [
            CheckResult(
                check_id="example.module",
                flagged=True,
                data={
                    "system_finding": {
                        "category": "Example compliance",
                        "action": {"href": "/compliant/example", "label": "Open example"},
                    },
                    "system_alerts": [{"id": "example-overall"}, {"id": "example-action"}],
                },
            )
        ]
    )

    assert signals[-1] == {
        "type": "MODULE_SYSTEM_FINDING",
        "category": "module",
        "breach_type": "MODULE_REQUIREMENT",
        "has_issue": True,
        "in_active_use": False,
        "count": 2,
        "message": "Example compliance",
        "href": "/compliant/example",
        "action_label": "Open example",
    }


def test_np3_overview_coverage_uses_the_register_health_not_the_generic_catalogue():
    assert np3_audit_coverage({"ok": 4, "needs_attention": 34}) == {
        "current_controls": 4,
        "total_controls": 38,
        "percent": 11,
        "label": "NP3 audit evidence status",
    }


def test_module_summary_health_uses_one_consistent_card_contract():
    assert module_summary_health({"current_controls": 4, "total_controls": 38, "percent": 11}, overdue=2) == {
        "score": 11,
        "current_controls": 4,
        "total_controls": 38,
        "evidence_ready": 4,
        "needs_attention": 34,
        "overdue": 2,
    }


def test_np3_emits_the_dashboard_workspace_summary_contract():
    assert _np3_workspace_summary({"ok": 4, "needs_attention": 34, "overdue": 2}) == {
        "workspace": "compliant",
        "module_name": "NP3",
        "href": "/compliant/nz-alcohol/food-safety",
        "action_label": "Open NP3",
        "score": 11,
        "current_controls": 4,
        "total_controls": 38,
        "evidence_ready": 4,
        "needs_attention": 34,
        "overdue": 2,
    }


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
    # The Flask app's Jinja root is app/ui/templates.  Guard the template it actually
    # renders, rather than the separately served /ui/shared asset directory.
    sidebar = (ROOT / "app" / "ui" / "templates" / "shared" / "sidebar-v2.html").read_text(encoding="utf-8")
    assert tabs.count('hx-boost="false"') == 4
    assert 'href="/compliant" hx-boost="false"' in sidebar
    assert 'href="/api/compliant/np3-audit?format=csv" hx-boost="false"' in audit
    assert 'href="/api/compliant/np3-audit?format=pdf" hx-boost="false"' in audit


def test_food_safety_tab_tracks_the_configured_programme_and_has_np1_np2_placeholders():
    tabs = (
        ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "_nz_alcohol_tabs.html"
    ).read_text(encoding="utf-8")
    routes = (ROOT / "app" / "features" / "compliant" / "routes" / "page_routes.py").read_text(encoding="utf-8")
    configuration = (ROOT / "app" / "features" / "compliant" / "frontend" / "static" / "configuration.js").read_text(
        encoding="utf-8"
    )
    placeholder = (
        ROOT
        / "app"
        / "features"
        / "compliant"
        / "frontend"
        / "templates"
        / "compliant"
        / "food_safety_coming_soon.html"
    ).read_text(encoding="utf-8")

    assert _food_safety_programme({"food_control_programme": "np1"}) == "np1"
    assert _food_safety_programme({"food_control_programme": "np2"}) == "np2"
    assert _food_safety_programme({"food_control_programme": "unexpected"}) == "np3"
    assert 'href="/compliant/nz-alcohol/food-safety"' in tabs
    assert 'href="/compliant/nz-alcohol/customs"' in tabs
    assert "food_control_programme|upper" in tabs
    assert 'route("/compliant/nz-alcohol/food-safety"' in routes
    assert 'route("/compliant/nz-alcohol/customs"' in routes
    assert "updateFoodSafetyTab" in configuration
    assert "support is coming soon" in placeholder


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


def test_np3_audit_register_labels_live_core_evidence_and_does_not_hide_a_failure():
    derived = [
        {
            "control_id": "trace-and-recall",
            "title": "Core DAG trace across 2 final-product batches",
            "source_kind": "core-dag",
            "source_refs": ["core-final-product-id", "core-execution-step-id"],
            "observed_at": None,
            "detail": "Connected Core lineage.",
        }
    ]
    rows = build_np3_audit_rows([], derived)
    traceability = next(row for row in rows if row["control_id"] == "trace-and-recall")
    assert traceability["state"] == "ready"
    assert traceability["derived_evidence_count"] == 1
    assert traceability["derived_evidence"][0]["source_kind"] == "core-dag"

    failed_record = SimpleNamespace(
        control_id="trace-and-recall",
        status="failed",
        due_date=None,
        title="Open recall exercise",
        evidence_reference=None,
        created_at=None,
    )
    rows = build_np3_audit_rows([failed_record], derived)
    traceability = next(row for row in rows if row["control_id"] == "trace-and-recall")
    assert traceability["state"] == "attention"


def test_np3_controls_carry_a_guidance_mapping_for_an_auditor_to_check():
    """Plain-language evidence prompts must remain tied to an official NP3 topic."""
    assert (
        control_reference("np3-food-control", "trace-and-recall")
        == "Sourcing, receiving and tracing food; Recalling food"
    )
    assert control_reference("np3-food-control", "cleaning-and-hygiene") == "Cleaning and sanitising"
    assert control_reference("customs-alcohol", "reconciliation") is None


def test_np3_mindmap_gaps_are_explicit_controls_with_audit_ready_registers():
    """Water and preservation controls must not disappear into a generic hazard note."""
    water = evidence_playbook("water-supply")
    assert water["page"] == 21
    assert water["log_template"]["key"] == "water_check"
    assert any("self-supply" in note.lower() for note in water["reference_notes"])
    assert np3_log_template("maintenance")["key"] == "maintenance_check"
    assert np3_log_template("unsafe-unsuitable-food")["key"] == "unsafe_food_incident"
    assert evidence_playbook("water-activity-control")["page"] == 55
    assert evidence_playbook("acidification-fermentation-control")["page"] == 57


def test_np3_labelling_check_captures_pre_visit_alcohol_label_evidence():
    labels = evidence_playbook("food-labelling-advertising")
    assert labels["page"] == 61
    assert {field["key"] for field in labels["fields"]} >= {
        "label_or_artwork",
        "label_requirements_check",
        "pre_visit_submission_reference",
    }
    assert any("pregnancy warning" in note.lower() for note in labels["reference_notes"])
    label_register = np3_log_template("food-labelling-advertising")
    assert label_register["key"] == "packaging_and_label_review"
    assert any(field["key"] == "pre_visit_submission" for field in label_register["fields"])


def test_np3_check_calls_out_when_the_guidance_changed_since_its_last_attestation():
    record = SimpleNamespace(
        control_id="registration-scope",
        status="complete",
        due_date=None,
        title="Previous scope review",
        evidence_reference=None,
        created_at=date.today(),
        record_type="attestation",
        created_by_user_id=None,
        details={"np3_guidance_version": "2024-v1", "how_we_meet": "We review scope after changes."},
    )
    row = next(row for row in build_np3_audit_rows([record]) if row["topic"] == "Registration / scope of operations")
    assert row["guidance_update_required"] is True
    assert row["guidance_version"] == NP3_GUIDANCE_VERSION
    assert row["history"][0]["how_we_meet"] == "We review scope after changes."


def test_every_np3_audit_check_has_a_tailored_guidance_card_and_evidence_plan():
    audit_controls = {control_id for _category, topics in NP3_AUDIT_CATEGORIES for control_id, _topic in topics}
    assert audit_controls <= NP3_EVIDENCE_PLAYBOOKS.keys()
    training = NP3_EVIDENCE_PLAYBOOKS["staff-competency"]
    assert training["section"] == "Ensuring staff are trained and competent"
    assert {field["key"] for field in training["fields"]} >= {
        "training_register_reference",
        "last_training_review",
        "competency_observation",
    }
    training_register = next(field for field in training["fields"] if field["key"] == "training_register_reference")
    assert "every staff member" in training_register["help"]
    assert training_register["example"] == "Training / Staff competency matrix / 2026"
    assert "#page=" in training["guidance_url"]


def test_np3_post_audit_checks_added_2026_09_23_have_playbooks_registers_and_a_category():
    """Eight checks added after a real NP3 verification visit: each needs a guidance
    card/example, most need a register, and every one must appear in the audit list
    (not just live in the catalogue) or a verifier walkthrough would never surface it."""
    from app.features.compliant.modules.nz_alcohol.catalogue import (
        CONTROL_REQUIREMENTS,
        NP3_CONTROL_REFERENCES,
        framework_by_slug,
    )

    new_controls = {
        "recall-policy",
        "hazard-issues-register",
        "packaging-supplier-verification",
        "customer-complaints-register",
        "manufacturing-process-description",
        "food-contact-equipment-cleaning",
        "premises-notices-displayed",
        "cleaning-chemicals-food-safe",
    }
    np3 = framework_by_slug("np3-food-control")
    catalogued = {control_id for control_id, _description in np3["controls"]}
    assert new_controls <= catalogued
    assert new_controls <= NP3_CONTROL_REFERENCES.keys()
    assert all(("np3-food-control", control_id) in CONTROL_REQUIREMENTS for control_id in new_controls)
    audit_controls = {control_id for _category, topics in NP3_AUDIT_CATEGORIES for control_id, _topic in topics}
    assert new_controls <= audit_controls
    for control_id in new_controls:
        playbook = evidence_playbook(control_id)
        assert playbook["page"], control_id
        assert "#page=" in playbook["guidance_url"]
        assert playbook["proof"], control_id
        assert playbook["fields"], control_id
        # Every new control has its own register except the two that hook into Core
        # instead of duplicating a fact Core already owns.
        if control_id != "manufacturing-process-description":
            assert np3_log_template(control_id) is not None, control_id

    recall_policy = evidence_playbook("recall-policy")
    assert any("24" in item and "NZFS" in item for item in recall_policy["proof"])
    assert control_reference("np3-food-control", "recall-policy") == "Recalling your food"

    hazard_log = np3_log_template("hazard-issues-register")
    hazard_options = {option for field in hazard_log["fields"] if field["key"] == "hazard_type" for option, _label in field["options"]}
    assert hazard_options == {"physical", "biological", "chemical"}

    cleaning_chem_log = np3_log_template("cleaning-chemicals-food-safe")
    assert {field["key"] for field in cleaning_chem_log["fields"]} >= {
        "food_safe_confirmed",
        "evidence_reference",
        "product_link",
    }
    product_link = next(field for field in cleaning_chem_log["fields"] if field["key"] == "product_link")
    assert product_link["required"] is False

    manufacturing = evidence_playbook("manufacturing-process-description")
    core_link = manufacturing.get("core_connections") or []
    assert any(link["workspace_url"] == "/core/flows" for link in core_link)


def test_recall_policy_training_category_links_the_new_control():
    from app.features.compliant.modules.nz_alcohol.np3_audit import NP3_TRAINING_CATEGORIES

    category = next(entry for entry in NP3_TRAINING_CATEGORIES if entry[0] == "recall-policy-procedures")
    _key, _label, controls = category
    assert "recall-policy" in controls


def test_upcoming_evidence_review_is_a_live_priority_action():
    record = SimpleNamespace(
        status="complete",
        due_date=date.today() + timedelta(days=7),
        title="Sanitisation protocol review",
        framework_slug="np3-food-control",
        control_id="cleaning-and-hygiene",
    )
    actions = build_priority_actions(
        SimpleNamespace(enabled=True, settings={"alcohol_product_types": ["spirits"]}),
        [],
        {"profiled_product_count": 1},
        records=[record],
    )
    assert actions[0]["state"] == "review"
    assert actions[0]["control_id"] == "cleaning-and-hygiene"


def test_nz_alcohol_workflow_rules_only_enforce_an_explicit_np3_policy():
    assert rules_for_profile(None) == ()
    generic_profile = SimpleNamespace(enabled=True, settings={"food_control_programme": "np2"})
    generic_rule = rules_for_profile(generic_profile)[0]
    assert generic_rule.prompt["required"] is False
    assert generic_rule.prompt["label"] == "Compliance evidence"
    assert generic_rule.constraints == ()

    np3_profile = SimpleNamespace(
        enabled=True,
        settings={"food_control_programme": "np3", "np3_execution_evidence_mode": "required"},
    )
    np3_rule = rules_for_profile(np3_profile)[0]
    assert np3_rule.prompt["required"] is True
    assert np3_rule.prompt["label"] == "NP3 operational evidence"
    assert np3_rule.constraints[0].requirement == "active_evidence"
    assert np3_rule.constraints[0].code == "compliance_requirement_not_met"
