# SECURITY: dilution_calculator
date: 2026-08-21
role: chain stage (read-only grader; invoked from review-feature) — no patching performed
verdict: clean
scanned: semgrep(0 findings), gitleaks(0 findings in-scope), uv-audit(0 vulnerabilities)
manual_checklist: 7/7 completed
not_verified: live_server suites (no app server listening per preflight — skip is honest, not silent)

## Scope
`app/features/dilution_calculator/`: `dilution_calculator_bp.py`, `routes/api_routes.py`,
`routes/page_routes.py`, `services/dilution_service.py`,
`frontend/templates/dilution_calculator/index.html`. Cross-checked registration in
`app/api/app_factory.py:124-128` and the auth/CSRF wiring it inherits app-wide
(`app/core/security/permissions.py`, `app/api/app_factory.py:412-425`).

## Scanner pass
- **semgrep** (`p/python`, `p/flask`, `p/owasp-top-ten`, `.semgrep/`) against the 5 tracked
  files in this slice: 175 rules run, **0 findings**.
- **gitleaks**: ran `detect --source app/features/dilution_calculator/`. Note: `--source`
  sets the git working dir, not a path filter — it still walked all 1079 commits, reporting
  65 pre-existing leaks repo-wide (`.agents/reports/auth/gitleaks.json`,
  `.agents/reports/org/gitleaks.json`, `app.py.bak`, `config/prod.ini`, etc. — none of them
  under `app/features/dilution_calculator/`, confirmed by listing every `File` key in the
  JSON output). **0 leaks touch this slice's files.** Pre-existing repo findings (including
  the known `app/tls/app_cert.key` accepted-risk from the skill's own history) are out of
  scope for this audit and already tracked elsewhere.
- **uv audit** (`--frozen`, preview json output): 84 packages audited, **0 vulnerabilities**.
  This feature adds no new dependency — `dilution_service.py` imports only stdlib `math`.

## Manual checklist (7/7)

1. **Auth on every route** — both routes carry `@requires_auth`
   (`routes/api_routes.py:18`, `routes/page_routes.py:11`), the same decorator used
   app-wide (`app/core/security/permissions.py:55`), which checks `g.current_user` and
   `abort(401)` if absent. No bare route found.
2. **Tenant isolation** — spec claims this slice is tenant-agnostic (no `org_id`, no
   models, no persistence). Verified rather than trusted: `grep -rn
   "org_id|current_org_id|Model(|db.session|requires_org_scope"
   app/features/dilution_calculator/` returns nothing. The service module
   (`dilution_service.py`) is pure computation over the request payload; no import of
   any ORM model or `app.core.db`. Claim holds — not flagging absent org-scoping per the
   task's own instruction, since there is genuinely no tenant-scoped table or `org_id`
   anywhere in this code path to scope.
3. **Mass assignment** — request JSON is walked field-by-field against an explicit
   allowlist (`FIELD_NAMES` in `dilution_service.py:22`); no `Model(**request.json)` or
   `setattr` loop, and there is no model to mass-assign into in the first place.
4. **Injection** — no SQL (no DB access at all), no `subprocess`, no file paths built from
   user input. Template (`index.html`) uses Alpine `x-text` exclusively for all
   server-derived values (`result.solved_field`, `.disclaimer`, echoed fields, error
   message) — no `x-html`, no Jinja `| safe` / `Markup()` on request-derived data anywhere
   in the template.
5. **SSRF / uploads** — N/A, no URLs or file uploads accepted by this slice.
6. **Secrets and config** — no secrets in these files (confirmed by gitleaks scope above).
   `SECRET_KEY`/debug config is app-wide, not slice-specific; `debug=false` in
   `app/config/prod.ini:3`.
7. **CSRF and CORS** — the mutating route (`POST /api/dilution-calculator/solve`) is
   *not* on the app's CSRF-exemption list (`app/api/app_factory.py:421-425` only exempts
   `auth.*` and the two telemetry ingest endpoints), so global `CSRFProtect(app)` applies
   to it. Frontend sends `X-CSRFToken` (`index.html:159-161,190`), matching
   `WTF_CSRF_HEADERS` config. No CORS wildcard introduced by this slice.

## Focused checks (per task brief)

- **Input validation / numeric parsing robustness** (`_validate_and_extract`,
  `dilution_service.py:75-100`): every given field is type-checked
  (`isinstance(value, (int, float)) and not isinstance(value, bool)`, `bool` explicitly
  excluded despite being an `int` subclass), finiteness-checked (`math.isfinite`, so
  JSON's non-standard `NaN`/`Infinity`/`-Infinity` literals are rejected, not silently
  accepted), and range-checked (ABV `0-100`, volumes `> 0`) before any arithmetic runs.
  Verified by direct unit exercise of `solve_dilution`: booleans, lists, `NaN`, `Infinity`
  all correctly rejected with a 400-mapped `DilutionValidationError`; none raised an
  unhandled exception.
- **Injection via JSON payload**: payload values are only ever used as Python floats in
  arithmetic (`_solve_value`, `_mixture_density`) — never interpolated into a string,
  query, template, or shell command. No injection surface exists regardless of value.
- **DoS via the bisection loop / pathological inputs**: `_BISECTION_ITERATIONS = 60` is a
  fixed constant independent of input (`dilution_service.py:24`) — the loop always runs
  exactly 60 or 0 iterations (0 at the `abv_pct` boundaries), so there is no
  input-controlled iteration count to exploit. Verified with extreme-but-valid floats
  (`starting_volume_ml=1e300`, `starting_abv=1e-300`) and boundary-abv values — solve
  completes in microseconds in every case; values that would overflow to `inf` are caught
  by the post-solve `math.isfinite(solved_value)` check (`dilution_service.py:138-139`)
  and rejected with 400, not left to propagate. Route-level request-body size is bounded
  by the app-wide `MAX_CONTENT_LENGTH` set in `app/api/app_factory.py:56`, which applies
  before this endpoint's handler runs — same protection every other route gets, not
  something this slice opts out of.
- **Auth enforcement on both routes**: confirmed under checklist item 1 above; also
  confirmed the decorator is the real app-wide one (not a local reimplementation) by
  import (`from app.core.security.permissions import requires_auth` in both route files).
- **Error message information leakage**: `DilutionValidationError` messages are static,
  templated strings describing which field/rule failed (e.g. `"'final_abv' must be
  between 0 and 100"`) — no stack traces, file paths, query text, or internal state is
  ever included, and the exception class's own docstring asserts this design intent
  (`dilution_service.py:33-34`). The route only catches this one exception type
  (`api_routes.py:24-28`); any other exception would fall through to the app's existing
  generic error handler (app-wide, `debug=false` in prod per `app/config/prod.ini:3`,
  out of scope to re-audit here since it isn't slice-specific code). In practice no such
  fallthrough was observed — every malformed/pathological input tried above resolved to
  either a clean result or a `DilutionValidationError`.
- **AC7 statelessness/determinism** (bears on DoS/replay concerns): confirmed no model,
  repository, or table is touched (checklist item 2) and the bisection has a fixed
  iteration count (above) — identical requests are computed fresh and deterministically,
  nothing to exhaust via repeated identical calls beyond ordinary request-rate concerns
  already handled by the app's existing rate limiting on auth-adjacent routes (not
  applicable here — this route needs no elevated protection beyond standard auth).

## Findings
None.

## Attempted but clean
- Grepped this slice for `org_id`/`current_org_id`/ORM model imports/`db.session` — none
  found, confirming the spec's "tenant-agnostic" claim rather than assuming it.
- Grepped for CSRF-exemption of the solve endpoint — not exempt, protection active.
- Fuzzed `solve_dilution` directly with booleans, lists, `NaN`, `Infinity`, and extreme
  magnitude floats (`1e300`/`1e-300`) — all handled without an unhandled exception, either
  rejected with a clean 400-mapped error or returning a finite, in-range result.
- Checked template for `x-html`/`| safe`/`Markup()` usage — none; all dynamic output goes
  through Alpine's auto-escaping `x-text`.
- Checked whether `--source`-scoped gitleaks actually filtered by path (it doesn't) and
  manually confirmed none of its 65 hits fall under this slice before ruling the layer
  clean rather than trusting the raw count.

