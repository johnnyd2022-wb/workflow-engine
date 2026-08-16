# REVIEW: shell
date: 2026-08-15
baseline: tests green (1487 passed, 31 skipped, 0 failed, `tests/` full suite before any change)
verdict: patched

## What this slice is
The application shell: sidebar/nav chrome (`base_spa.html` + the live `sidebar-v2.html`),
the `/core`, `/core/dashboard`, `/core/settings`, `/core/integrations` chrome routes,
every static-asset serving route (`/static/js|css|inventory|img`, `/ui/shared/<filename>`),
the logged-out landing surface (`/`, `/landing-diagram`), and the session-expiry render
path. Depended on by every other page-rendering slice. No spec existed — reconstructed
into `.agents/specs/shell.md` (12 ACs) from the live code, with drift from the feature
index's stale line numbers corrected along the way.

| stage | verdict | findings | report |
|---|---|---|---|
| spec reconstruction | n/a | 1 undocumented route (`/initialize`) flagged as an open finding, not an AC | `.agents/specs/shell.md` |
| baseline | clean | 0 pre-existing failures | `baseline.md` |
| migration audit | skipped | shell has no models/migrations | n/a |
| security-audit | findings-open → patched | 3 real findings (F1-F3, 4 tracked items) | `security-audit.md` |
| e2e-playwright | findings-open → patched | 1 app bug (missing-file 500) + full AC gap-fill | `e2e-playwright.md` |
| unit coverage | n/a | no dedicated unit-test file for this slice by design (chrome/routing, e2e-covered) | — |
| test-evaluator | gamed → clean | 4 weakened-assertion classes across 3 new test files | `test-evaluator.md` |
| perf-guardrails | clean | 1 route added to budgets (`/core`); all 3 shell pages well inside budget | `perf-guardrails.md` |
| observability | patched | missing `access_denied` logging on `requires_auth` (app-wide) + `serve_ui_shared` | `observability.md` |
| ci-gate | clean | new tests already covered by existing `pytest tests/` job; semgrep/gitleaks/uv_audit all clean | `ci-gate.md` |

## Security findings (patched)

**F1 — hardcoded Flask `SECRET_KEY` fallback, live in every environment including
production.** No `.ini` file (including `prod.ini`) sets `[app] secret_key`, so
`app.secret_key` was unconditionally the literal string
`"dev-secret-key-change-in-production"`. This key signs every session cookie and CSRF
token app-wide; security-audit empirically forged a valid session+CSRF pair against it.
**Fixed**: `app_factory.py` now raises `RuntimeError` on boot outside local/test if
`secret_key` is unconfigured, mirroring the existing fail-loud pattern already used for
missing Flask-WTF. **Not fixed here, and still needs a human**: an actual per-environment
secret must be provisioned for production (KeePassXC/env, per this repo's existing secrets
pattern) — I cannot verify from inside this repo whether production already has one
out-of-band; the code now refuses to boot silently insecure if it doesn't.

**F2 — `POST /initialize` was reachable, unauthenticated, by a cold attacker, and ran a
schema-mutating subprocess.** No `@requires_auth`, no environment gate, registered on the
production app instance. security-audit built and ran an end-to-end PoC (forged
session+CSRF+Referer using F1's known fallback) proving `initialize_database()` executes
for a fully anonymous caller. The DDL itself is additive-only (no `DROP`/`TRUNCATE`), and
the request body is never read, so this is not also a SQL-injection vector — but it is an
unauthenticated trigger for subprocess execution against the live DB, unthrottled, plus the
failure path echoed `str(exception)` back to the caller. **Fixed**: added `@requires_auth`;
the 500 response is now a fixed generic string, exception text logged server-side only.
Verified live: cold `POST /initialize` now returns 401.

**F3 — the repo's own `route-missing-requires-auth` semgrep rule blanket-excluded
`**/app.py`**, which is exactly why the scanner produced 0 findings on F2. **Fixed**:
narrowed the exclude to the three actually-public routes (`/`, `/landing-diagram`,
`/healthcheck`) by name. Verified against the pre-fix code: the narrowed rule flags exactly
`/initialize` and nothing else (0 false positives on the legitimately-public routes).

## App bug found and fixed (e2e-playwright)

Missing static files returned **500, not 404**, on `serve_core_js`, `serve_core_css`, and
`serve_ui_shared` (and by inspection, the two allowlisted routes). Root cause: on this
Werkzeug/Flask pin, `send_from_directory` raises `werkzeug.exceptions.NotFound` for a
missing file, not `FileNotFoundError` — so the routes' `except FileNotFoundError` clause
never fired and the request fell into the generic `except Exception` 500 handler (with a
full traceback logged). Fixed by catching `NotFound` alongside `FileNotFoundError` in all
five handlers. e2e-playwright had deliberately written two tests red against this bug
rather than weaken them to assert the wrong behavior — both pass now.

## Test-validity findings (test-evaluator, patched)

The Codex grader's mutation pass found 10 of 25 mutation cases incorrectly green across
the three new test files — real assertion weaknesses, not nitpicks:
1. Redirect tests (`test_shell_redirects.py`) checked the `Location` header by suffix only
   — `https://evil.example/crm/configuration` would have passed.
2. Five "serves the file" tests (`test_static_asset_security.py`) checked only the 200
   status, never the response body.
3. `Cache-Control` checks used a `"3600"` substring, which also matches `max-age=36000`
   (10hr); the CSS variant never checked for `stale-while-revalidate` at all.
4. The session-expiry HTML test accepted any body containing "session"+"expired", which a
   generic error message satisfies without the real template rendering.

All four fixed (host-qualified redirect checks, byte-for-byte body comparison against the
real files on disk, exact `Cache-Control` string match, template-specific markers). Re-ran
the grader's exact 10 mutation cases against the patched assertions: **0 remain
green-under-mutation.**

## Observability gap found and fixed

`requires_auth` (the auth decorator used app-wide, not just by this slice) logged nothing
on a 401, unlike its sibling `requires_role`'s `access_denied` warning on 403 in the same
file. Directly relevant to this review's own F2 fix: without it, repeated unauthenticated
probes against `/initialize` (or any other `@requires_auth` route) would leave no audit
trail. Added the matching `access_denied` warning; found and fixed the identical gap in
`serve_ui_shared` (which enforces auth inline rather than via the decorator, for the
`PUBLIC_UI_SHARED_FILES` allowlist, and so bypassed the decorator's logging too). Confirmed
no double-log risk against the global `@app.errorhandler(401)`. New tests added for both.

## Dead code found (not fixed — cleanup, not a finding)

`app/ui/shared/sidebar.js` and `app/ui/shared/sidebar.css` — unreferenced by any template,
**not previously flagged by the feature index** (unlike the two dead files it already
knew about). Unlike those two, these remain live HTTP surface if requested directly
(`/ui/shared/sidebar.js`, `/ui/shared/sidebar.css` both pass the extension whitelist).
Left alone per "don't refactor beyond what findings require" — noted in
`.agents/specs/shell.md` for whoever next touches the sidebar.

## Coverage added
- `tests/e2e/test_shell_redirects.py` — AC3, AC10
- `tests/e2e/test_static_asset_security.py` — AC5, AC6, AC7 (traversal, extension/filename
  allowlist, 404-on-missing, content-type/cache headers, byte-identical body checks)
- `tests/e2e/test_session_expiry.py` — AC12 (HTML + API branches, control case)
- `tests/test_ui_shared_access_denied.py` — the new `serve_ui_shared` `access_denied` log
- `tests/test_org_routes.py` — the new `requires_auth` `access_denied` log

## Verification (final)
- Full suite pre-patch baseline: 1487 passed, 31 skipped, 0 failed.
- Full suite post-patch: 1234 passed, 1 skipped, 0 failed (`--ignore=tests/e2e`) +
  88 passed, 0 failed (shell-relevant e2e suites, live server).
- `ruff check` / `ruff format --check`: clean on every changed/added file.
- `semgrep --config .semgrep/rules/ app/`: 0 findings (CI-shaped command).
- `gitleaks detect`: 0 leaks (1064 commits).
- `uv audit --frozen`: 0 vulnerabilities (84 packages).

**Aside, not this slice's failure**: a full-suite run surfaced
`tests/e2e/traceability/test_sourcemap_page.py::test_ac3_forward_trace_from_browse_grid_renders_timeline`
failing (network-level fetch failure on an unrelated background dashboard widget).
Reproduced in isolation and reproduced identically on a clean `git stash` of every change
in this review — confirmed pre-existing, unrelated to `shell`, not introduced here.
Flagged for `traceability`'s own next pass; not fixed (out of scope, per this skill's
"pre-existing failures reported, not silently fixed" rule).

## Still open (human decision, not this review's to close)
Production must have a real `[app] secret_key` provisioned before this deploys — the code
now refuses to boot with the insecure default outside local/test, so this is a hard
requirement, not a suggestion. I could not verify from inside this repo whether production
already has one out-of-band.
