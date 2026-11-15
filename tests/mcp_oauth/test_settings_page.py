"""AC33-AC35, server side: the Settings -> AI assistants page (public MCP 8.2e).

The browser behaviour (the switch, the role picker, the bottom-sheet revoke, 375 px) is in
``tests/e2e/test_mcp_settings_browser.py``. What is pinned here is what the *server* decides:
who gets the admin controls, what the page tells someone whose role can't connect, that the page
is session-only, and that the Settings tab row and the page registry know about it.
"""

from __future__ import annotations

from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings
from app.ui.navigation import SECTION_TABS, resolve, section_tabs
from app.ui.page_registry import PAGES, page_for
from app.utils.config_loader import config
from tests.mcp_oauth.support import bearer, make_client, mint_grant

PATH = "/core/ai-assistants"


def _page(world, who) -> str:
    resp = world.session(who).get(PATH)
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


# --- the page, and who gets the admin controls --------------------------------------------------


def test_ac33_a_signed_out_visitor_does_not_get_the_page(world):
    resp = world.anon().get(PATH)
    assert resp.status_code in (302, 401)
    assert "Let people connect" not in resp.get_data(as_text=True)


def test_ac33_an_admin_gets_the_switch_and_the_role_picker(world):
    html = _page(world, "admin")
    assert 'data-can-manage="true"' in html
    assert "data-ai-switch" in html
    assert "data-ai-roles" in html
    assert "Let people connect their own AI assistant (Claude, ChatGPT, …) to read this organisation" in html
    assert "Connected apps" in html


def test_ac33_a_member_gets_no_admin_controls_in_the_page_at_all(world):
    """The switch and roles are not hidden with CSS: the server never sends them to a non-admin."""
    for who in ("member", "sales", "production", "compliance", "auditor"):
        html = _page(world, who)
        assert 'data-can-manage="false"' in html, who
        assert "data-ai-switch" not in html, who
        assert "data-ai-roles" not in html, who
        assert "Your connections" in html, who


def test_the_page_names_the_mcp_url_for_everyone(world):
    for who in ("admin", "member"):
        assert config.mcp_resource in _page(world, who), who


def test_the_page_script_and_styles_are_served(world):
    html = _page(world, "admin")
    client = world.anon()
    for name in ("ai-assistants.js", "ai-assistants.css"):
        assert f"/static/mcp-settings/{name}" in html, name
        assert client.get(f"/static/mcp-settings/{name}").status_code == 200, name


# --- what a person who cannot connect is told ---------------------------------------------------


def test_a_member_is_told_when_the_org_has_assistants_off(world):
    world.enable(False)
    html = _page(world, "member")
    assert "hasn't turned on AI assistant access" in html
    assert "data-ai-blocked" in html


def test_a_member_is_told_when_their_role_is_not_ticked(world):
    world.enable(True, roles=("admin",))
    html = _page(world, "member")
    assert "Your role can't use AI assistant access" in html
    assert "data-ai-blocked" in html


def test_a_member_whose_role_is_ticked_sees_no_blocking_note(world):
    world.enable(True, roles=("member",))
    assert "data-ai-blocked" not in _page(world, "member")


def test_an_admin_is_never_given_the_blocking_note(world):
    """An admin switches it on from this very page, so the note would only be noise."""
    world.enable(False)
    assert "data-ai-blocked" not in _page(world, "admin")


# --- AC33: the state the page reads back is the state it saved ----------------------------------


def test_ac33_a_new_org_has_the_switch_off_and_saving_is_read_back_the_same(world, db):
    db.query(McpAllowedRole).filter_by(org_id=world.org.id).delete()
    db.query(McpOrgSettings).filter_by(org_id=world.org.id).delete()
    db.commit()
    admin = world.session("admin")
    first = admin.get("/api/core/mcp/settings").get_json()
    assert (first["enabled"], first["allowed_roles"]) == (False, [])

    keys = ["builtin:member", "builtin:sales"]
    saved = admin.put("/api/core/mcp/settings", json={"enabled": True, "allowed_roles": keys})
    assert saved.status_code == 200
    again = admin.get("/api/core/mcp/settings").get_json()
    assert again["enabled"] is True
    assert sorted(again["allowed_roles"]) == sorted(keys)


def test_ac33_a_member_cannot_change_the_settings_whatever_the_page_shows(world):
    member = world.session("member")
    body = {"enabled": True, "allowed_roles": ["builtin:member"]}
    assert member.put("/api/core/mcp/settings", json=body).status_code == 403
    assert member.get("/api/core/mcp/settings").status_code == 403


# --- AC34: what the page lists --------------------------------------------------------------------


def test_ac34_the_grants_list_has_what_a_row_shows(world, db):
    grant, _access, _refresh = mint_grant(db, world.users["member"], world.client_row)
    rows = world.session("admin").get("/api/core/mcp/grants").get_json()["grants"]
    row = next(r for r in rows if r["id"] == str(grant.id))
    assert row["client_name"] == world.client_row.client_name
    assert row["verified"] is False
    assert row["user"]["email"] == world.users["member"].email
    assert row["created_at"] and row["last_used_at"] is None


def test_a_hostile_client_name_never_reaches_the_page_html(world, db):
    """The page fetches grants as JSON and writes them with textContent; the HTML carries none."""
    hostile = make_client(db, name='MCPTEST <img src=x onerror="alert(1)">')
    mint_grant(db, world.users["member"], hostile)
    html = _page(world, "admin")
    assert "onerror" not in html
    assert "<img src=x" not in html


# --- session only -------------------------------------------------------------------------------


def test_the_page_is_not_reachable_with_an_assistants_token(world, db):
    _grant, access, _refresh = mint_grant(db, world.users["admin"], world.client_row)
    resp = world.anon().get(PATH, headers=bearer(access))
    assert resp.status_code == 403


# --- the Settings tab row and the page registry ---------------------------------------------------


def test_the_page_is_registered_under_settings(world):
    page = page_for(PATH)
    assert page is not None
    assert (page.section, page.tab, page.title) == ("settings", "ai-assistants", "AI assistants")
    assert resolve(PATH) == ("settings", "ai-assistants")


def test_every_registered_tab_still_points_at_its_page():
    tab = next(t for t in SECTION_TABS["settings"] if t.key == "ai-assistants")
    assert tab.path == PATH
    assert tab.label == "AI assistants"
    assert any(p.path == tab.path and (p.section, p.tab) == ("settings", tab.key) for p in PAGES)


def test_everyone_gets_the_tab_because_everyone_can_see_their_own_connections(world):
    for who in ("admin", "member", "sales", "auditor"):
        keys = [tab.key for tab in section_tabs("settings", world.users[who])]
        assert "ai-assistants" in keys, who
