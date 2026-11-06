"""GL-C04: help and contact on every page, with a reference support can look up.

The reference is the first 8 characters of the request's id: the X-Request-ID header on every
response and the request_id on every log line for that request.
"""

import re

import pytest
from flask import g

from app.observability.middleware import incoming_request_id
from app.observability.reference import reference_for
from tests.test_auth_password_session import PASSWORD
from tests.test_auth_password_session import account as _account  # noqa: F401 -- fixture re-export

BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


@pytest.fixture
def signed_in(_account):  # noqa: F811
    return _account["make_client"](PASSWORD)


@pytest.fixture(scope="module")
def anon():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    return app, client


def test_every_response_carries_its_request_id(anon):
    _app, client = anon
    first = client.get("/healthcheck").headers.get("X-Request-ID")
    second = client.get("/healthcheck").headers.get("X-Request-ID")
    assert first and second and first != second


def test_a_caller_supplied_request_id_is_kept_only_if_it_looks_like_one(anon):
    _app, client = anon
    kept = client.get("/healthcheck", headers={"X-Request-ID": "edge-7f3a9c21d4"})
    assert kept.headers["X-Request-ID"] == "edge-7f3a9c21d4"
    replaced = client.get("/healthcheck", headers={"X-Request-ID": "x" * 200})
    assert replaced.headers["X-Request-ID"] != "x" * 200
    assert incoming_request_id("abc def ghij") is None
    assert incoming_request_id("short") is None
    assert incoming_request_id("1b4e28ba-2fa1-11d2-883f-0016d3cca427") == "1b4e28ba-2fa1-11d2-883f-0016d3cca427"


def test_reference_is_the_first_eight_characters_of_the_request_id():
    assert reference_for("1B4E28BA-2fa1-11d2-883f-0016d3cca427") == "1b4e28ba"
    assert reference_for(None) == ""


def test_a_missing_page_says_how_to_get_help_with_the_reference(anon):
    _app, client = anon
    resp = client.get("/no-such-page-anywhere", headers=BROWSER)
    assert resp.status_code == 404
    page = resp.get_data(as_text=True)
    ref = reference_for(resp.headers["X-Request-ID"])
    assert "We couldn&#39;t find that page" in page or "We couldn't find that page" in page
    assert f'data-testid="error-reference">{ref}<' in page
    assert "mailto:support@biz-e.app" in page
    assert "Not Found</h1>" not in page  # not Flask's bare page any more


def test_a_missing_api_route_answers_json_with_the_reference(signed_in):
    resp = signed_in.get("/api/core/no-such-endpoint")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body == {"error": "Not found", "reference": reference_for(resp.headers["X-Request-ID"])}


@pytest.mark.parametrize(
    ("path", "headers", "json_reply"),
    [("/api/core/anything", {}, True), ("/core/anything", BROWSER, False)],
)
def test_a_server_error_gives_a_reference_instead_of_a_bare_500(anon, path, headers, json_reply):
    app, _client = anon
    app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        with app.test_request_context(path, headers=headers):
            g.request_id = "9c0ffee1-0000-4000-8000-000000000000"
            resp = app.make_response(app.handle_exception(RuntimeError("boom")))
    finally:
        app.config["PROPAGATE_EXCEPTIONS"] = None
    assert resp.status_code == 500
    if json_reply:
        assert resp.get_json() == {"error": "Something went wrong on our side", "reference": "9c0ffee1"}
    else:
        page = resp.get_data(as_text=True)
        assert "Something went wrong on our side" in page and ">9c0ffee1<" in page
        assert "boom" not in page  # never the exception text


def test_every_app_page_offers_help_with_its_own_reference(signed_in):
    resp = signed_in.get("/core/settings", headers=BROWSER)
    assert resp.status_code == 200
    page = resp.get_data(as_text=True)
    meta = re.search(r'<meta name="request-reference" content="([0-9a-f]{8})">', page)
    assert meta and meta.group(1) == reference_for(resp.headers["X-Request-ID"])
    assert 'class="bee-menu__help"' in page and '@click="openHelp()"' in page
    assert '<dialog id="bize-help"' in page and 'data-support-email="support@biz-e.app"' in page
    assert '<script src="/ui/shared/help.js" defer></script>' in page


def test_the_help_script_is_served_to_signed_in_people(signed_in):
    resp = signed_in.get("/ui/shared/help.js")
    assert resp.status_code == 200
    assert b"window.BizeHelp" in resp.data
