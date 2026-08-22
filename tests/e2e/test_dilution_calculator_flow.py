"""Dilution calculator: a stateless, tenant-data-free production-floor tool.

Spec: .agents/specs/dilution_calculator.md. Unlike most features in this suite there is
no tenant-scoped resource to create or cross-tenant-probe here (spec: "tenant_scoped: no
... touches no org_id-scoped table") — the route is auth-gated but reads/writes nothing,
so the cross-tenant isolation check the skill otherwise mandates does not apply. What
matters instead: the page is genuinely auth-gated (AC6), a real browser round trip through
the form produces the documented worked example (AC1/AC2 — the brief's own 40% ABV /
1000 mL / 20% ABV -> 2000 mL example, with a contraction-aware water figure that is
strictly more than the naive 1000 mL), and the one uniform validation rule (AC5) surfaces
as a real, visible error in the UI rather than a silent failure or a raw 500.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import assert_clean_page, attach_probe, csrf_headers

pytestmark = pytest.mark.e2e


def _numeric(text: str) -> float:
    """Strip locale formatting (thousands separators, trailing unit) from displayed text."""
    cleaned = text.replace(",", "").replace("mL", "").strip()
    return float(cleaned)


# ---------------------------------------------------------------------------------
# AC6: GET /dilution-calculator is auth-gated
# ---------------------------------------------------------------------------------


def test_dilution_calculator_page_requires_auth(page: Page, app_url: str):
    """A logged-out browser must never be served the calculator page.

    app_factory.py's global 401 handler redirects browser GETs for non-API/non-static
    paths to "/" (302), the same mechanism test_smoke.py's dashboard check relies on.
    """
    attach_probe(page)
    response = page.goto("/dilution-calculator")
    assert response is not None, "no response for /dilution-calculator"
    assert not page.url.rstrip("/").endswith("/dilution-calculator"), (
        f"dilution calculator page served to a logged-out browser: {page.url}"
    )
    # Landed back on the public landing page, not an error page.
    expect(page.get_by_role("button", name="Sign In").first).to_be_visible()


def test_dilution_calculator_api_requires_auth(page: Page, app_url: str):
    """A logged-out caller must never get a calculation back from the solve endpoint.

    In practice this POST is rejected before it even reaches `@requires_auth`: CSRF
    protection (Flask-WTF, global except /auth/*, see conftest.csrf_headers) runs
    ahead of the auth check and returns 400 "The CSRF token is missing" for a
    token-less POST regardless of session state — confirmed directly against the
    running server (`curl -X POST .../solve` with no cookies/token -> 400, CSRF
    message). So a plain 401 assertion here would be testing a code path this route
    never actually reaches without valid CSRF too. What's true and worth asserting:
    no unauthenticated, token-less caller ever gets a 200 with a solved result —
    same defensive shape as test_crm_customers_api_requires_auth for the equivalent
    CRM check.
    """
    response = page.request.post(
        "/api/dilution-calculator/solve",
        data={
            "solve_for": "final_volume_ml",
            "starting_abv": 40,
            "starting_volume_ml": 1000,
            "final_abv": 20,
        },
    )
    assert response.status != 200, f"expected the solve to be rejected, got 200: {response.text()}"
    assert response.status in (400, 401), f"expected a CSRF (400) or auth (401) rejection, got {response.status}"
    assert "solved_value" not in response.text(), "unauthenticated caller received a solved result"


def test_dilution_calculator_page_renders_for_authenticated_user(logged_in_page: Page):
    """AC6's positive case: an authenticated org member gets the real page, cleanly."""
    page = logged_in_page
    response = page.goto("/dilution-calculator")
    assert response is not None and response.status < 400, (
        f"/dilution-calculator returned {response.status if response else 'no response'}"
    )
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Dilution Calculator")).to_be_visible()
    expect(page.get_by_role("button", name="Calculate")).to_be_visible()
    assert_clean_page(page)


# ---------------------------------------------------------------------------------
# AC1/AC2: real browser walkthrough of the brief's own worked example
# ---------------------------------------------------------------------------------


def test_solve_final_volume_matches_worked_example(logged_in_page: Page):
    """Starting ABV=40, starting volume=1000 mL, final ABV=20, solve for final volume.

    AC2 pins two separate numbers in the same response:
    - solved_value (final_volume_ml) must equal 2000 within 1e-6 — the exact
      C1V1=C2V2 identity, no contraction adjustment.
    - water_to_add_ml (contraction-aware) must be strictly greater than
      water_to_add_naive_ml (1000 mL) — contraction only shows up there.

    Driven entirely through the real form: solve_for is picked via the UI toggle
    (not just relying on it already being the default), values are typed into the
    labelled inputs, and the result is read back from the rendered page.
    """
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    # Explicitly select solve_for=final_volume_ml via the UI toggle.
    page.get_by_role("button", name="Final volume (mL)").click()

    # The field being solved for is disabled — filling only the other three.
    expect(page.locator("#dilcalc-final_volume_ml")).to_be_disabled()

    page.get_by_label("Starting ABV (%)").fill("40")
    page.get_by_label("Starting volume (mL)").fill("1000")
    page.get_by_label("Final ABV (%)").fill("20")

    page.get_by_role("button", name="Calculate").click()

    result = page.get_by_test_id("dilcalc-result")
    expect(result).to_be_visible()

    solved_text = page.get_by_test_id("dilcalc-solved-value").inner_text()
    solved_value = _numeric(solved_text)
    assert solved_value == pytest.approx(2000, abs=1e-6), (
        f"final_volume_ml should be 2000 (C1V1=C2V2, no contraction adjustment), got {solved_value} "
        f"(raw text {solved_text!r})"
    )

    water_to_add_text = page.get_by_test_id("dilcalc-water-to-add").inner_text()
    water_to_add = _numeric(water_to_add_text)
    assert water_to_add > 1000, (
        f"water_to_add_ml (contraction-aware) must be strictly greater than the naive 1000 mL, "
        f"got {water_to_add} (raw text {water_to_add_text!r})"
    )

    naive_text = page.get_by_test_id("dilcalc-water-to-add-naive").inner_text()
    naive_value = _numeric(naive_text)
    assert naive_value == pytest.approx(1000, abs=1e-6), f"naive water figure should be exactly 1000, got {naive_value}"
    assert water_to_add > naive_value, "contraction-aware water figure must exceed the naive additive figure"

    assert_clean_page(page)


def test_solve_final_volume_via_api_matches_ui_result(logged_in_page: Page):
    """Same worked example driven straight at the API (AC1's response shape), as a
    second, independent confirmation of the numbers the UI test reads off the DOM —
    catches a bug where the UI happened to render the right thing from a wrong payload,
    or vice versa."""
    page = logged_in_page
    response = page.request.post(
        "/api/dilution-calculator/solve",
        headers=csrf_headers(page),
        data={
            "solve_for": "final_volume_ml",
            "starting_abv": 40,
            "starting_volume_ml": 1000,
            "final_abv": 20,
        },
    )
    assert response.status == 200, f"solve failed: {response.status} {response.text()}"
    body = response.json()

    assert body["solved_field"] == "final_volume_ml"
    assert body["solved_value"] == pytest.approx(2000, abs=1e-6)
    assert body["water_to_add_ml"] > body["water_to_add_naive_ml"] == pytest.approx(1000, abs=1e-6)
    assert "disclaimer" in body and body["disclaimer"], "AC8: disclaimer must be present"


# ---------------------------------------------------------------------------------
# AC5: the uniform direction rule, exercised as a real, visible UI error
# ---------------------------------------------------------------------------------


def test_invalid_direction_shows_error_in_ui_not_silent_failure(logged_in_page: Page):
    """Submitting final_abv >= starting_abv (here solving final_volume_ml, so the
    direction check fires against the given pair) must render a visible error and must
    not produce a result — a silent failure (blank screen, swallowed rejection) would
    be worse than a loud one for a tool used live on a production floor."""
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    # solve_for=final_volume_ml is the default; keep it explicit for clarity.
    page.get_by_role("button", name="Final volume (mL)").click()

    page.get_by_label("Starting ABV (%)").fill("20")
    page.get_by_label("Starting volume (mL)").fill("1000")
    page.get_by_label("Final ABV (%)").fill("40")  # final >= starting: invalid dilution direction

    page.get_by_role("button", name="Calculate").click()

    error = page.get_by_test_id("dilcalc-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("final_abv must be less than starting_abv")

    # No result rendered alongside the error.
    expect(page.get_by_test_id("dilcalc-result")).to_be_hidden()

    assert_clean_page(page)


def test_ac5_solving_abv_field_rejects_shrinking_volume_in_ui(logged_in_page: Page):
    """AC5's other branch: when solve_for is an ABV field, the check flips to
    final_volume_ml <= starting_volume_ml. The existing AC5 test only exercises the
    volume-field branch (solve_for=final_volume_ml); this covers the ABV-field branch
    end to end through the real form."""
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Final ABV (%)").click()
    expect(page.locator("#dilcalc-final_abv")).to_be_disabled()

    page.get_by_label("Starting ABV (%)").fill("40")
    page.get_by_label("Starting volume (mL)").fill("1000")
    page.get_by_label("Final volume (mL)").fill("500")  # not > starting_volume_ml: invalid

    page.get_by_role("button", name="Calculate").click()

    error = page.get_by_test_id("dilcalc-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("final_volume_ml must be greater than starting_volume_ml")
    expect(page.get_by_test_id("dilcalc-result")).to_be_hidden()

    assert_clean_page(page)


def test_ac5_divisor_guard_final_abv_zero_shows_error_in_ui(logged_in_page: Page):
    """AC5's explicit divisor guard: final_abv=0 passes the `final_abv < starting_abv`
    pair check but is the divisor for solving final_volume_ml, so it must be rejected
    with its own distinct message (not a ZeroDivisionError, not a blank/500 page) —
    exercised here as a real form submission, not just the service-level unit test."""
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Final volume (mL)").click()

    page.get_by_label("Starting ABV (%)").fill("40")
    page.get_by_label("Starting volume (mL)").fill("1000")
    page.get_by_label("Final ABV (%)").fill("0")

    page.get_by_role("button", name="Calculate").click()

    error = page.get_by_test_id("dilcalc-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("final_abv must be greater than 0 to solve for final_volume_ml")
    expect(page.get_by_test_id("dilcalc-result")).to_be_hidden()

    assert_clean_page(page)


# ---------------------------------------------------------------------------------
# AC4: server-side validation errors surfaced in the UI, beyond the direction check
# ---------------------------------------------------------------------------------


def test_ac4_abv_out_of_range_shows_error_in_ui(logged_in_page: Page):
    """An ABV outside [0, 100] passes the client's own required/finite checks (140 is a
    finite number) so this is a genuine server round trip, not client-side validation —
    proves AC4's range check is actually wired to a visible error, not just a unit test."""
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Final volume (mL)").click()

    page.get_by_label("Starting ABV (%)").fill("140")
    page.get_by_label("Starting volume (mL)").fill("1000")
    page.get_by_label("Final ABV (%)").fill("20")

    page.get_by_role("button", name="Calculate").click()

    error = page.get_by_test_id("dilcalc-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("'starting_abv' must be between 0 and 100")
    expect(page.get_by_test_id("dilcalc-result")).to_be_hidden()

    assert_clean_page(page)


def test_ac4_non_positive_volume_shows_error_in_ui(logged_in_page: Page):
    """0 is a finite number, so the client's own validation lets it through — this
    exercises the server's volume > 0 rule as a real round trip."""
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Final volume (mL)").click()

    page.get_by_label("Starting ABV (%)").fill("40")
    page.get_by_label("Starting volume (mL)").fill("0")
    page.get_by_label("Final ABV (%)").fill("20")

    page.get_by_role("button", name="Calculate").click()

    error = page.get_by_test_id("dilcalc-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("'starting_volume_ml' must be greater than 0")
    expect(page.get_by_test_id("dilcalc-result")).to_be_hidden()

    assert_clean_page(page)


def test_ac4_blank_required_field_shows_error_in_ui_without_calling_api(logged_in_page: Page):
    """A blank required field is caught client-side before any fetch — the message text
    ("Final ABV (%) is required", the field's display label) is distinct from the
    server's own missing-field message ("'final_abv' is required", the raw field name),
    so asserting on the client wording confirms this path never reaches the API."""
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Final volume (mL)").click()

    page.get_by_label("Starting ABV (%)").fill("40")
    page.get_by_label("Starting volume (mL)").fill("1000")
    # Final ABV left blank.

    page.get_by_role("button", name="Calculate").click()

    error = page.get_by_test_id("dilcalc-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("Final ABV (%) is required")
    expect(page.get_by_test_id("dilcalc-result")).to_be_hidden()

    assert_clean_page(page)


# ---------------------------------------------------------------------------------
# AC3 (round-trip, symmetric across all four solve directions) driven through the UI,
# which as a side effect exercises the two solve_for directions (final_abv,
# starting_abv/starting_volume_ml) the tests above never click through.
#
# Numbers are chosen (matching the spec's own worked example / the unit test's round
# trip fixtures) so every intermediate solved_value is an exact whole number. The
# result is displayed via `toLocaleString(maximumFractionDigits: 2)`, i.e. rounded for
# display — feeding a *non*-whole displayed value back into the next step would fail
# AC3's 1e-6 tolerance for a UI-rendering reason unrelated to the calculation itself.
# ---------------------------------------------------------------------------------


def test_ac3_round_trip_final_volume_then_final_abv_via_ui(logged_in_page: Page):
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    # Step 1: solve final_volume_ml from (a=40, b=1000, c=20) -> exact 2000.
    page.get_by_role("button", name="Final volume (mL)").click()
    page.get_by_label("Starting ABV (%)").fill("40")
    page.get_by_label("Starting volume (mL)").fill("1000")
    page.get_by_label("Final ABV (%)").fill("20")
    page.get_by_role("button", name="Calculate").click()

    result = page.get_by_test_id("dilcalc-result")
    expect(result).to_be_visible()
    solved_final_volume = _numeric(page.get_by_test_id("dilcalc-solved-value").inner_text())
    assert solved_final_volume == pytest.approx(2000.0, abs=1e-6)

    # Step 2: switch to solving final_abv, feed the solved final_volume_ml back in
    # alongside the same (a, b). starting_abv/starting_volume_ml fields keep their
    # step-1 values; only final_abv (now the target) and final_volume_ml need filling.
    page.get_by_role("button", name="Final ABV (%)").click()
    expect(page.locator("#dilcalc-final_abv")).to_be_disabled()
    page.get_by_label("Final volume (mL)").fill(str(solved_final_volume))
    page.get_by_role("button", name="Calculate").click()

    expect(result).to_be_visible()
    solved_final_abv = _numeric(page.get_by_test_id("dilcalc-solved-value").inner_text())
    assert solved_final_abv == pytest.approx(20.0, abs=1e-6), (
        f"round trip through the UI should recover the original final_abv=20, got {solved_final_abv}"
    )

    assert_clean_page(page)


def test_ac3_round_trip_starting_volume_then_starting_abv_via_ui(logged_in_page: Page):
    page = logged_in_page
    page.goto("/dilution-calculator")
    page.wait_for_load_state("networkidle")

    # Step 1: solve starting_volume_ml from (starting_abv=40, final_abv=20,
    # final_volume_ml=2000) -> exact 1000.
    page.get_by_role("button", name="Starting volume (mL)").click()
    expect(page.locator("#dilcalc-starting_volume_ml")).to_be_disabled()
    page.get_by_label("Starting ABV (%)").fill("40")
    page.get_by_label("Final ABV (%)").fill("20")
    page.get_by_label("Final volume (mL)").fill("2000")
    page.get_by_role("button", name="Calculate").click()

    result = page.get_by_test_id("dilcalc-result")
    expect(result).to_be_visible()
    solved_starting_volume = _numeric(page.get_by_test_id("dilcalc-solved-value").inner_text())
    assert solved_starting_volume == pytest.approx(1000.0, abs=1e-6)

    # Step 2: switch to solving starting_abv, feed the solved starting_volume_ml back
    # in. final_abv/final_volume_ml fields keep their step-1 values (20 / 2000).
    page.get_by_role("button", name="Starting ABV (%)").click()
    expect(page.locator("#dilcalc-starting_abv")).to_be_disabled()
    page.get_by_label("Starting volume (mL)").fill(str(solved_starting_volume))
    page.get_by_role("button", name="Calculate").click()

    expect(result).to_be_visible()
    solved_starting_abv = _numeric(page.get_by_test_id("dilcalc-solved-value").inner_text())
    assert solved_starting_abv == pytest.approx(40.0, abs=1e-6), (
        f"round trip through the UI should recover the original starting_abv=40, got {solved_starting_abv}"
    )

    assert_clean_page(page)
