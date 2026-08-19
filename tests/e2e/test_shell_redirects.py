"""AC3 and AC10: two shell routes whose entire contract is "redirect somewhere else".

`test_pages_render.py` and `test_landing_regressions.py` already navigate through
`/core/integrations` and `/dashboard` via `page.goto`, which auto-follows redirects and
only proves the browser eventually lands somewhere with a <400 status -- a route that
satisfied that by rendering its own 200 page instead of redirecting would pass both
silently. These pin the redirect itself: status code and `Location` header.
"""

import pytest

pytestmark = pytest.mark.e2e


def test_ac3_core_integrations_redirects_to_crm_configuration(logged_in_page, app_url):
    response = logged_in_page.request.get("/core/integrations", max_redirects=0)
    assert response.status == 302, f"expected a 302 redirect, got {response.status}"
    location = response.headers.get("location", "")
    expected = f"{app_url.rstrip('/')}/crm/configuration"
    # Host-qualified, not a suffix check: a suffix match would also accept
    # https://evil.example/crm/configuration as a "pass" (open-redirect regression).
    assert location == expected or location == "/crm/configuration", (
        f"unexpected redirect target: {location!r} (expected {expected!r} or a relative "
        f"same-origin path, not an external host)"
    )


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
