# TEST-EVALUATOR: shell
date: 2026-08-15
invoked_as: chain stage (read-only grader — access: read, codex/gpt-5.6-sol, sandbox
read-only). Its own write of this report was rejected by the sandbox
(`patch rejected: writing is blocked by read-only sandbox`), per
`.agents/verification-chain.md` §5: the orchestrator captures the grader's verbatim final
message and writes this file on its behalf. Content below is that message, transcribed
from the pane, not edited for substance.
verdict: findings-open (gamed) → patched, see addendum below

## What was graded
`tests/e2e/test_shell_redirects.py`, `tests/e2e/test_static_asset_security.py`,
`tests/e2e/test_session_expiry.py` — the three new files from this review's
e2e-playwright stage — plus a direct probe of the two security patches
(`app/app.py` `/initialize`, `app/api/app_factory.py` secret_key fail-closed behavior).

## Execution evidence (grader's own runs)
- Exact in-process execution of the app-level assertions: 25/25 passed. Confirmed the
  missing-file cases now return 404 (the NotFound-catching fix).
- Live pytest against the running app server: 25 skipped — Playwright browser startup
  timed out inside the grader's sandbox (direct localhost sockets were sandbox-denied to
  the codex process). Not a finding about the tests; a grader-environment limitation. The
  orchestrator separately ran the full suite live (63/63 passed, see
  `.agents/reports/shell/e2e-playwright.md` follow-up run) — that result stands.
- Security patches: `/initialize` unauthenticated → 401, initializer never called;
  authenticated request whose initializer raises → fixed generic 500 body, exception text
  absent. Production boot with `secret_key` unset → `RuntimeError` mentioning
  `secret_key`. All confirmed via direct probe, matching the orchestrator's own
  verification.

## Falsifiability (mutation) pass
For each new test, the grader constructed a fake Playwright `Page`/response returning a
plausible-but-wrong value for exactly the behavior that test's name claims to guard, then
called the test function against it. A test that stays green under a mutation that
violates its own named behavior is not proving that behavior. Result: **15 correctly
red, 10 incorrectly green** out of 25 mutation cases — grouped into four assertion
problems:

### 1. `tests/e2e/test_shell_redirects.py:18-28` — suffix-only redirect target
Both `test_ac3_core_integrations_redirects_to_crm_configuration` and
`test_ac10_dashboard_alias_redirects_to_core_dashboard` check only that the `Location`
header **ends with** the expected path, not that it points at this app at all. A mutated
response with `Location: https://evil.example/crm/configuration` (or
`.../core/dashboard`) still passes. An open-redirect regression on either route would go
undetected.

### 2. `tests/e2e/test_static_asset_security.py:32-39,83-96,127-129` — status-only "serves file" assertions
`test_ac5_static_js_serves_real_file_without_auth`,
`test_ac5_static_css_serves_real_file_without_auth`,
`test_ac6_inventory_static_serves_allowlisted_file`,
`test_ac6_img_static_serves_allowlisted_file`, and
`test_ac7_ui_shared_serves_allowlisted_extension_when_authenticated` assert only a 200
status code, never the response body. A route that returns 200 with the wrong content (or
no content) still passes every one of these.

### 3. `tests/e2e/test_static_asset_security.py:42-53` — imprecise cache-control assertion
The AC5 header tests check for the substring `"3600"` in `Cache-Control`, which also
matches `max-age=36000` (10 hours, not the specced 1 hour). The CSS variant additionally
never checks for `stale-while-revalidate` at all, so a regression that drops SWR from the
CSS route's header would not be caught.

### 4. `tests/e2e/test_session_expiry.py:59-67` — generic-text check instead of template proof
`test_ac12_inactivity_timeout_renders_session_expired_page_for_html_request` accepts any
401 response containing the words "Session expired" — a generic Flask abort message with
that text would pass just as well as the real `session_expired.html` render. It doesn't
prove `session_expired.html` specifically rendered (e.g. checking for a marker unique to
that template).

## Verdict
**gamed** — 4 of ~9 new tests carry assertions weak enough that a real regression in the
behavior they're named for would not turn them red. Per the skill's blocking rule, this
does not clear the gate as-is.

---
## Addendum: patched and re-verified (orchestrator)

Tightened all four classes of assertion:
- `test_shell_redirects.py`: `Location` now checked against the exact expected origin+path
  (or a bare relative path), not an `endswith` suffix.
- `test_static_asset_security.py`: all five "serves the real file" tests now compare
  `response.body()` byte-for-byte against the real file read from disk, not just status
  200. `Cache-Control` checked with an exact string match against
  `"public, max-age=3600, stale-while-revalidate=60"`, replacing the substring checks
  (fixing both the `max-age=36000` false-pass and the missing-SWR gap on the CSS variant).
- `test_session_expiry.py`: the HTML-request test now asserts
  `<title>Session Expired</title>` and `id="countdown"` — markers unique to
  `session_expired.html` — instead of a bare "session"+"expired" substring check.

Re-ran the full 25-test suite live against `https://localhost:8005`: **25/25 pass**.
Re-ran the grader's exact 10 green-under-mutation cases against the patched assertions:
**all 10 now correctly fail** (0 green-under-mutation remaining). Full mutation set
re-verification (all 25 cases, including the 15 that were already correctly red) not
repeated — the 15 didn't change.

verdict (after patch): **clean** — 0 known gamed assertions remaining in this batch.
