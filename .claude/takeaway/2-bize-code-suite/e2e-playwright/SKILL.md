---
name: e2e-playwright
description: "Write and run headless Playwright end-to-end tests for the Flask app, mapping each test to an acceptance criterion from the feature spec. Use this skill whenever the user mentions E2E, browser tests, Playwright, smoke tests, or 'does the app actually work', and whenever new-feature or review-feature calls it after a build passes unit tests. E2E runs are ground truth: they replace a human clicking through the app, which is the point of agentic coding."
---

# E2E Playwright

Unit tests prove functions work; E2E proves the app works. For an agent, a passing headless flow is the closest thing to a human saying "yes, I clicked through it and it's fine". Every test here traces to an `AC<n>` from `.agents/specs/<slug>.md` so coverage is auditable, not vibes.

## 0. One-time setup (skip if present)

Stack: `pytest-playwright`, Chromium, headless. Check `requirements-dev.txt` and `tests/e2e/conftest.py`; create if missing:

```bash
pip install pytest-playwright && playwright install --with-deps chromium
```

`tests/e2e/conftest.py` responsibilities:
- boot the Flask app once per session against a throwaway test database (factory pattern: `create_app("testing")`), on an ephemeral port, torn down after
- seed fixtures: at least two orgs and one user per org (tenant tests need a hostile neighbor to exist)
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

- Keep the suite lean: critical flows per feature plus signup/login/billing smoke tests globally. E2E minutes are expensive; depth belongs in unit and integration tests.
- Never mark an AC covered by a test that does not genuinely exercise it end to end.
- Do not screenshot-diff by default; visual regression is a separate decision with real maintenance cost.
