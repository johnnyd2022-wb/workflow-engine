---
name: e2e-playwright
description: "Write and run headless Playwright end-to-end tests for the Flask app, mapping each test to an acceptance criterion from the feature spec. Use this skill whenever the user mentions E2E, browser tests, Playwright, smoke tests, or 'does the app actually work', and whenever new-feature or review-feature calls it after a build passes unit tests. E2E runs are ground truth: they replace a human clicking through the app, which is the point of agentic coding."
---

# E2E Playwright

Unit tests prove functions work; E2E proves the app works. For an agent, a passing headless flow is the closest thing to a human saying "yes, I clicked through it and it's fine". Every test here traces to an `AC<n>` from `.agents/specs/<slug>.md` so coverage is auditable, not vibes.

## 0a. Map coverage BEFORE writing anything (deterministic, cheap)

Do not re-derive what is already tested by reading the app and the suite — that burns tokens rediscovering a map a script computes in one pass. Run:

```bash
python3 scripts/e2e_coverage.py --json     # {summary, gaps[], routes[]}; human: drop --json
```

It reports, per `(method, route)`, whether an E2E test exercises it, by matching the real `app.url_map` against the route literals in `tests/e2e/*.py`. Use its `gaps` list to decide what to add; a route already `covered` needs no new test. `--check` exits non-zero if any non-excluded gap remains (a scriptable gate). Static/health/telemetry routes are excluded; form-driven auth endpoints (login/signup/verify-2fa) are marked covered via a small `UI_DRIVEN_COVERAGE` map in the script — extend that map (never add API literals to it) if you cover another endpoint purely through a form. The living page/flow view is `.agents/reports/e2e/coverage-index.md`; `e2e_coverage.py` is the deterministic source of truth behind it.

## 0. One-time setup (skip if present)

Stack: `pytest-playwright`, Chromium, headless. Check `pyproject.toml`'s `dev` extra and `tests/e2e/conftest.py`; create if missing:

```bash
uv add --optional dev pytest-playwright && uv run playwright install --with-deps chromium
```

**Boot the app as `from app.app import app`, with `ENVIRONMENT` unset, over TLS.** All
three parts are load-bearing, and each was wrong in an earlier version of this skill:

- **`app.app:app`, not `create_app()`.** `app/app.py:24` calls `create_app()` and then
  registers `/`, `/dashboard`, `/landing-diagram`, `/healthcheck` and `/initialize` on
  that instance. A bare `create_app()` is blueprint-only: no landing page, so no login
  modal, and every navigation 404s.
- **`ENVIRONMENT` unset, not `ENVIRONMENT=test`.** Unset resolves to `local`
  (`app/utils/config_loader.py:16`), whose `local.ini` points at the test DB on
  `localhost:8401`. `test.ini` targets `host.docker.internal`, which only resolves inside
  Docker, so `ENVIRONMENT=test` **hangs** from a host shell — and Playwright needs a
  host-reachable URL. This matches how pytest is already run here (see CLAUDE.md).
- **Real TLS, not plain HTTP.** `SESSION_COOKIE_SECURE` defaults True and HSTS is only
  set on secure requests (`app/api/app_factory.py:51,337`), so an HTTP boot breaks auth
  and makes the cookie/HSTS assertions untestable. Serve `app/tls/app_cert.pem` and pass
  `ignore_https_errors=True` to the browser context.

`tests/e2e/conftest.py` responsibilities:
- boot the Flask app once per session on an ephemeral port, torn down after (see above
  for exactly how — it is not `create_app()`)
- skip the suite with a stated reason when chromium, the TLS cert, or the test DB is
  absent; an absent dependency is never a failure (suite-warden's rule)
- seed fixtures: at least two orgs and one user per org (tenant tests need a hostile
  neighbor to exist) — import `two_org_two_user` / `OrganisationFactory` /
  `UserFactory` from `tests/factories.py` / `tests/conftest.py` (owned by the
  **test-fixtures** skill) rather than reseeding this here; it's the same world
  security-audit's isolation tests use
- provide a `logged_in_page` fixture that authenticates via the real login flow once and reuses storage state, so every test does not re-click login

Never point E2E at a shared or production database. If only a real environment is available, stop and ask.

## 1. Write tests from the spec

Read the ACs. For each user-visible criterion, one test named for it:

```python
# tests/e2e/<slug>/test_<slug>.py
import re
from playwright.sync_api import Page, expect

def test_ac1_create_work_order(logged_in_page: Page, app_url: str):
    page = logged_in_page
    page.goto(f"{app_url}/work_orders")
    page.get_by_role("button", name="New work order").click()
    page.get_by_label("Title").fill("Batch 42 rerun")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("status")).to_contain_text("created")
    expect(page.get_by_role("row", name=re.compile("Batch 42 rerun"))).to_be_visible()
```

Conventions that keep these stable:
- Select by role and label, never CSS classes or nth-child; add `data-testid` to the template when no accessible handle exists (and prefer fixing the accessibility instead).
- Rely on Playwright auto-waiting `expect()`; `time.sleep` and fixed waits are prohibited, they are the number one source of flakes.
- Each test is independent and seeds its own data through fixtures; no test depends on another's leftovers.
- Assert on outcomes the user cares about (visible row, status message, redirect), not implementation details.

Always include, regardless of ACs:
- **the cross-tenant probe**: log in as org B, request org A's object URL directly, expect 404. This is the E2E twin of the security audit's isolation check.
- **the unhappy path** for every form: invalid input shows an error and does not create a record.

## 2. Run and stabilize

```bash
pytest tests/e2e/<slug> -q --tracing=retain-on-failure
```

On failure, read the trace/screenshot under `test-results/` before touching code; distinguish app bug (hand to the builder with the trace) from test bug (fix the test). On a pass, run the suite three times; any intermittent failure is a bug to fix now, because a flaky gate gets disabled within a month and then protects nothing.

## 3. Report

Write `.agents/reports/<slug>/e2e.md`: table of AC to test to pass/fail, flake check result (3/3), and any ACs with no E2E coverage plus why (e.g. AC is API-only, covered by integration tests). Then hand the suite to ci-gate so it becomes a required check; an E2E suite that only runs when someone remembers is decoration.

## Rules

- Performance budgets are NOT this skill's job: `tests/e2e/test_perf_budgets.py` is owned by **perf-guardrails** (spec D2's advisory tier, budgets in `.agents/perf/budgets.json`). When a new flow adds a significant page or API route, tell perf-guardrails (or its caller) so the measure lists grow with the app.
- Keep the suite lean: critical flows per feature plus signup/login/billing smoke tests globally. E2E minutes are expensive; depth belongs in unit and integration tests.
- Never mark an AC covered by a test that does not genuinely exercise it end to end.
- Do not screenshot-diff by default; visual regression is a separate decision with real maintenance cost.
