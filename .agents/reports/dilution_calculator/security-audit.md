# SECURITY: dilution_calculator
date: 2026-07-26
verdict: clean
scanned: semgrep(0 findings), gitleaks(NOT RUN — binary absent, see below), uv-audit(0 vulnerabilities, 82 packages)
manual_checklist: 7/7 completed
verification_mode: subagents (preflight decision, honored)
grader_engine: claude — **no Codex available in this environment**, so the adversarial
  second-reader step normally provided by Codex-in-Herdr did not run. This audit was
  self-reviewed only; flagging per the fallback-disclosure rule in
  `.agents/verification-chain.md`.

## Scope
`git diff origin/main...HEAD` in the worktree at
`/home/johnny/workflow-engine-dilution_calculator` (branch `feat/dilution_calculator`,
2 commits ahead of `origin/main`), plus the two integration points it touches outside its
own blueprint:
- `app/features/dilution_calculator/**` (blueprint, routes, service, template)
- `app/api/app_factory.py` (blueprint registration)
- `app/ui/templates/shared/sidebar-v2.html` (nav link)
- `tests/test_dilution_calculator.py`

13 files, 1699 insertions, no deletions. No model/migration/repository files — matches
the spec's `tenant_scoped: no`, `changes: none` under Data model.

## Tool availability (preflight)
`python3 scripts/preflight.py --json` → `tools`: 4/5 available — **`gitleaks` missing**.
Semgrep, uv, alembic, playwright present. Per the skill's rule ("say which layer didn't
run rather than reporting a clean scan"): **the secrets-scanning layer did not run in
this audit.** This is a known environment gap (not specific to this feature), and this
report should not be read as having cleared secrets scanning — only semgrep and uv audit
ran as the deterministic layer. No secrets were spotted by eye in the diff (no keys,
tokens, connection strings, or credentials in any of the 13 changed files), but that is
not a substitute for gitleaks.

## 1. Scanner pass
```
semgrep --config p/python --config p/flask --config p/owasp-top-ten --config .semgrep/ \
  app/features/dilution_calculator/ app/api/app_factory.py app/ui/templates/shared/sidebar-v2.html
→ 171 rules run on 7 files, 0 findings

uv audit --frozen --output-format json --preview-features audit-command,json-output
→ 82 packages audited, 0 vulnerabilities, 0 adverse statuses
```
Both scanner outputs saved: `.agents/reports/dilution_calculator/semgrep.json`,
`.agents/reports/dilution_calculator/uv-audit.json`.

`scripts/finding_history.py decide` checked for both `missing-auth` and `xss` classes
against this area — both returned `new` (no prior verdict on file), consistent with zero
findings to triage.

## 2. Manual pass
1. **Auth on every route.** Both routes (`POST /api/dilution-calculator/solve`,
   `GET /dilution-calculator`) carry `@requires_auth`
   (`app/features/dilution_calculator/routes/api_routes.py:18`,
   `app/features/dilution_calculator/routes/page_routes.py:11`), which checks
   `g.current_user` and `abort(401)` if absent
   (`app/core/security/permissions.py:42-52`). Verified *effective*, not just decorated:
   `tests/test_dilution_calculator.py::TestDilutionCalculatorAuth` hits both routes with
   no session cookie via a fresh `create_app()` test client and asserts
   `401`/`302` — ran these tests for real (`uv run pytest
   tests/test_dilution_calculator.py -v`, all 33 pass, including the three auth tests).
   `test_ac6_page_renders_for_authenticated_user` confirms the positive case (200,
   authenticated) so the negative-case pass isn't just because the whole app is broken.
2. **Tenant isolation.** Not applicable — verified. The spec (`tenant_scoped: no`) and
   the code agree: `dilution_service.py` takes a plain dict, does pure arithmetic
   (closed-form division + fixed-iteration bisection), and returns a dict. No import of
   any model, repository, or `db.session` anywhere in
   `app/features/dilution_calculator/`. `grep -rn "org_id\|db.session\|Model\b"
   app/features/dilution_calculator/` returns nothing. `test_ac7_endpoint_writes_no_rows`
   asserts the DB row count is unchanged before/after a solve call. There is no tenant
   data surface here for org-A/org-B leakage to occur against — confirmed, not assumed.
3. **Mass assignment.** N/A — no ORM model is populated from request JSON.
   `_validate_and_extract` in `dilution_service.py:75-100` is an explicit allowlist:
   it iterates exactly `FIELD_NAMES - {solve_for}` (a fixed frozenset of 4 names), rejects
   anything not present/finite/in-range, and builds a fresh `given` dict field-by-field —
   never `dict(**payload)` or a loop over arbitrary payload keys. Extra/unknown JSON keys
   are silently ignored (never assigned anywhere), which is correct for this shape.
4. **Injection.** No SQL (no DB access at all). No `subprocess`. No file paths built
   from user input. Template (`index.html`) uses Alpine `x-text` exclusively for every
   dynamic binding (`result.solved_field`, `result.solved_value`, `result.water_to_add_ml`,
   `result.disclaimer`, `error`, field labels) — never `x-html` or `{{ ... | safe }}`.
   `x-text` sets `textContent`, not `innerHTML`, so a value can't execute as markup even
   if the API returned attacker-influenced content back to the same authenticated user.
   Grepped the whole diff for `| safe`, `Markup(`, `x-html`, `innerHTML`, `eval(`,
   `document.write` — none present.
5. **SSRF / uploads.** N/A — no outbound HTTP calls, no file uploads; feature is pure
   computation behind the existing auth boundary. Spec's "External surfaces: none" holds.
6. **Secrets and config.** No secrets in the diff (by eye — gitleaks did not run, see
   above). No new config/env vars introduced. `SECRET_KEY`/cookie flags/debug settings
   are unmodified by this feature.
7. **CSRF and CORS.** `POST /api/dilution-calculator/solve` is state-*reading*, not
   state-*changing* (writes no rows — confirmed under #2), so CSRF risk here is inherently
   low (worst case, cross-site trigger of a compute-only call). Even so, it is **not**
   exempted from Flask-WTF's global `CSRFProtect(app)`
   (`app/api/app_factory.py:378`) — the exemption loop only exempts
   `auth.*` endpoints and the two telemetry ingest endpoints
   (`app/api/app_factory.py:382-384`); `dilution_calculator_api.solve` is not in that set,
   so Flask-WTF validates the token on every POST. The frontend sends it correctly
   (`X-CSRFToken` header read from the `<meta name="csrf-token">` tag, `index.html:153-154,184`),
   matching the app's established SPA pattern. No CORS wildcard or credential-carrying
   `Access-Control-Allow-Origin` introduced by this feature.

### Spot-check: the two build-review fixes
Per the task, checked that both fixes documented in `dilution_service.py` actually hold,
by reading the code and by running (not just reading) their regression tests:
- **Non-string `solve_for` → 500.** `_validate_and_extract` guards with
  `isinstance(solve_for, str) and solve_for not in FIELD_NAMES` (line 80) before the
  frozenset membership check, so a list/dict/int `solve_for` is rejected as a normal 400,
  not an unguarded membership-test crash. `test_ac4_rejects_non_string_solve_for` passes
  a list and asserts `DilutionValidationError` — ran it, passes.
- **Overflow-to-Infinity slipping past validation.** `solve_dilution` explicitly checks
  `math.isfinite(solved_value)` right after the division (line 138), before the
  range/positivity checks that `inf` would otherwise pass (`inf > 0` is `True` in Python,
  which is exactly the gap being closed). `test_ac4_rejects_overflow_to_infinite_solved_value`
  feeds `starting_volume_ml=1.5e308, final_abv=1e-300` (finite inputs, infinite quotient)
  and asserts the rejection — ran it, passes.
- Additional spot-checks run live against the service function (not just reading code):
  `starting_abv=True` (bool, an `int` subclass in Python) is correctly rejected — the
  `_is_finite_number` guard explicitly excludes `bool` (`dilution_service.py:38`);
  a JSON string `"NaN"` in a numeric field is rejected (fails `isinstance(value,
  (int, float))`, not silently coerced); a legitimately huge-but-finite input
  (`starting_volume_ml=1e15`) resolves in ~25µs with no timeout/DoS risk, since the
  bisection loop is a fixed 60 iterations regardless of input magnitude (AC7's
  determinism requirement doubles as a DoS bound — no unbounded loop exists anywhere in
  this file).

### CSP note (not a finding — existing app-wide posture)
`index.html` has an inline `<script>` block. The app's CSP already sets
`script-src 'self' 'unsafe-inline' 'unsafe-eval' ...` app-wide
(`app/api/app_factory.py:345`), and at least one other feature template
(`app/features/crm/frontend/templates/crm/analytics.html`) follows the same inline-script
pattern — this feature doesn't change or weaken CSP, it just uses the existing convention.
Flagging only so it's visible; not scoped to fix as part of this audit (would be an
app-wide CSP tightening, out of scope for a single-feature diff).

## Attempted but clean
- Grepped the full diff for `org_id`, `db.session`, `Model(`, `setattr(` — none found;
  confirms no tenant-data or mass-assignment surface exists to probe further.
- Grepped for `| safe`, `Markup(`, `x-html`, `innerHTML`, `eval(`, `document.write`,
  `shell=True` — none found anywhere in the diff.
- Ran `uv run pytest tests/test_dilution_calculator.py -v` for real (not just read) —
  33/33 pass, `ENVIRONMENT` unset per CLAUDE.md's host-run guidance, test DB up on
  `localhost:8401`.
- Probed the service function directly (bool-as-int, string-"NaN", 1e15-scale volume)
  beyond the checked-in test cases — all handled correctly, no crash, no bypass.
- Checked `app_factory.py`'s CSRF-exemption list line by line to confirm this feature's
  API endpoint is not in it.

## Findings
None. No `fix`, `false-positive`, or `accepted-risk` bucketed items this run — every
scanner and manual check came back clean, and both previously-identified build-review
gaps (non-string `solve_for`, overflow-to-Infinity) are verified fixed with passing
regression tests. No new semgrep rule was authored (section 3 of the skill), because
there is no new finding to encode.

## not_verified
- **Secrets scanning (gitleaks).** Binary absent from this environment
  (`preflight.py` reports `tools: 4/5 available — missing: gitleaks`). Manual eyeball of
  the diff found nothing secret-shaped, but this is not equivalent to a gitleaks run and
  should not be read as one. Recommend running gitleaks against this branch once the
  binary is available, or on the next scheduled sweep that has it.
- **Codex adversarial second-reader.** `grader_engine=claude`, no Codex available in this
  environment per the preflight decision handed down — this audit had no hostile second
  reader distinct from the author. Per the fallback-disclosure rule in
  `.agents/verification-chain.md`, noting this explicitly rather than silently presenting
  a single-reviewer audit as equivalent to the full adversarial chain.

## Remediation
Not applicable — zero findings to route (section 5 of the skill only applies to `fix`-
bucket items). Nothing was patched because nothing needed patching.
