"""Public MCP 8.2b, AC5 in a real browser: sign in on the normal login page, land on consent.

Unit tests (tests/mcp_oauth/) cover the endpoints. What they cannot cover is that a person who
arrives signed out is taken through the landing page's own sign-in modal and comes back to the
consent page, and that the page works on a phone.
"""

import re
import secrets
import uuid
from urllib.parse import urlencode

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.page_load_audit import audit_current_page

pytestmark = pytest.mark.e2e

REDIRECT = "https://assistant.example.test/callback"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.fixture()
def assistant(fresh_user):
    """A signed-up person in an org with assistants on, and a registered client."""
    from app.core.db import db_session
    from app.core.db.models.user import UserRole
    from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings, OAuthClient
    from app.utils.config_loader import config

    person = fresh_user(UserRole.MEMBER)
    db = db_session()
    client_id = f"e2e-client-{secrets.token_hex(6)}"
    db.add(McpOrgSettings(org_id=person["org_id"], enabled=True))
    db.add(McpAllowedRole(org_id=person["org_id"], role_key="builtin:member"))
    db.add(OAuthClient(client_id=client_id, client_name="E2E Assistant", redirect_uris=[REDIRECT], registration="dcr"))
    db.commit()

    def authorize_path(**overrides):
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "state": f"s-{uuid.uuid4().hex[:6]}",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "scope": "bize.read",
            "resource": config.mcp_resource,
        }
        params.update(overrides)
        return "/oauth/authorize?" + urlencode(params)

    yield {**person, "path": authorize_path, "client_id": client_id}

    db.rollback()
    db.query(OAuthClient).filter(OAuthClient.client_id == client_id).delete(synchronize_session=False)
    db.commit()


def _sign_in(page: Page, person: dict) -> None:
    expect(page.locator("#login-email")).to_be_visible()  # the login modal opened by itself
    page.locator("#login-email").fill(person["email"])
    page.locator("#login-password").fill(person["password"])
    page.locator("#login-submit-btn").click()


def _hold_redirect_target(page: Page) -> None:
    """The assistant's callback is not a real site; answer it so the browser has somewhere to land."""
    page.route("https://assistant.example.test/**", lambda route: route.fulfill(status=200, body="callback"))


def _decide(page: Page, button: str) -> str:
    """Click a consent button and return where the app redirected the browser (the Location header).

    Reads the 302 itself, so the test does not depend on the browser following it to a made-up host.
    """
    with page.expect_response(lambda r: r.url.endswith("/oauth/authorize") and r.request.method == "POST") as posted:
        page.get_by_role("button", name=button).click()
    response = posted.value
    assert response.status == 302, response.status
    return response.headers["location"]


def test_signed_out_person_signs_in_and_lands_on_consent_then_approves(page: Page, assistant):
    _hold_redirect_target(page)
    state = "approve-flow"
    page.goto(assistant["path"](state=state))

    expect(page).to_have_url(re.compile(r"/\?login=1|/$"))  # sent to the normal sign-in page
    _sign_in(page, assistant)

    page.wait_for_url(re.compile(r"/oauth/authorize\?"), timeout=15_000)
    expect(page.get_by_role("heading", name=re.compile("Connect E2E Assistant"))).to_be_visible()
    expect(page.get_by_text("Unverified app")).to_be_visible()
    expect(page.get_by_text("assistant.example.test", exact=True)).to_be_visible()
    expect(page.get_by_label("Read only")).to_be_checked()
    expect(page.get_by_label(re.compile("Read and write"))).to_be_disabled()

    location = _decide(page, "Allow read-only access")
    assert location.startswith(REDIRECT + "?")
    assert f"state={state}" in location
    assert re.search(r"[?&]code=bzc_[A-Za-z0-9_-]{43}", location)


def test_cancel_goes_back_to_the_assistant_with_access_denied(page: Page, assistant):
    _hold_redirect_target(page)
    page.goto(assistant["path"](state="cancel-flow"))
    _sign_in(page, assistant)
    page.wait_for_url(re.compile(r"/oauth/authorize\?"), timeout=15_000)

    location = _decide(page, "Cancel")
    assert location.startswith(REDIRECT + "?")
    assert "error=access_denied" in location
    assert "state=cancel-flow" in location
    assert "code=" not in location


def test_a_next_that_is_not_the_consent_page_is_ignored_after_sign_in(page: Page, assistant):
    page.goto("/?login=1&next=" + "https%3A%2F%2Fevil.example%2Fphish")
    _sign_in(page, assistant)
    page.wait_for_url(re.compile(r"/core(/dashboard)?/?(\?.*)?$"), timeout=15_000)
    assert "evil.example" not in page.url


def test_consent_is_blocked_with_a_message_when_the_org_has_assistants_off(page: Page, assistant):
    from app.core.db import db_session
    from app.features.mcp_oauth.models import McpOrgSettings

    db = db_session()
    db.query(McpOrgSettings).filter(McpOrgSettings.org_id == assistant["org_id"]).update({"enabled": False})
    db.commit()

    page.goto(assistant["path"]())
    _sign_in(page, assistant)
    page.wait_for_url(re.compile(r"/oauth/authorize\?"), timeout=15_000)
    expect(page.get_by_text("hasn't turned on AI assistant access")).to_be_visible()
    expect(page.get_by_role("button", name="Allow read-only access")).to_have_count(0)


def test_consent_page_has_no_sideways_scroll_on_a_phone(browser, app_url, assistant):
    from app.core.db import db_session
    from app.features.mcp_oauth.models import McpOrgSettings, OAuthClient

    host = ".".join(["a" * 63, "b" * 63, "c" * 63, "example.test"])
    redirect = f"https://{host}:8443/callback"
    db = db_session()
    client = db.query(OAuthClient).filter_by(client_id=assistant["client_id"]).one()
    client.client_name = "E2E Assistant " + "A" * 58
    client.redirect_uris = [redirect]
    db.commit()

    context = browser.new_context(base_url=app_url, ignore_https_errors=True, viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(assistant["path"](redirect_uri=redirect))
        _sign_in(page, assistant)
        page.wait_for_url(re.compile(r"/oauth/authorize\?"), timeout=15_000)
        expect(page.get_by_role("button", name="Allow read-only access")).to_be_visible()
        expect(page.get_by_text(f"{host}:8443", exact=True)).to_be_visible()
        widths = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        assert widths[0] <= widths[1], widths
        audit_current_page(page, "/oauth/authorize")

        db.query(McpOrgSettings).filter_by(org_id=assistant["org_id"]).update({"enabled": False})
        db.commit()
        page.reload()
        expect(page.get_by_role("alert")).to_contain_text("hasn't turned on AI assistant access")
        widths = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        assert widths[0] <= widths[1], widths
    finally:
        context.close()
