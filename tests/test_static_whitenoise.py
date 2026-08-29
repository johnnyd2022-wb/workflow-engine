"""WhiteNoise fronts the unauthenticated JS/CSS prefixes at the WSGI layer.

The security contract (traversal 400, bad-extension 400, 404, the /static/inventory and
/static/img filename allowlists, the /ui/shared auth gate) is covered end-to-end by
tests/e2e/test_static_asset_security.py -- those still pass because WhiteNoise falls
through to the Flask routes for any path it has no file for. This file pins the two
things that make the change worth doing:

  1. an existing asset is served by WhiteNoise with a validator header (ETag /
     Last-Modified) so a CDN edge can cache it and reloads become 304s;
  2. the exact Cache-Control the Flask routes emit is preserved, and nosniff is still
     set even though WhiteNoise bypasses Flask's after_request hook.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_EXPECTED_CC = "public, max-age=3600, stale-while-revalidate=60"


@pytest.fixture
def client():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    c.environ_base["wsgi.url_scheme"] = "https"
    c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    return c


@pytest.mark.parametrize(
    "url,disk",
    [
        ("/static/js/app.js", ("app", "core", "frontend", "js", "app.js")),
        ("/static/css/core2.css", ("app", "core", "frontend", "css", "core2.css")),
    ],
)
def test_whitenoise_serves_asset_with_validator_and_pinned_cache_control(client, url, disk):
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.data == REPO_ROOT.joinpath(*disk).read_bytes()
    assert resp.headers.get("Cache-Control") == _EXPECTED_CC
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    # A validator header is what lets Cloudflare (and the browser) revalidate cheaply.
    assert resp.headers.get("ETag") or resp.headers.get("Last-Modified")


def test_conditional_get_returns_304(client):
    first = client.get("/static/js/app.js")
    etag = first.headers.get("ETag")
    assert etag
    second = client.get("/static/js/app.js", headers={"If-None-Match": etag})
    assert second.status_code == 304


def test_static_urls_carry_a_cache_busting_version(client):
    """url_for on the bundled-asset endpoints appends ?v=<digest> so a deploy that ships
    changed JS/CSS gets a new URL instead of serving hour-old assets against fresh HTML.
    The digest is stable within a process and the asset still serves with or without it."""
    from app.api.app_factory import create_app

    app = create_app()
    with app.test_request_context():
        from flask import url_for

        js_url = url_for("core.serve_core_js", filename="app.js")
        css_url = url_for("core.serve_core_css", filename="core2.css")

    assert "?v=" in js_url and "?v=" in css_url
    assert js_url.split("v=")[1] == css_url.split("v=")[1], "one version for all core bundles"
    # the file serves whether or not the param is present (routing ignores the query)
    assert client.get(js_url).status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    assert client.get("/static/js/app.js?v=deadbeef").status_code == 200


def test_fallthrough_preserves_flask_guards(client):
    # traversal + bad extension -> Flask route's 400; missing -> Flask route's 404
    assert client.get("/static/js/..secret.js").status_code == 400
    assert client.get("/static/css/app.js").status_code == 400
    assert client.get("/static/js/does-not-exist-xyz.js").status_code == 404
    # allowlisted prefixes are NOT fronted by WhiteNoise -> Flask route unchanged
    assert client.get("/static/inventory/other-icon.svg").status_code == 400
    assert client.get("/static/inventory/inventory-icon.svg").status_code == 200
