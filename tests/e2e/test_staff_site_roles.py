"""Real HTTPS role preparation and staged assignment refusal at desktop/mobile widths."""

import threading
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from app.core.db.models.user import User
from tests.factories import DEFAULT_TEST_PASSWORD
from tests.test_compliant_routes import flask_app  # noqa: F401
from tests.test_custom_roles import org  # noqa: F401
from tests.test_staff_site_roles import _sites

pytestmark = pytest.mark.e2e


@pytest.fixture
def site_roles_server(org, db, flask_app):  # noqa: F811
    o, _ = org
    a, _ = _sites(db, o.id)
    actor = db.query(User).filter(User.org_id == o.id).one()
    server = make_server("127.0.0.1", 0, flask_app, threaded=True, ssl_context="adhoc")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}", actor.email, a.id
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize("width", [1440, 390])
def test_prepare_selected_role_and_assignment_remains_closed(browser, site_roles_server, width):
    url, email, site_id = site_roles_server
    context = browser.new_context(ignore_https_errors=True, viewport={"width": width, "height": 1000})
    try:
        assert (
            context.request.post(url + "/auth/login", data={"email": email, "password": DEFAULT_TEST_PASSWORD}).status
            == 200
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/core/people")
        root = page.locator("[data-custom-roles]")
        expect(root).to_be_visible()
        page.locator(".people-custom-role-new summary").click()
        form = page.locator("[data-custom-role-form]")
        name = "Browser selected " + str(uuid4())
        form.locator('[name="name"]').fill(name)
        form.get_by_label("Site access", exact=True).select_option("selected")
        form.locator(f'[data-custom-role-sites] input[value="{site_id}"]').check()
        form.get_by_role("button", name="Create role").click()
        expect(root.locator("[data-custom-role-list]")).to_contain_text(name)
        assert page.url.endswith("/core/people")
        data = context.request.get(url + "/org/roles").json()
        role = next(r for r in data["custom_roles"] if r["name"] == name)
        assert role["site_access_mode"] == "selected" and role["site_ids"] == [str(site_id)] and not role["assignable"]
        response = context.request.post(
            url + "/org/users", data={"email": f"blocked-{uuid4()}@test.com", "role": role["value"]}
        )
        assert response.status == 400 and "cannot be assigned" in response.json()["error"]
        assert not errors
        assert page.evaluate("document.documentElement.scrollWidth") <= width
    finally:
        context.close()
