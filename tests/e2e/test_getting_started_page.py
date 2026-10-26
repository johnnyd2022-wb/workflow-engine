"""GL-P09: the Getting started page, a resumable path from sign-up to a traced sale.

Shared behaviour runs against Style 1 (the default). The CONCEPT ONLY group loads each style at
phone, laptop and wall widths and is deleted with the two styles not chosen.
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

READY = "[data-getting-started-root] [data-gs-progress]:not([hidden])"


def _serve(page: Page, edit):
    def handler(route):
        body = route.fetch().json()
        edit(body)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/api/core/getting-started", handler)


def _open(page: Page, style="1", width=1440):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/core/getting-started?style={style}")
    page.locator(READY).wait_for()


def test_progress_and_the_next_step_open_first(logged_in_page: Page):
    page = logged_in_page
    _open(page)
    data = page.request.get("/api/core/getting-started").json()
    expect(page.locator("[data-gs-done]")).to_have_text(str(data["done"]))
    expect(page.locator("[data-gs-total]")).to_have_text(str(data["total"]))
    nxt = next(s for s in data["steps"] if s["key"] == data["next"])
    # The next step is the one open, with its button leading to where it's done.
    expanded = page.locator(".gs-guide__toggle[aria-expanded='true']")
    expect(expanded).to_have_count(1)
    expect(expanded).to_contain_text(nxt["title"])
    expect(page.get_by_role("link", name=nxt["action"])).to_have_attribute("href", nxt["href"])


def test_a_blocked_step_says_what_it_waits_for(logged_in_page: Page):
    page = logged_in_page

    def block(body):
        for s in body["steps"]:
            if s["key"] == "first_batch":
                s.update(status="blocked", blocked_by="Set up a product workflow first.", needs="workflow", fact=None)

    _serve(page, block)
    _open(page)
    row = page.locator(".gs-guide__item", has_text="Record your first batch")
    expect(row).to_contain_text("Cannot start yet")
    row.locator(".gs-guide__toggle").click()
    expect(row).to_contain_text("Set up a product workflow first.")
    expect(row.get_by_role("link")).to_have_count(0)


def test_all_done_says_so_and_home_drops_the_strip(logged_in_page: Page):
    page = logged_in_page

    def finish(body):
        for s in body["steps"]:
            s.update(status="done", blocked_by=None, needs=None)
        body.update(done=body["total"], next=None, complete=True)

    _serve(page, finish)
    _open(page)
    expect(page.get_by_role("heading", name="You're set up")).to_be_visible()
    page.goto("/core/dashboard")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-dashboard-go-live]")).to_be_hidden()


def test_a_failed_load_says_so_and_shows_no_empty_list(logged_in_page: Page):
    page = logged_in_page
    page.route("**/api/core/getting-started", lambda r: r.fulfill(status=500, body="{}", content_type="application/json"))
    page.goto("/core/getting-started")
    expect(page.locator("[data-gs-message]")).to_contain_text("Could not load your progress")
    expect(page.locator("[data-gs-view]:visible")).to_have_count(0)


# --- CONCEPT ONLY: each style fits every width ------------------------------------------------


@pytest.mark.parametrize("style", ["1", "2", "3"])
@pytest.mark.parametrize("width", [390, 1440, 1920])
def test_concept_each_style_fits_without_sideways_scroll(logged_in_page: Page, style, width):
    page = logged_in_page
    _open(page, style, width)
    expect(page.locator(f"[data-gs-view='{style}']")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_concept_style_3_skips_and_goes_to_the_step_a_blocked_one_needs(logged_in_page: Page):
    page = logged_in_page

    def block(body):
        for s in body["steps"]:
            if s["key"] == "trace":
                s.update(status="blocked", blocked_by="Match your Xero products first.", needs="mappings")

    _serve(page, block)
    _open(page, "3")
    page.locator(".gs-path__step", has_text="Follow a batch to its customers").click()
    page.get_by_role("button", name="Go to: Match your Xero products to yours").click()
    expect(page.locator(".gs-path__step[aria-current='step']")).to_contain_text("Match your Xero products")
