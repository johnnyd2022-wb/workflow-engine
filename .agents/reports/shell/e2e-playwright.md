# shell — E2E Playwright report

Scope: `.agents/specs/shell.md`. Gap-fill mode — ran existing shell-relevant suites as-is,
then added coverage only for ACs with no prior E2E coverage. AC11 (`/initialize`) is
deliberately left untested per the task's instruction: it is an open security finding
being audited in parallel by security-audit this same turn, not a confirmed intended
behavior to lock in a test around.

## Existing suites re-run (unchanged)

`test_pages_render.py`, `test_smoke.py`, `test_landing_regressions.py`,
`test_security_headers.py`, `test_settings_flow.py` — **38 passed**, 0 failed, 0 skipped.

## AC coverage

| AC | Route(s) | Test | Result |
|----|----------|------|--------|
| AC1 | `GET /core` | `test_pages_render.py::test_core_page_renders_clean[/core]` (pre-existing) | pass |
| AC2 | `GET /core/dashboard` | `test_pages_render.py::test_core_page_renders_clean[/core/dashboard]` (pre-existing) | pass |
| AC3 | `GET /core/integrations` | `test_shell_redirects.py::test_ac3_core_integrations_redirects_to_crm_configuration` (new) | **pass** |
| AC4 | `GET /core/settings` | `test_pages_render.py::test_core_page_renders_clean[/core/settings]` (pre-existing) | pass |
| AC5 | `/static/js/<f>`, `/static/css/<f>` | `test_static_asset_security.py` (new): serves real file, Content-Type/Cache-Control, traversal rejection, extension rejection, **missing-file 404** | **7 pass, 2 FAIL — app bug, see Findings** |
| AC6 | `/static/inventory/<f>`, `/static/img/<f>` | `test_static_asset_security.py` (new): allowlisted file served, non-allowlisted-but-valid-extension rejected, traversal rejection | **pass (5/5)** |
| AC7 | `/ui/shared/<f>` | `test_static_asset_security.py` (new): traversal rejection, extension rejection, allowlisted extension served, **missing-file 404**; auth-gate 401 already covered by `test_landing_regressions.py::test_gated_shared_assets_still_require_auth` | **3 pass, 1 FAIL — same app bug** |
| AC8 | `GET /` | `test_smoke.py::test_landing_page_renders_clean` (pre-existing) | pass |
| AC9 | `GET /landing-diagram` | not directly asserted by any suite (excluded from `e2e_coverage.py`'s required set as static chrome); embedding is implicitly exercised via the landing page render. Left uncovered — low risk, static file with no logic, out of the "no coverage today" list the task called out. | n/a |
| AC10 | `GET /dashboard` (app.py alias) | `test_shell_redirects.py::test_ac10_dashboard_alias_redirects_to_core_dashboard` (new, pins 302 + Location); unauthenticated case already covered by `test_landing_regressions.py::test_logged_out_user_cannot_reach_dashboard` | **pass** |
| AC11 | `POST /initialize` | **intentionally not tested** — open finding, being audited in parallel this turn; do not lock in coverage for either the current (unsafe) or a not-yet-decided fixed behavior | n/a |
| AC12 | session inactivity timeout | `test_session_expiry.py` (new): HTML request → 401 + `session_expired.html`; API request → JSON 401 `{"error": "Session expired due to inactivity"}`; control test proves a fresh session is not treated as expired | **pass (3/3)** |

Flake check: new suite run 3× consecutively, identical result each time (22 pass / 3 fail,
same tests every run) — the failures are deterministic, not flaky.

## Findings (app bugs, not fixed — out of this stage's scope)

**Missing static file returns 500, not 404, on 3 of 5 asset-serving routes** —
`serve_core_js`, `serve_core_css`, and `serve_ui_shared` (`app/core/backend/backend.py:1087,1126`,
`app/api/app_factory.py:120`). AC5 and AC7 both require: "missing file is a 404, not a
fallthrough... unexpected exceptions are a 500, not a stack trace leak."

Root cause: on this Werkzeug (3.1.8) / Flask (3.1.3) pin, `send_from_directory` raises
`werkzeug.exceptions.NotFound` for a missing file, not `FileNotFoundError`. `NotFound` is
a subclass of `Exception`, so the routes' `except FileNotFoundError: abort(404)` clause
never fires — the exception falls into the broad `except Exception:` clause instead, which
`logger.exception(...)`s it and does `abort(500)`. A request for a nonexistent static
asset gets a 500 (and a full traceback logged with `exc_info=True`) where the spec — and a
sane client — expects a quiet 404.

`serve_core_inventory_static` and `serve_core_img` (AC6) have the identical
`except FileNotFoundError` / `except Exception` pattern and are very likely affected the
same way, but AC6's routes gate on a hardcoded filename allowlist *before* the file-access
try block, so there is no allowlisted-but-missing-file case to exercise it through the
route as written — every allowlisted name corresponds to a real file on disk. Worth fixing
alongside the other three since it's the same bug, even though this suite can't
demonstrate it black-box.

Confirmed reproducible 3/3 runs. Not fixed here: `serve_core_js`, `serve_core_css`,
`serve_ui_shared` (and by inspection, `serve_core_inventory_static`, `serve_core_img`) all
need `except FileNotFoundError` changed to also catch `werkzeug.exceptions.NotFound` (or
reordered so `NotFound`/`HTTPException` re-raises before the generic `except Exception`
catches it) — that's an app-code change outside this stage's remit (test files + report
only, per this run's task scope). Tests `test_ac5_static_asset_404s_on_missing_file` (both
params) and `test_ac7_ui_shared_404s_on_missing_file_when_authenticated` are written to
assert the **spec-correct** behavior (404) and are left red on purpose, as a gate for
whoever picks this up — not weakened to assert the current 500.

## Files added

- `tests/e2e/test_shell_redirects.py` — AC3, AC10
- `tests/e2e/test_static_asset_security.py` — AC5, AC6, AC7
- `tests/e2e/test_session_expiry.py` — AC12

None of these touch `app/`; only `tests/e2e/*` and this report were written, per the
concurrent security-audit stage's read-only constraint on the rest of the tree.

## Handoff

Not run against `ci-gate` yet — leaving that to the orchestrator once the AC5/AC7 finding
above is triaged (fix-bug or this stage's follow-up), since wiring a suite with 3 known-red
tests into a required check would break the gate on merge.
