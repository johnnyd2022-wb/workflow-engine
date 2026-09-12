"""Static guardrails for the Compliant dashboard's first-use path."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_compliant_overview_is_a_summary_not_an_evidence_workbench():
    """Overview directs work into scoped surfaces instead of embedding unrelated forms."""
    dashboard = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert "<form data-profile-form" not in dashboard
    assert "data-record-form" not in dashboard
    assert "data-product-form" not in dashboard
    assert "YOUR NEXT BEST MOVES" not in dashboard
    assert "MODULE SETTINGS" not in dashboard
    assert "A clear view of what applies." not in dashboard
    assert "without pretending to be legal certification" not in dashboard
    assert "data-frameworks" in dashboard
    assert "data-compliant-surface=\"overview\"" in dashboard


def test_compliant_dashboard_keeps_its_summary_copy_concise():
    dashboard = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert "without pretending to be legal certification" not in dashboard


def test_compliant_dashboard_hydrates_live_views_in_parallel_without_hiding_partial_failures():
    script = (_REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "static" / "compliant.js").read_text(
        encoding="utf-8"
    )

    assert "Promise.allSettled" in script
    assert "some supporting lists could not load" in script
    assert "setSubmitting(form, true)" in script


def test_np3_audit_keeps_evidence_in_the_expanded_check():
    script = (_REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "static" / "np3-audit.js").read_text(
        encoding="utf-8"
    )

    assert "np3-evidence-options" in script
    assert "np3-category-tabs" in script
    assert "np3-health-card" in script
    assert "require evidence" in script
    assert "np3-category-tab__evidence-needed" in script
    assert "openControlDetail" not in script
    assert "rowsByCategory" in script


def test_core_renders_module_defined_system_finding_contracts_without_module_branches():
    banner = (_REPO_ROOT / "app" / "core" / "frontend" / "js" / "system-findings-banner.js").read_text(encoding="utf-8")
    notifications = (_REPO_ROOT / "app" / "core" / "frontend" / "js" / "system-findings-notifications.js").read_text(
        encoding="utf-8"
    )

    assert "system_finding" in banner
    assert "system_alerts" in notifications
    assert "compliant.nz_alcohol" not in banner
    assert "compliant.nz_alcohol" not in notifications


def test_core_hub_consolidates_findings_inside_its_system_issues_health_bar():
    core_hub = (_REPO_ROOT / "app" / "core" / "frontend" / "core" / "core2.html").read_text(encoding="utf-8")
    system_status = (_REPO_ROOT / "app" / "core" / "backend" / "system_status.py").read_text(encoding="utf-8")

    assert "{% include 'shared/system-findings-banner.html' %}" not in core_hub
    assert "MODULE_SYSTEM_FINDING" in system_status
    assert "system_alerts" in system_status


def test_np3_audit_has_a_dedicated_check_workspace_with_tailored_evidence_fields():
    check_page = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "np3_check.html"
    ).read_text(encoding="utf-8")
    check_script = (_REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "static" / "np3-check.js").read_text(
        encoding="utf-8"
    )

    assert "data-np3-check-root" in check_page
    assert "evidence_playbook" in check_script
    assert "/settings" in check_script
    assert "evidence_fields" in check_script
    assert "np3-field__help" in check_script
    assert "What to collect for this check" in check_script
    assert "np3-check-workspace__primary" in check_script
    assert "/logs" in check_script
    assert "BUILT-IN REGISTER" in check_script


def test_compliant_evidence_ui_is_control_scoped_and_keeps_passing_sections_quiet():
    dashboard = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "dashboard.html"
    ).read_text(encoding="utf-8")
    evidence_register = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "evidence_register.html"
    ).read_text(encoding="utf-8")
    dashboard_script = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "static" / "compliant.js"
    ).read_text(encoding="utf-8")
    audit_script = (_REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "static" / "np3-audit.js").read_text(
        encoding="utf-8"
    )
    audit = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "np3_audit.html"
    ).read_text(encoding="utf-8")

    assert "data-evidence-control-heading" not in dashboard
    assert "data-evidence-control-heading" in evidence_register
    assert "review_interval_months" in evidence_register
    assert "evidence_coverage" in dashboard_script
    assert "compliant-framework-summary" in dashboard_script
    assert "summary_health" in dashboard_script
    assert "Compliance score:" in dashboard_script
    assert "current evidence controls" in dashboard_script
    assert "evidence ready" in dashboard_script
    assert "need attention" in dashboard_script
    assert "overdue" in dashboard_script
    assert "compliantSurface" in dashboard_script
    assert "activeCategory" in audit_script
    assert "np3-evidence-options" in audit_script
    assert "data-np3-control-detail" not in audit
    assert ">NP3</strong>" in audit
    assert "np3-overview-panels" in audit
    assert "AUDIT PREP" in audit
    assert "np3-rail-register" in audit
    assert "data-np3-disclaimer" not in audit
    assert "This checklist reflects the verification-confirmation topics" not in audit


def test_core_overview_keeps_system_issues_out_of_competing_alert_cards():
    core_hub = (_REPO_ROOT / "app" / "core" / "frontend" / "core" / "core2.html").read_text(encoding="utf-8")

    assert "Inventory alerts" not in core_hub
    assert "core2-overview-inventory-alerts" not in core_hub


def test_np3_health_uses_attention_as_one_actionable_total():
    audit_script = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "static" / "np3-audit.js"
    ).read_text(encoding="utf-8")
    stylesheet = (_REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "static" / "compliant.css").read_text(
        encoding="utf-8"
    )

    assert "People actions" not in audit_script
    assert "Includes people, evidence, guidance and remediation" in audit_script
    assert "np3-health-card--attention strong" in stylesheet
    assert "np3-health-card--overdue strong" in stylesheet
    assert "compliant-framework-summary__metric--ready" in stylesheet
    assert "compliant-framework-summary__metric--attention" in stylesheet
    assert "compliant-framework-summary__metric--overdue" in stylesheet


def test_audit_pack_does_not_overclaim_tamper_evidence():
    """The stored checksum is self-computed and never re-verified on read, so the pack
    must not tell an auditor it is tamper-evident — see docs/compliant-nz-alcohol-spec.md
    §11, which explicitly says not to claim immutability until that exists."""
    audit_pack = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "audit_pack.html"
    ).read_text(encoding="utf-8")

    assert "tamper" not in audit_pack.lower()
    assert "immutable" not in audit_pack.lower()
    assert "SHA-256 checksum" in audit_pack
