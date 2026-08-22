# e2e-playwright — process_templates

verdict: patched

## What happened

Two invocations of this stage ended up running concurrently against the same worktree
(orchestrator error: a herdr-tab launch was mistakenly duplicated with a second direct
invocation before confirming the first was still working — see `rounds.md`). One
process detected the collision mid-run and correctly stood down rather than keep
overwriting files; the other's work survived: `tests/e2e/process_templates/conftest.py`
and `tests/e2e/process_templates/test_process_templates_flow.py` (8 tests covering AC1,
AC2, AC3, AC5, AC10, AC12, AC13, using the existing `attach_probe`/`assert_clean_page`/
`fresh_user`/`login_through_ui` conventions from `tests/e2e/conftest.py`).

Running that suite for the first time surfaced two **real, deterministic bugs** in the
build — not flakiness, not test-authoring issues (though one test-authoring issue was
also found and fixed, see below). Both are fixed below and covered by this same suite,
which is now fully green (8/8).

## Findings — real bugs, fixed

### F1: static-asset route always 401'd → browser silently got HTML instead of the JS/CSS

`app/features/process_templates/process_templates_bp.py`'s asset route was named
`static` (Flask endpoint `process_templates.static`). `app/api/middleware/tenant_context.py:71`
treats any endpoint ending `.static` as public and skips loading `g.current_user` for
it — the convention exists for Flask's own built-in per-blueprint static folder, which
is legitimately unauthenticated. My route reused that name but kept `@requires_auth` on
top, so `g.current_user` was never set and every request 401'd — for every user,
authenticated or not, always. The app's global 401 handler (`app_factory.py:322`) then
redirected the browser to `/` because the path doesn't start with `/static/`, `/api/`,
or `/auth/` — so the browser followed the 302, got the SPA shell's HTML back for what it
expected to be a script/stylesheet, and Chromium silently refused to execute/apply it
(MIME-type mismatch), logging a console error but never surfacing as a Python-side
failure. Nothing about the catalogue page rendered because `template-catalog.js` never
actually ran.

**Fix:** renamed the route function to `serve_process_templates_static` (endpoint
`process_templates.serve_process_templates_static`), which doesn't match the `.static`
suffix, so `@requires_auth` now works as intended.

**Pre-existing sibling bug, not fixed (out of scope for this feature):**
`app/features/compliant/compliant_bp.py`'s asset route has the identical pattern —
`@bp.route("/compliant/static/<path:filename>") @requires_auth def static(...)`. It
will have the exact same always-401-redirects-to-`/` failure mode. Flagging for a
human/`findings-sweep` to fix; not touched here since it belongs to a different feature
and this stage's mandate is process_templates' own diff.

### F2: modal overlay's `display: flex` defeated the `hidden` attribute

`app/features/process_templates/frontend/static/template-catalog.css`'s
`.pt-modal-overlay` rule set `display: flex` unconditionally. Author stylesheets
override the browser's default `[hidden] { display: none }` UA rule, so setting the
element's `hidden` attribute (as the JS does to show/hide the preview modal) had no
visual effect — the invisible-but-still-`display:flex` overlay sat on top of the page
and intercepted every click, timing out `test_ac13`'s "Use this template" click with
Playwright's own diagnostic confirming it (`<div hidden="" class="pt-modal-overlay">…
intercepts pointer events`).

**Fix:** added `.pt-modal-overlay[hidden] { display: none; }`.

## Findings — test-authoring, fixed

### F3: `test_ac5_family_filter_narrows_the_card_grid` locator ambiguity

`get_by_role("button", name="Winery / Vineyard")` matched the family filter chip *and*
every Winery/Vineyard template card (each card's accessible name includes its family
label as visible text) — 7 elements, a Playwright strict-mode violation. Scoped the
locator to `[data-pt-family-filters]` so it only matches the chip.

## Coverage

8/8 green: `tests/e2e/process_templates/test_process_templates_flow.py` — the chooser
at its own URL (AC1), an org without Compliant seeing an empty catalogue and getting
404 on a direct template id (AC2, AC3), the catalogue page listing/filtering cards and
showing the advisory (AC5, AC10, AC12), and the full copy → wizard-summary flow with
the copied step visible in `#flow-compliance-panel` (AC6, AC13).

Also re-ran `tests/e2e/test_process_wizard_flow.py` (25 tests, all green) to confirm
the earlier build-time regression (the chooser originally modified the shared
`/core/flows/create` route) stays fixed now that it lives at its own
`/core/flows/create/start` route.

VERDICT: patched
