"""Public MCP 8.2e in a real browser: Settings -> AI assistants (AC33, AC34, AC35).

Unit tests (tests/mcp_oauth/test_settings_page.py) pin what the server decides. What only a browser
shows: the switch and the role picker saving and coming back the same, Revoke going through a
bottom sheet, a client's chosen name staying text, and the page not scrolling sideways at 375 px.
"""

from __future__ import annotations

import re
import secrets
from uuid import UUID

import pytest
from playwright.sync_api import Page, expect

from app.core.db.models.user import UserRole
from tests.e2e.conftest import login_through_ui, purge_org

pytestmark = pytest.mark.e2e

PATH = "/core/ai-assistants"
SWITCH_NAME = re.compile("Let people connect their own AI assistant")
PHONE = {"width": 375, "height": 812}
HOSTILE = 'Hostile <img src=x onerror="window.__pwned=1"> app'
LONG_NAME = "An assistant with a very long name that a person might pick on the registration form " * 2


@pytest.fixture()
def world(fresh_user, db):
    """An org with an admin and a member, one client per grant, and a way to read the tables back."""
    from app.core.db.models.user import User
    from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings, OAuthClient, OAuthGrant
    from tests.mcp_oauth.support import make_client, mint_grant

    admin = fresh_user(UserRole.ADMIN)
    org_id = UUID(admin["org_id"])
    # fresh_user makes one person per call, in a new org; the member joins the admin's org instead.
    from tests.factories import DEFAULT_TEST_PASSWORD, UserFactory

    member_row = UserFactory(
        org_id=org_id, email=f"e2e-mcp-member-{secrets.token_hex(4)}@example.test", role=UserRole.MEMBER
    )
    db.commit()
    member = {"email": member_row.email, "password": DEFAULT_TEST_PASSWORD, "user_id": str(member_row.id)}
    clients: list = []

    class World:
        pass

    w = World()
    w.admin, w.member, w.org_id = admin, member, org_id

    def connect(user_id: str, name: str, verified: bool = False):
        # Verified comes from the code list (design review S3), so a verified client uses Claude's
        # documented callback rather than just a flag on the row.
        redirect = ["https://claude.ai/api/mcp/auth_callback"] if verified else None
        client = make_client(db, name=f"MCPTEST {name}", verified=verified, redirect_uris=redirect)
        clients.append(client)
        user = db.get(User, UUID(user_id))
        grant, _access, _refresh = mint_grant(db, user, client)
        return grant

    def settings():
        db.expire_all()
        row = db.get(McpOrgSettings, org_id)
        keys = sorted(r.role_key for r in db.query(McpAllowedRole).filter_by(org_id=org_id))
        return (bool(row.enabled) if row else False), keys

    def revoked(grant_id) -> bool:
        db.expire_all()
        return db.get(OAuthGrant, grant_id).revoked_at is not None

    w.connect, w.settings, w.revoked = connect, settings, revoked
    yield w

    db.rollback()
    # Everything the org holds (grants and tokens included), then the member; fresh_user's own
    # teardown removes the admin. The clients are global rows, so they go by name.
    purge_org(db, org_id, UUID(member["user_id"]))
    db.query(User).filter(User.id == UUID(member["user_id"])).delete(synchronize_session=False)
    for client in clients:
        db.query(OAuthClient).filter(OAuthClient.id == client.id).delete(synchronize_session=False)
    db.commit()


def _open(page: Page, person: dict) -> None:
    login_through_ui(page, person["email"], person["password"])
    page.goto(PATH)
    expect(page.get_by_role("heading", name="AI assistants", level=1)).to_be_visible()


def _settled(sheet):
    """The sheet's bounding box once its slide-up animation has finished (mid-slide it is below the fold)."""
    sheet.evaluate("el => Promise.all(el.getAnimations().map(a => a.finished))")
    return sheet.bounding_box()


def _roles(page: Page):
    return page.locator("[data-ai-roles]")


def _dark(page: Page) -> None:
    page.evaluate("localStorage.setItem('spa-theme', 'dark')")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-spa-theme", "dark")


# --- AC33 -----------------------------------------------------------------------------------------


def test_ac33_the_switch_is_off_for_a_new_org_and_the_roles_wait_for_it(world, page):
    _open(page, world.admin)
    switch = page.get_by_role("switch", name=SWITCH_NAME)
    expect(switch).not_to_be_checked()
    expect(_roles(page).get_by_role("checkbox").first).to_be_disabled()
    expect(page.get_by_role("button", name="Save changes")).to_be_disabled()  # nothing to save yet


def test_ac33_ticking_roles_and_turning_it_on_saves_and_the_page_reloads_the_same(world, page):
    _open(page, world.admin)
    page.get_by_role("switch", name=SWITCH_NAME).check()
    _roles(page).get_by_label("Staff", exact=True).check()
    _roles(page).get_by_label("Sales", exact=True).check()
    page.get_by_role("button", name="Save changes").click()
    expect(page.locator("[data-ai-status]")).to_contain_text("Saved")

    assert world.settings() == (True, ["builtin:member", "builtin:sales"])

    page.reload()
    expect(page.get_by_role("switch", name=SWITCH_NAME)).to_be_checked()
    expect(_roles(page).get_by_label("Staff", exact=True)).to_be_checked()
    expect(_roles(page).get_by_label("Sales", exact=True)).to_be_checked()
    expect(_roles(page).get_by_label("Auditor", exact=True)).not_to_be_checked()
    expect(page.get_by_role("button", name="Save changes")).to_be_disabled()  # saved, so clean again


def test_ac33_turning_it_off_again_keeps_the_ticked_roles_and_disables_them(world, page):
    _open(page, world.admin)
    page.get_by_role("switch", name=SWITCH_NAME).check()
    _roles(page).get_by_label("Staff", exact=True).check()
    page.get_by_role("button", name="Save changes").click()
    expect(page.locator("[data-ai-status]")).to_contain_text("Saved")

    page.get_by_role("switch", name=SWITCH_NAME).uncheck()
    expect(_roles(page).get_by_label("Staff", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Save changes").click()
    expect(page.locator("[data-ai-status]")).to_contain_text("Saved")
    assert world.settings() == (False, ["builtin:member"])


def test_ac33_on_with_nobody_ticked_says_so_instead_of_looking_finished(world, page):
    _open(page, world.admin)
    page.get_by_role("switch", name=SWITCH_NAME).check()
    expect(page.locator("[data-ai-roles-hint]")).to_contain_text("Tick at least one role")


def test_a_failed_save_shows_the_error_and_keeps_what_was_typed(world, page):
    _open(page, world.admin)
    page.route(
        "**/api/core/mcp/settings",
        lambda route: route.fulfill(status=400, json={"error": "Unknown role: x"})
        if route.request.method == "PUT"
        else route.continue_(),
    )
    page.get_by_role("switch", name=SWITCH_NAME).check()
    _roles(page).get_by_label("Staff", exact=True).check()
    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_role("alert").filter(has_text="Unknown role")).to_be_visible()
    expect(_roles(page).get_by_label("Staff", exact=True)).to_be_checked()
    assert world.settings() == (False, [])


def test_access_settings_has_only_the_org_switch(world, page):
    _open(page, world.admin)
    expect(page.get_by_role("switch", name=SWITCH_NAME)).to_be_visible()
    expect(page.get_by_role("region", name="Access").get_by_role("switch")).to_have_count(1)


# --- AC34 -----------------------------------------------------------------------------------------


def test_ac34_connected_apps_lists_a_grant_and_revoke_goes_through_the_bottom_sheet(world, page):
    grant = world.connect(world.member["user_id"], "Claude")
    _open(page, world.admin)
    row = page.locator("[data-ai-grants] > li").filter(has_text="Claude")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("Unverified app")
    expect(row).to_contain_text(world.member["email"])
    expect(row).to_contain_text("Connected")
    expect(row).to_contain_text("Never used")

    row.get_by_role("button", name=re.compile("Revoke")).click()
    sheet = page.locator("[data-ai-dialog]")
    expect(sheet).to_be_visible()
    expect(sheet).to_contain_text("Claude")
    # Nothing is revoked by opening the sheet.
    assert not world.revoked(grant.id)

    # A bottom sheet: pinned to the bottom edge of the viewport and centred.
    box = _settled(sheet)
    viewport = page.viewport_size
    assert abs((box["y"] + box["height"]) - viewport["height"]) <= 1, box
    assert abs((box["x"] + box["width"] / 2) - viewport["width"] / 2) <= 2, box

    sheet.get_by_role("button", name="Revoke access").click()
    expect(sheet).to_be_hidden()
    expect(page.locator("[data-ai-grants] > li").filter(has_text="Claude")).to_have_count(0)
    expect(page.locator("[data-ai-empty]")).to_be_visible()
    assert world.revoked(grant.id)

    page.reload()  # it stays gone
    expect(page.locator("[data-ai-grants] > li").filter(has_text="Claude")).to_have_count(0)


def test_ac34_cancelling_the_sheet_keeps_the_grant(world, page):
    grant = world.connect(world.member["user_id"], "Cursor")
    _open(page, world.admin)
    row = page.locator("[data-ai-grants] > li").filter(has_text="Cursor")
    row.get_by_role("button", name=re.compile("Revoke")).click()
    sheet = page.locator("[data-ai-dialog]")
    sheet.get_by_role("button", name="Cancel").click()
    expect(sheet).to_be_hidden()
    expect(row).to_have_count(1)
    assert not world.revoked(grant.id)

    # Escape closes it too, and focus returns to the button that opened it.
    row.get_by_role("button", name=re.compile("Revoke")).click()
    expect(sheet).to_be_visible()
    page.keyboard.press("Escape")
    expect(sheet).to_be_hidden()
    expect(row.get_by_role("button", name=re.compile("Revoke"))).to_be_focused()
    assert not world.revoked(grant.id)


def test_ac34_a_clients_chosen_name_is_shown_as_text_never_as_markup(world, page):
    world.connect(world.member["user_id"], HOSTILE)
    _open(page, world.admin)
    row = page.locator("[data-ai-grants] > li").first
    expect(row).to_contain_text("<img src=x")  # the characters, shown
    assert page.locator("[data-ai-grants] img").count() == 0
    assert page.evaluate("window.__pwned") is None

    row.get_by_role("button", name=re.compile("Revoke")).click()
    expect(page.locator("[data-ai-dialog]")).to_contain_text("<img src=x")
    assert page.locator("[data-ai-dialog] img").count() == 0
    assert page.evaluate("window.__pwned") is None


def test_ac34_a_verified_client_has_no_unverified_badge(world, page):
    world.connect(world.member["user_id"], "Known app", verified=True)
    _open(page, world.admin)
    row = page.locator("[data-ai-grants] > li").filter(has_text="Known app")
    expect(row).to_have_count(1)
    expect(row).not_to_contain_text("Unverified")


def test_ac34_an_empty_list_says_what_will_appear(world, page):
    _open(page, world.admin)
    expect(page.locator("[data-ai-empty]")).to_be_visible()
    expect(page.locator("[data-ai-grants] > li")).to_have_count(0)


def test_a_failed_load_offers_try_again(world, page):
    calls = {"n": 0}

    def flaky(route):
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(status=500, json={"error": "boom"})
        else:
            route.continue_()

    page.route("**/api/core/mcp/grants", flaky)
    _open(page, world.admin)
    expect(page.get_by_role("alert").filter(has_text="Couldn't load")).to_be_visible()
    page.get_by_role("button", name="Try again").click()
    expect(page.locator("[data-ai-empty]")).to_be_visible()


def test_a_member_sees_only_their_own_connection_and_no_admin_controls(world, page):
    mine = world.connect(world.member["user_id"], "My assistant")
    world.connect(world.admin["user_id"], "Admins assistant")
    _open(page, world.member)

    expect(page.get_by_role("switch")).to_have_count(0)
    expect(page.locator("[data-ai-roles]")).to_have_count(0)
    expect(page.get_by_role("heading", name="Your connections")).to_be_visible()
    rows = page.locator("[data-ai-grants] > li")
    expect(rows).to_have_count(1)
    expect(rows).to_contain_text("My assistant")
    expect(rows).not_to_contain_text("Admins assistant")

    rows.get_by_role("button", name=re.compile("Revoke")).click()
    page.locator("[data-ai-dialog]").get_by_role("button", name="Revoke access").click()
    expect(page.locator("[data-ai-empty]")).to_be_visible()
    assert world.revoked(mine.id)


def test_the_connect_url_can_be_copied(world, page, context):
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    _open(page, world.admin)
    expect(page.locator("[data-ai-url]")).to_have_value(re.compile(r"/mcp$"))
    page.get_by_role("button", name="Copy").click()
    expect(page.get_by_role("button", name="Copied")).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == page.locator("[data-ai-url]").input_value()


# --- AC35 -----------------------------------------------------------------------------------------


def _no_sideways_scroll(page: Page, where: str) -> None:
    sizes = page.evaluate(
        "() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth,"
        " body: document.body.scrollWidth })"
    )
    assert sizes["scroll"] <= sizes["client"] + 1, f"{where}: page scrolls sideways {sizes}"
    assert sizes["body"] <= sizes["client"] + 1, f"{where}: body scrolls sideways {sizes}"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_ac35_at_375px_the_page_has_no_sideways_scroll(world, page, theme):
    world.connect(world.member["user_id"], LONG_NAME)
    world.connect(world.admin["user_id"], "Claude")
    world.connect(world.member["user_id"], "Averyveryveryveryveryveryverylongsinglewordclientnamewithnospaces")
    page.set_viewport_size(PHONE)
    _open(page, world.admin)
    if theme == "dark":
        _dark(page)
    page.get_by_role("switch", name=SWITCH_NAME).check()
    _no_sideways_scroll(page, f"{theme}: settings and grants")

    page.locator("[data-ai-grants] > li").first.get_by_role("button", name=re.compile("Revoke")).click()
    sheet = page.locator("[data-ai-dialog]")
    expect(sheet).to_be_visible()
    _no_sideways_scroll(page, f"{theme}: bottom sheet open")
    box = _settled(sheet)
    assert box["x"] >= -1 and box["x"] + box["width"] <= PHONE["width"] + 1, f"sheet sticks out: {box}"
    assert abs((box["y"] + box["height"]) - PHONE["height"]) <= 1, f"sheet is not at the bottom: {box}"


def test_s6_the_notice_about_outside_text_sits_beside_the_switch_and_fits_a_phone(world, page):
    """Design review S6: the switch's own card says what text comes from outside, readable at 375 px."""
    _open(page, world.admin)
    card = page.locator(".ai-access")
    notice = card.locator("[data-ai-outside-text]")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("customer and supplier names")
    expect(notice).to_contain_text("never shared with assistants")
    switch_box = page.get_by_role("switch", name=SWITCH_NAME).bounding_box()
    notice_box = notice.bounding_box()
    assert switch_box["y"] < notice_box["y"] < _settled(_roles(page))["y"], "between the switch and the roles"
    page.set_viewport_size(PHONE)
    box = _settled(notice)
    assert box["x"] >= -1 and box["x"] + box["width"] <= PHONE["width"] + 1, f"the notice sticks out: {box}"
    _no_sideways_scroll(page, "settings with the outside-text notice")


def test_ac35_the_member_view_at_375px_has_no_sideways_scroll(world, page):
    world.connect(world.member["user_id"], LONG_NAME)
    page.set_viewport_size(PHONE)
    _open(page, world.member)
    _no_sideways_scroll(page, "member view")
