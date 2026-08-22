"""AC: `GET /compliant/static/<filename>` requires auth, serves only .js/.css from
frontend/static/, rejects any filename containing "/" or ".." with 400
(.agents/specs/compliant-platform.md, "Blueprint & static assets").

Unlike the unauthenticated `/static/js/*`, `/static/css/*` routes covered by
tests/e2e/test_static_asset_security.py, this route sits behind `@requires_auth` and
guards traversal with an inline check rather than relying on `send_from_directory` alone
-- both are asserted here since neither has any existing E2E coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = REPO_ROOT / "app" / "features" / "compliant" / "frontend" / "static"


def test_static_asset_requires_auth(page):
    """Not under /static/ or /api/, so the global 401 handler treats this as a page GET
    and redirects rather than returning bare JSON (app_factory.py:322-336)."""
    response = page.request.get("/compliant/static/compliant.js", max_redirects=0)
    assert response.status == 302, f"expected a redirect for an unauthenticated request, got {response.status}"


def test_static_asset_serves_real_js_file(admin_page):
    response = admin_page.request.get("/compliant/static/compliant.js")
    assert response.status == 200
    assert response.body() == (STATIC_DIR / "compliant.js").read_bytes()


def test_static_asset_serves_real_css_file(admin_page):
    response = admin_page.request.get("/compliant/static/compliant.css")
    assert response.status == 200
    assert response.body() == (STATIC_DIR / "compliant.css").read_bytes()


@pytest.mark.parametrize(
    "filename",
    [
        # A bare ".." with no "/", not a percent-encoded or URL-relative form: those get
        # normalized before the request leaves the client, or decoded ambiguously by the
        # WSGI server, and are not this route's contract to test (see
        # tests/e2e/test_static_asset_security.py's module docstring for the same
        # reasoning). "..secret.js" is guaranteed to reach the view as a literal segment.
        "..secret.js",
        "..secret.css",
    ],
)
def test_static_asset_rejects_path_traversal(admin_page, filename):
    response = admin_page.request.get(f"/compliant/static/{filename}")
    assert response.status == 400, f"{filename!r} should be rejected: got {response.status}"


def test_static_asset_rejects_disallowed_extension(admin_page):
    response = admin_page.request.get("/compliant/static/compliant.py")
    assert response.status == 400
