"""AC5-AC7: the static/shared-asset routes are unauthenticated by design (docstrings:
"no auth so they load reliably"), so path-traversal rejection, extension allowlisting, and
(for /static/inventory, /static/img, and /ui/shared) a filename/auth allowlist are the
entire security boundary. A single dropped guard on any of these routes turns "serves a
fixed set of files" into "reads any file on disk this process can see".

Traversal payloads here use a literal ".." with no "/" (e.g. "..app.js") rather than an
encoded slash ("..%2f..%2fapp.py"): whether a percent-encoded slash reaches the view as a
literal "/" or gets decoded/normalized earlier depends on the WSGI server and is not this
route's contract to test. A bare ".." is a single path segment under every server, always
reaches the view, and is exactly what AC5-AC7 says must be rejected
(`".." in filename or "/" in filename or "\\" in filename`) -- so it exercises the app-level
guard deterministically instead of the routing layer's incidental behavior.

/ui/shared's auth gate for non-allowlisted files (AC7's 401) and its correct
Content-Type for the public file already have dedicated coverage in
test_landing_regressions.py (F1 regression) and test_security_headers.py; this file adds
the traversal/extension/404 checks those don't cover.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]

# Expected Cache-Control values, asserted exactly (not by substring) so a regression like
# max-age=36000 (10hr, matches the "3600" substring) or a dropped
# stale-while-revalidate on the CSS route is caught (test-evaluator.md finding #3).
_STATIC_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=60"


def _real_bytes(*parts: str) -> bytes:
    return (REPO_ROOT.joinpath(*parts)).read_bytes()


# ---------------------------------------------------------------------------------------
# AC5: /static/js/<filename>, /static/css/<filename> -- no auth, traversal rejection,
# extension whitelist, 404 on missing file, explicit Content-Type + Cache-Control.
# ---------------------------------------------------------------------------------------


def test_ac5_static_js_serves_real_file_without_auth(page):
    response = page.request.get("/static/js/app.js")
    assert response.status == 200
    # Byte-identical to the real file on disk, not just a 200 status
    # (test-evaluator.md finding #2 -- a 200 with wrong/empty body previously passed).
    assert response.body() == _real_bytes("app", "core", "frontend", "js", "app.js")


def test_ac5_static_css_serves_real_file_without_auth(page):
    response = page.request.get("/static/css/core2.css")
    assert response.status == 200
    assert response.body() == _real_bytes("app", "core", "frontend", "css", "core2.css")


def test_ac5_static_js_has_content_type_and_cache_headers(page):
    response = page.request.get("/static/js/app.js")
    assert "javascript" in response.headers.get("content-type", "")
    assert response.headers.get("cache-control", "") == _STATIC_CACHE_CONTROL


def test_ac5_static_css_has_content_type_and_cache_headers(page):
    response = page.request.get("/static/css/core2.css")
    assert "text/css" in response.headers.get("content-type", "")
    assert response.headers.get("cache-control", "") == _STATIC_CACHE_CONTROL


@pytest.mark.parametrize(
    "route",
    ["/static/js/..secret.js", "/static/css/..secret.css", "/static/js/app%5Cfile.js"],
)
def test_ac5_static_asset_rejects_path_traversal(page, route):
    response = page.request.get(route)
    assert response.status == 400, f"{route} should be rejected as an invalid filename, got {response.status}"


@pytest.mark.parametrize("route", ["/static/js/app.py", "/static/css/app.js"])
def test_ac5_static_asset_rejects_disallowed_extension(page, route):
    response = page.request.get(route)
    assert response.status == 400, f"{route} should be rejected for its extension, got {response.status}"


@pytest.mark.parametrize("route", ["/static/js/does-not-exist-e2e.js", "/static/css/does-not-exist-e2e.css"])
def test_ac5_static_asset_404s_on_missing_file(page, route):
    response = page.request.get(route)
    assert response.status == 404


# ---------------------------------------------------------------------------------------
# AC6: /static/inventory/<filename>, /static/img/<filename> -- hardcoded filename
# allowlist, not a general extension whitelist.
# ---------------------------------------------------------------------------------------


def test_ac6_inventory_static_serves_allowlisted_file(page):
    response = page.request.get("/static/inventory/inventory-icon.svg")
    assert response.status == 200
    # Public assets live in inventory_static/ (not inventory/, which holds server templates).
    assert response.body() == _real_bytes("app", "core", "frontend", "inventory_static", "inventory-icon.svg")


def test_ac6_inventory_static_rejects_non_allowlisted_filename_with_valid_extension(page):
    """A .svg extension is not sufficient on its own -- only the two hardcoded names serve."""
    response = page.request.get("/static/inventory/other-icon.svg")
    assert response.status == 400


def test_ac6_inventory_static_does_not_expose_server_templates(page):
    """The inventory/ dir holds server-rendered Jinja (add.html, dispose.html, view.html,
    ...). None of it may be reachable as a static file -- regression guard for !197
    routing the whole directory through WhiteNoise."""
    for name in ("add.html", "add_manual.html", "dispose.html", "view.html", "inventory_hub_banner.html"):
        response = page.request.get(f"/static/inventory/{name}")
        assert response.status != 200, f"/static/inventory/{name} must not be served statically"


def test_ac6_img_static_serves_allowlisted_file(page):
    response = page.request.get("/static/img/hero-wave.jpg")
    assert response.status == 200
    assert response.body() == _real_bytes("app", "core", "frontend", "img", "hero-wave.jpg")


def test_ac6_img_static_rejects_non_allowlisted_filename_with_valid_extension(page):
    response = page.request.get("/static/img/other-hero.jpg")
    assert response.status == 400


def test_ac6_inventory_static_rejects_path_traversal(page):
    response = page.request.get("/static/inventory/..inventory-icon.svg")
    assert response.status == 400


# ---------------------------------------------------------------------------------------
# AC7: /ui/shared/<filename> -- same traversal/extension rules as AC5, layered under the
# in-view auth gate. Use an authenticated request so these hit the traversal/extension
# checks rather than the earlier 401 (any non-allowlisted filename 401s first when
# anonymous, which is F1's test already, not this one).
# ---------------------------------------------------------------------------------------


def test_ac7_ui_shared_rejects_path_traversal_when_authenticated(logged_in_page):
    response = logged_in_page.request.get("/ui/shared/..account-info.js")
    assert response.status == 400


def test_ac7_ui_shared_rejects_disallowed_extension_when_authenticated(logged_in_page):
    response = logged_in_page.request.get("/ui/shared/account-info.html")
    assert response.status == 400


def test_ac7_ui_shared_serves_allowlisted_extension_when_authenticated(logged_in_page):
    response = logged_in_page.request.get("/ui/shared/account-info.js")
    assert response.status == 200
    assert response.body() == _real_bytes("app", "ui", "shared", "account-info.js")


def test_ac7_ui_shared_404s_on_missing_file_when_authenticated(logged_in_page):
    response = logged_in_page.request.get("/ui/shared/does-not-exist-e2e.js")
    assert response.status == 404
