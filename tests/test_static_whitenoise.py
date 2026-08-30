"""WhiteNoise fronts the unauthenticated JS/CSS prefixes at the WSGI layer.

The security contract (traversal 400, bad-extension 400, 404, the /static/inventory and
/static/img filename allowlists, the /ui/shared auth gate) is covered end-to-end by
tests/e2e/test_static_asset_security.py. This file pins the two things that make the
change worth doing:

  1. an existing asset is served by WhiteNoise with a validator header (ETag /
     Last-Modified) so a CDN edge can cache it and reloads become 304s;
  2. the exact Cache-Control the Flask routes emit is preserved, and nosniff is still
     set even though WhiteNoise bypasses Flask's after_request hook.

WhiteNoise.add_files() recursively publishes *everything* under the dir it is given and
does NOT honour the Flask route's filename allowlist, so the source dir must hold public
assets only. js/, css/, img/ and inventory_static/ do; the server-rendered inventory/
templates are deliberately NOT handed to WhiteNoise. test_inventory_templates_not_exposed
below is the regression guard for that.
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
    # /static/inventory/: WhiteNoise serves the two public assets from inventory_static/;
    # anything it has no file for falls through to the Flask route's two-file allowlist.
    assert client.get("/static/inventory/other-icon.svg").status_code == 400
    assert client.get("/static/inventory/inventory-icon.svg").status_code == 200
    assert client.get("/static/inventory/inventory-spa-header.css").status_code == 200


def test_inventory_templates_not_exposed(client):
    """Regression: !197 handed the whole inventory/ dir (public assets + server-rendered
    Jinja) to WhiteNoise, so GET /static/inventory/add.html returned 200 with raw
    template source, bypassing the Flask allowlist. Every non-allowlisted inventory
    filename must stay non-200; the two public assets keep their content type and the
    pinned Cache-Control."""
    repo_inventory = REPO_ROOT / "app" / "core" / "frontend" / "inventory"
    template_names = sorted(p.name for p in repo_inventory.glob("*.html"))
    assert template_names, "expected server-rendered templates in app/core/frontend/inventory/"
    for name in template_names:
        resp = client.get(f"/static/inventory/{name}")
        assert resp.status_code != 200, (
            f"/static/inventory/{name} is a server template and must not be served statically "
            f"(got {resp.status_code})"
        )

    svg = client.get("/static/inventory/inventory-icon.svg")
    assert svg.status_code == 200
    assert svg.headers.get("Content-Type", "").startswith("image/svg+xml")
    assert svg.headers.get("Cache-Control") == _EXPECTED_CC
    css = client.get("/static/inventory/inventory-spa-header.css")
    assert css.status_code == 200
    assert css.headers.get("Content-Type", "").startswith("text/css")
    assert css.headers.get("Cache-Control") == _EXPECTED_CC
