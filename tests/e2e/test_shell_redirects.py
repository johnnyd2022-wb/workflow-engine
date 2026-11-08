"""AC10: a shell route whose entire contract is "redirect somewhere else", and AC3's old
redirect, which plan 2.5 replaced with a page of its own.

`test_pages_render.py` and `test_landing_regressions.py` already navigate through
`/core/integrations` and `/dashboard` via `page.goto`, which auto-follows redirects and
only proves the browser eventually lands somewhere with a <400 status -- a route that
satisfied that by rendering its own 200 page instead of redirecting would pass both
silently. These pin the redirect itself: status code and `Location` header.
"""

import pytest

pytestmark = pytest.mark.e2e


def test_ac3_core_integrations_is_its_own_settings_page(logged_in_page, app_url):
    # AC3 redirected this into Sales settings; plan 2.5 makes it the Settings home for Xero.
    response = logged_in_page.request.get("/core/integrations", max_redirects=0)
    assert response.status == 200, f"expected the Integrations page itself, got {response.status}"
    assert "Integrations" in response.text()


def test_ac10_dashboard_alias_redirects_to_core_dashboard(logged_in_page, app_url):
    response = logged_in_page.request.get("/dashboard", max_redirects=0)
    assert response.status == 302, f"expected a 302 redirect, got {response.status}"
    location = response.headers.get("location", "")
    expected = f"{app_url.rstrip('/')}/core/dashboard"
    # Host-qualified, not a suffix check: a suffix match would also accept
    # https://evil.example/core/dashboard as a "pass" (open-redirect regression).
    assert location == expected or location == "/core/dashboard", (
        f"unexpected redirect target: {location!r} (expected {expected!r} or a relative "
        f"same-origin path, not an external host)"
    )
