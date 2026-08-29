"""Compliant Tools page: real-browser fill -> submit -> rendered result.

Spec .agents/specs/compliant_tools.md AC19. The pure render logic is unit-tested
(tests/js/compliant-tools-render.test.js, AC16) and the served markup structurally
(tests/test_compliant_tools.py, AC17); this proves the whole thing actually works in a
browser for two representative calculators, plus the entitlement + retired-URL behaviour.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import attach_probe, login_through_ui

pytestmark = pytest.mark.e2e


def _numeric(text: str) -> float:
    return float(text.replace(",", "").replace("mL", "").replace("L", "").strip())


def _fill(page: Page, key: str, field: str, value) -> None:
    page.locator(f'form[data-calculator="{key}"] [name="{field}"]').fill(str(value))


def _submit(page: Page, key: str):
    form = page.locator(f'form[data-calculator="{key}"]')
    form.locator("button.ct-submit").click()
    return form.locator("xpath=following-sibling::*[@data-result]").locator(".ct-result")


def test_ac19_dilution_flow_matches_worked_example(admin_page: Page):
    admin_page.goto("/compliant/tools")
    expect(admin_page.locator('form[data-calculator="dilution"]')).to_be_visible()

    admin_page.locator('form[data-calculator="dilution"] [name="solve_for"]').select_option("final_volume_ml")
    _fill(admin_page, "dilution", "starting_abv", 40)
    _fill(admin_page, "dilution", "starting_volume_ml", 1000)
    _fill(admin_page, "dilution", "final_abv", 20)
    result = _submit(admin_page, "dilution")

    expect(result).to_be_visible()
    values = result.locator(".ct-result-value").all_inner_texts()
    assert any(abs(_numeric(v) - 2000.0) < 0.5 for v in values), values
    expect(result.locator(".ct-disclaimer")).to_contain_text("hydrometer")


def test_ac19_standard_drinks_flow(admin_page: Page):
    admin_page.goto("/compliant/tools")
    _fill(admin_page, "standard_drinks", "volume_ml", 330)
    _fill(admin_page, "standard_drinks", "abv_pct", 5)
    result = _submit(admin_page, "standard_drinks")

    expect(result).to_be_visible()
    values = [_numeric(v) for v in result.locator(".ct-result-value").all_inner_texts()]
    assert any(abs(v - 1.3022) < 0.01 for v in values), values
    expect(result.locator(".ct-disclaimer")).to_contain_text("Food Standards Code")


def test_ac19_validation_error_renders_in_ui(admin_page: Page):
    admin_page.goto("/compliant/tools")
    admin_page.locator('form[data-calculator="dilution"] [name="solve_for"]').select_option("final_volume_ml")
    _fill(admin_page, "dilution", "starting_abv", 40)
    _fill(admin_page, "dilution", "starting_volume_ml", 1000)
    _fill(admin_page, "dilution", "final_abv", 900)  # > starting_abv -> 400

    form = admin_page.locator('form[data-calculator="dilution"]')
    form.locator("button.ct-submit").click()
    error = form.locator("xpath=following-sibling::*[@data-result]").locator(".ct-error")
    expect(error).to_be_visible()


def test_ac19_unsubscribed_org_gets_404_and_no_nav(browser, app_url, fresh_user):
    user = fresh_user()  # deliberately NOT granted the compliant subscription
    context = browser.new_context(base_url=app_url, ignore_https_errors=True)
    page = context.new_page()
    attach_probe(page)
    login_through_ui(page, user["email"], user["password"])

    resp = page.request.get("/compliant/tools")
    assert resp.status == 404, resp.status

    page.goto("/core/dashboard")
    assert page.locator('.sidebar a[href="/compliant"]').count() == 0
    context.close()


def test_ac19_old_dilution_url_is_gone(admin_page: Page):
    assert admin_page.request.get("/dilution-calculator").status == 404
    assert admin_page.request.post("/api/dilution-calculator/solve", data={}).status == 404
