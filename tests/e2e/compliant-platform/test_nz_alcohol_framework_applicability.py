"""AC: NZ-alcohol framework applicability end-to-end -- `.agents/specs/compliant-nz-alcohol.md`,
"Framework applicability end-to-end". `GET /api/compliant/overview` and
`POST /api/compliant/reports/<framework_slug>` are the platform routes; the behavior under
test is this module's own `framework_applies()` / `framework_for_profile()` filtering, which
carries no dedicated route of its own (see spec's Provenance section).

Not covered by tests/e2e/compliant-platform/ already: those tests exercise the routes'
generic CRUD/auth/tenant-isolation shape with `alcohol_product_types` fixed to a single
value; none of them vary the setting to prove a framework actually appears/disappears, vary
`trade_waste_council` to prove the returned framework's source/version/controls actually
change, or exercise the "real but inapplicable framework" 400 branch of `build_audit_pack()`.
"""

from __future__ import annotations

import pytest

from app.features.compliant.modules.nz_alcohol.councils import TRADE_WASTE_CATALOGUES
from tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e


def _slugs(overview_body: dict) -> set[str]:
    return {framework["slug"] for framework in overview_body["frameworks"]}


def test_product_type_setting_filters_np3_and_wine_frameworks_in_overview(admin_page, enable_profile):
    """AC: an org whose `alcohol_product_types` is `["wine"]` never sees `np3-food-control`;
    switching the setting to a non-wine type flips which of `np3-food-control` /
    `wine-standards` is present. `customs-alcohol` applies to `"all_alcohol"` and is
    unaffected either way."""
    enable_profile(admin_page, enabled=True, settings={"alcohol_product_types": ["wine"]})
    wine_only = admin_page.request.get("/api/compliant/overview").json()
    slugs = _slugs(wine_only)
    assert "customs-alcohol" in slugs
    assert "wine-standards" in slugs
    assert "np3-food-control" not in slugs, "wine-only org should not see the NP3 food-control framework"

    enable_profile(admin_page, enabled=True, settings={"alcohol_product_types": ["beer"]})
    beer_only = admin_page.request.get("/api/compliant/overview").json()
    slugs = _slugs(beer_only)
    assert "customs-alcohol" in slugs
    assert "np3-food-control" in slugs, "beer org should see the NP3 food-control framework"
    assert "wine-standards" not in slugs, "beer-only org should not see the wine standards framework"


def test_unset_product_type_setting_shows_every_non_trade_waste_framework(admin_page, enable_profile):
    """AC: an empty/unset `alcohol_product_types` shows everything, before the operator has
    made a choice -- rather than hiding frameworks by default."""
    enable_profile(admin_page, enabled=True, settings={})
    body = admin_page.request.get("/api/compliant/overview").json()
    slugs = _slugs(body)
    assert {"customs-alcohol", "np3-food-control", "wine-standards"} <= slugs
    assert "trade-waste" not in slugs, "trade-waste has its own gate, independent of product types"


def test_trade_waste_framework_appears_only_with_consent_or_required_flag(admin_page, enable_profile):
    """AC: `trade-waste` applies iff a consent reference is set OR `trade_waste_required`
    is truthy -- neither present means the org never sees it."""
    enable_profile(admin_page, enabled=True, settings={})
    assert "trade-waste" not in _slugs(admin_page.request.get("/api/compliant/overview").json())

    enable_profile(admin_page, enabled=True, settings={"trade_waste_required": True})
    assert "trade-waste" in _slugs(admin_page.request.get("/api/compliant/overview").json())

    enable_profile(admin_page, enabled=True, settings={}, trade_waste_consent_reference="TW-CONSENT-001")
    assert "trade-waste" in _slugs(admin_page.request.get("/api/compliant/overview").json())


def test_trade_waste_framework_reflects_selected_council(admin_page, enable_profile):
    """AC: once `trade_waste_council` is set, the `trade-waste` framework's
    source_url/version/source_title match that council's catalogue entry, not the generic
    placeholder -- and switching council changes them again."""
    enable_profile(admin_page, enabled=True, settings={"trade_waste_required": True})
    generic = next(
        f for f in admin_page.request.get("/api/compliant/overview").json()["frameworks"] if f["slug"] == "trade-waste"
    )
    assert generic["source_url"] == "", "unset council should keep the base catalogue's placeholder source_url"

    enable_profile(admin_page, enabled=True, settings={"trade_waste_required": True, "trade_waste_council": "hamilton"})
    hamilton = next(
        f for f in admin_page.request.get("/api/compliant/overview").json()["frameworks"] if f["slug"] == "trade-waste"
    )
    expected = TRADE_WASTE_CATALOGUES["hamilton"]
    assert hamilton["source_url"] == expected["source_url"]
    assert hamilton["version"] == expected["version"]
    assert hamilton["source_title"] == expected["source_title"]
    expected_control_ids = {control_id for control_id, _description in expected["controls"]}
    actual_control_ids = {control["control_id"] for control in hamilton["controls"]}
    assert actual_control_ids == expected_control_ids, (
        "council overlay must bind controls too, not just version/source metadata "
        f"(expected {expected_control_ids}, got {actual_control_ids})"
    )
    # Hamilton and Dunedin have genuinely different control sets (Hamilton has no
    # "renewal", Dunedin has no "management-plan") -- proves the overlay actually swaps
    # controls per council rather than reusing a shared/base set that happens to overlap.
    assert actual_control_ids != {
        control_id for control_id, _description in TRADE_WASTE_CATALOGUES["dunedin"]["controls"]
    }

    enable_profile(
        admin_page,
        enabled=True,
        settings={"trade_waste_required": True, "trade_waste_council": "dunedin"},
    )
    dunedin = next(
        f for f in admin_page.request.get("/api/compliant/overview").json()["frameworks"] if f["slug"] == "trade-waste"
    )
    assert dunedin["source_url"] == TRADE_WASTE_CATALOGUES["dunedin"]["source_url"]
    assert dunedin["source_url"] != hamilton["source_url"], (
        "switching council must actually change the bound catalogue, not just accept the setting"
    )


def test_build_audit_pack_rejects_a_real_but_inapplicable_framework(admin_page, enable_profile):
    """AC: `build_audit_pack()` 400s a request for a framework slug that is real but does
    not apply to the org's current profile settings (checked via `framework_applies()`
    before any database query), distinct from the already-covered "unknown slug" 400."""
    enable_profile(admin_page, enabled=True, settings={"alcohol_product_types": ["spirits"]})

    response = admin_page.request.post(
        "/api/compliant/reports/wine-standards", headers=csrf_headers(admin_page), data={}
    )
    assert response.status == 400, f"expected 400 for an inapplicable framework, got {response.status}"
    assert "not applicable" in response.json()["error"]

    response = admin_page.request.post("/api/compliant/reports/trade-waste", headers=csrf_headers(admin_page), data={})
    assert response.status == 400, f"expected 400 for trade-waste with no consent/flag, got {response.status}"
    assert "not applicable" in response.json()["error"]

    # Sanity check the gate is real, not a blanket 400: the applicable framework succeeds.
    response = admin_page.request.post(
        "/api/compliant/reports/customs-alcohol", headers=csrf_headers(admin_page), data={}
    )
    assert response.status == 201, f"expected the applicable framework to still succeed, got {response.status}"
