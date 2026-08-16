"""Static guardrails for the Compliant dashboard's first-use path."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_compliant_dashboard_has_one_complete_profile_form():
    """Nested forms make browser parsing and the one-minute setup flow unreliable."""
    dashboard = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert dashboard.count("<form data-profile-form") == 1
    assert dashboard.count("</form>") == dashboard.count("<form ")
    assert "data-profile-target" in dashboard


def test_compliant_dashboard_documents_the_honest_product_boundary():
    dashboard = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert "without pretending to be legal certification" in dashboard
