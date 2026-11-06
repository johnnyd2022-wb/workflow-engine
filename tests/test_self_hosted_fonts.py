"""Webfonts are served from /static/fonts, never Google Fonts.

A main pipeline went red when the browser smoke test couldn't reach fonts.googleapis.com
(net::ERR_NETWORK_CHANGED). Self-hosting removes that third-party request from every page,
and the CSP no longer allows Google's font hosts.
"""

import re
from pathlib import Path

import pytest

from app.core.security import csp

ROOT = Path(__file__).resolve().parents[1]
FONTS_CSS = ROOT / "app/core/frontend/css/fonts.css"
FONTS_DIR = ROOT / "app/core/frontend/fonts"
GOOGLE = re.compile(r"fonts\.(googleapis|gstatic)\.com")


@pytest.fixture(scope="module")
def client():
    from app.api.app_factory import create_app

    return create_app().test_client()


def test_no_template_or_stylesheet_loads_google_fonts():
    offenders = [
        str(path.relative_to(ROOT))
        for pattern in ("**/*.html", "**/*.css", "**/*.js")
        for path in (ROOT / "app").glob(pattern)
        if GOOGLE.search(path.read_text(errors="ignore"))
    ]
    assert offenders == []


def test_every_font_face_points_at_a_file_that_exists():
    urls = re.findall(r"url\(/static/fonts/([^)]+)\)", FONTS_CSS.read_text())
    assert urls, "fonts.css declares no faces"
    assert {"Roboto", "Inter", "Momo Trust Display"} <= set(
        re.findall(r"font-family: '([^']+)'", FONTS_CSS.read_text())
    )
    missing = sorted({name for name in urls if not (FONTS_DIR / name).is_file()})
    assert missing == []


def test_the_policy_allows_fonts_and_styles_only_from_this_site():
    header = "; ".join(csp._shared(False))
    assert not GOOGLE.search(header)
    assert "font-src 'self'" in header


@pytest.mark.parametrize("name", ["roboto-latin.woff2", "inter-latin-ext.woff2", "momo-trust-display-latin.woff2"])
def test_fonts_are_served_publicly_as_woff2(client, name):
    response = client.get(f"/static/fonts/{name}")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "font/woff2"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.data[:4] == b"wOF2"


def test_the_stylesheet_is_public(client):
    response = client.get("/static/css/fonts.css")
    assert response.status_code == 200
    assert b"@font-face" in response.data
