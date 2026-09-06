"""Static guardrails for the Compliant dashboard's first-use path."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_compliant_dashboard_links_to_a_separate_configuration_surface():
    """Configuration must not be embedded in the evidence dashboard."""
    dashboard = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert "<form data-profile-form" not in dashboard
    assert "data-profile-target" in dashboard
    assert "/compliant/nz-alcohol/configuration" in dashboard


def test_compliant_dashboard_documents_the_honest_product_boundary():
    dashboard = (
        _REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "templates" / "compliant" / "dashboard.html"
    ).read_text(encoding="utf-8")

    assert "without pretending to be legal certification" in dashboard


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
