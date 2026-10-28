"""GL-U01: a modal takes focus, keeps it, closes on Escape and gives focus back.

One shared script (app/ui/shared/dialog-focus.js) handles every modal; these check it on three
kinds: an Alpine overlay with role="dialog" (Sales settings), an Alpine sheet without a dialog
role (New customer), and a sheet with no Escape handler of its own (the Sales overview's widget).
Requests are routed into the Flask test client (see test_crm_contact_sync_ui).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from app.core.db.models.user import UserRole
from tests.e2e.test_crm_contact_sync_ui import client, sales_page, xero  # noqa: F401 -- fixture re-export
from tests.test_crm import db, org  # noqa: F401 -- fixture re-export
from tests.test_crm import user as _member  # noqa: F401 -- fixture re-export

pytestmark = pytest.mark.e2e

HOST = "https://crm.test"
INSIDE = "(sel) => document.querySelector(sel).contains(document.activeElement)"


@pytest.fixture()
def user(_member, db):  # noqa: F811
    _member.role = UserRole.ADMIN
    db.commit()
    return _member


def _tab_stays_inside(page, selector, presses=25):
    for _ in range(presses):
        page.keyboard.press("Tab")
        assert page.evaluate(INSIDE, selector), "Tab left the dialog"
    for _ in range(5):
        page.keyboard.press("Shift+Tab")
        assert page.evaluate(INSIDE, selector), "Shift+Tab left the dialog"


def test_the_mapping_dialog_takes_keeps_and_returns_focus(xero, sales_page):  # noqa: F811
    # The assessment's probe: focus stayed on the page behind the dialog.
    sales_page.goto(HOST + "/crm/configuration")
    sales_page.locator(".sales-settings[aria-busy='false']").wait_for()
    opener = sales_page.get_by_role("button", name="Add a mapping")
    opener.click()
    dialog = sales_page.locator("[data-ss-mapping-dialog]")
    expect(dialog).to_be_visible()
    sales_page.wait_for_function("document.querySelector('[data-ss-mapping-dialog]').contains(document.activeElement)")
    _tab_stays_inside(sales_page, "[data-ss-mapping-dialog]")
    # Behind it is inert: the page's own button can't be reached or clicked.
    assert sales_page.evaluate("document.querySelector('.ss-stack').closest('[inert]') !== null")
    sales_page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    sales_page.wait_for_function("document.activeElement && document.activeElement.matches('[data-ss-add-mapping]')")
    assert sales_page.evaluate("document.querySelector('[inert]') === null")


def test_a_sheet_without_a_dialog_role_gets_the_same_behaviour(xero, sales_page):  # noqa: F811
    sales_page.goto(HOST + "/crm/customers")
    opener = sales_page.get_by_role("button", name="New customer")
    opener.click()
    sheet = sales_page.locator(".crm-task-sheet-overlay").first
    expect(sheet).to_be_visible()
    sales_page.wait_for_function("document.querySelector('.crm-task-sheet-overlay').contains(document.activeElement)")
    _tab_stays_inside(sales_page, ".crm-task-sheet-overlay")
    sales_page.keyboard.press("Escape")
    expect(sheet).to_be_hidden()
    sales_page.wait_for_function(
        "document.activeElement && document.activeElement.textContent.trim() === 'New customer'"
    )


def test_escape_closes_a_dialog_that_has_no_escape_handler_of_its_own(xero, sales_page):  # noqa: F811
    # The Sales overview's widget sheet only closed from its buttons; Escape did nothing.
    sales_page.goto(HOST + "/crm")
    sales_page.get_by_role("button", name="Add widget").click()
    sheet = sales_page.locator(".crm-lane-sheet-overlay", has_text="Add Custom Widget")
    expect(sheet).to_be_visible()
    sales_page.wait_for_function(
        "[...document.querySelectorAll('.crm-lane-sheet-overlay')].some(o => o.getClientRects().length && o.contains(document.activeElement))"
    )
    sales_page.keyboard.press("Escape")
    expect(sheet).to_be_hidden()
    sales_page.wait_for_function("document.activeElement && document.activeElement.textContent.trim() === 'Add widget'")


SCRIPT = Path(__file__).resolve().parents[2] / "app/ui/shared/dialog-focus.js"


@pytest.mark.parametrize(
    "markup",
    [
        # styles_2.css hides .modal-overlay with opacity and pointer-events, not display.
        '<div class="modal-overlay" style="position:fixed;inset:0;opacity:0;pointer-events:none">'
        "<button>Inside</button></div>",
        # The execute-step modal rendered as a page (data-render-mode="page") is static.
        '<div class="modal-overlay" style="position:static"><button>Inside</button></div>',
        # A <dialog> opened with show(), not showModal(), is not modal.
        "<dialog open><button>Inside</button></dialog>",
    ],
    ids=["hidden-by-opacity", "embedded-in-page", "non-modal-dialog"],
)
def test_what_only_looks_like_a_modal_leaves_the_page_alone(page, markup):
    page.set_content(f"<main><button id='outside'>Outside</button></main>{markup}")
    page.add_script_tag(path=str(SCRIPT))
    page.focus("#outside")
    page.wait_for_timeout(100)  # two animation frames for the observer
    assert page.evaluate("document.querySelector('[inert]') === null")
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.id") == "outside"


def test_the_signed_out_notice_stays_usable_over_an_open_sheet(xero, sales_page):  # noqa: F811
    # Codex on !573: the dialog helper made the notice an inert background sibling.
    sales_page.goto(HOST + "/crm")
    sales_page.get_by_role("button", name="Add widget").click()
    title = sales_page.get_by_placeholder("e.g. Top 5 stockists this month").or_(
        sales_page.get_by_placeholder("e.g. Top 5 Customers by Monthly Rate")
    )
    title.fill("Gin by region")
    sales_page.route(
        "**/crm/api/session-probe",
        lambda route: route.fulfill(status=401, content_type="application/json", body="{}"),
    )
    sales_page.evaluate("fetch('/crm/api/session-probe', { method: 'POST' })")
    notice = sales_page.locator("#session-ended-notice")
    expect(notice).to_be_visible()
    sales_page.wait_for_timeout(100)  # the helpers' animation frames
    assert sales_page.evaluate("document.querySelector('#session-ended-notice').closest('[inert]') === null")
    link = notice.get_by_role("link", name="Sign in again")
    for _ in range(30):
        sales_page.keyboard.press("Tab")
        if sales_page.evaluate(
            "document.activeElement && document.activeElement.textContent.trim() === 'Sign in again'"
        ):
            break
    else:
        raise AssertionError("Tab never reached the Sign in again link")
    expect(link).to_be_focused()
    expect(title).to_have_value("Gin by region")
