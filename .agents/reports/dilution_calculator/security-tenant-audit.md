# SECURITY-TENANT-AUDIT: dilution_calculator

date: 2026-07-26
stage: security-tenant-audit (normally BLOCKING, per .agents/model-routing.json)
verdict: clean

## Fallback disclosure (per .agents/verification-chain.md §1)

This stage is routed to Codex (gpt-5.6-sol, exec mode) specifically for independent
adversarial reasoning distinct from whoever wrote the prior security-audit's scanner
pass. Codex is **not available in this environment** (`preflight.py` →
`decisions.grader_engine: "claude"`, `capabilities.codex: false`). This audit ran on
Claude (the same model family as the original security-audit author) as a fallback, not
the prescribed independent second reader. Flagging explicitly per the fallback-disclosure
rule rather than presenting this as equivalent to the normal Codex pass.

## Scope

Read every file under `app/features/dilution_calculator/` end to end (not grep-and-stop):
`dilution_calculator_bp.py`, `routes/api_routes.py`, `routes/page_routes.py`,
`services/dilution_service.py`, `frontend/templates/dilution_calculator/index.html`. Also
read `app/api/app_factory.py` in full, `app/api/middleware/tenant_context.py`,
`app/api/middleware/session_security.py`, `app/observability/middleware.py`, and
`app/core/security/permissions.py`. Independently ran the feature's test suite
(`uv run pytest tests/test_dilution_calculator.py -v`, `ENVIRONMENT` unset per CLAUDE.md
host-run guidance, test DB up on `localhost:8401`): **33/33 pass**, matching the prior
report's claim.

Noted but out of scope for this stage: an uncommitted working-tree diff on
`index.html` (adds `data-testid`/`role="alert"` attributes only, still exclusively
`x-text` bindings — no security implication) and two untracked e2e Playwright files
(`tests/e2e/test_dilution_calculator_flow.py`, `tests/e2e/test_debug_dilution.py`, the
latter a scratch/debug test) — cosmetic/test-infra additions, not part of the audited
code path, no auth/CSRF bypass patterns in them.

## 1. Control-flow read: is "no tenant data touched" actually true?

Traced both routes to their full call graph:

- `page_routes.py:dilution_calculator_index` → `render_template(...)`, no service call,
  no data access at all.
- `api_routes.py:solve` → `request.get_json()` → `solve_dilution(payload)` in
  `dilution_service.py` → `_validate_and_extract` (explicit allowlist over a fixed
  4-item frozenset) → `_check_dilution_direction` → `_solve_value` (closed-form division)
  → `_mass_fraction_for_abv` (bisection, pure math) → returns a plain dict → `jsonify`.

`grep -rn "org_id|current_org|db\.session|db_session|Repository|sqlalchemy" app/features/dilution_calculator/ --include="*.py"`
returns **nothing** — confirmed by reading, not just grepping: no import of any
SQLAlchemy model, repository, or `db_session`; no reference to `g.current_org_id`,
`g.org_id`, or any other `g`-scoped tenant state; no module-level mutable state that
could carry information between requests (the only module-level values are
`_RHO_ETHANOL_PURE`/`_RHO_WATER_PURE`, constants computed once at import time from a
fixed formula, not from request input). Every value in the response is a pure function
of that single request's own JSON body. The prior audit's "not applicable" claim for
tenant isolation is **verified true**, not rubber-stamped.

## 2. `@requires_auth` — real decorator, correct routes

- `app/core/security/permissions.py:44-52` — `requires_auth` checks
  `hasattr(g, "current_user") and g.current_user`, `abort(401)` otherwise. This is the
  same decorator used by every other authenticated route in the app (verified by reading
  the function itself, not assuming from the import line).
- `api_routes.py:18` — `@requires_auth` directly above `def solve():`, correct function.
- `page_routes.py:11` — `@requires_auth` directly above `def dilution_calculator_index():`,
  correct function.
- Both imports are `from app.core.security.permissions import requires_auth` — the real
  module, not a local shadow/lookalike.
- Independently confirmed effective (not just decorated) via the test suite:
  `test_ac6_api_endpoint_requires_auth`, `test_ac6_page_requires_auth` (no session →
  401/302), `test_ac6_page_renders_for_authenticated_user` (positive case, 200) — all
  pass.

## 3. Blueprint registration and middleware — no bypass

- `app_factory.py:101-106` registers the dilution_calculator blueprint at the same point
  in `create_app()` as `core_bp` (line 99) and the CRM blueprint (line 112), before the
  `setup_tenant_context`/`setup_session_security`/`setup_observability` calls at lines
  289-291. **This registration-order concern does not actually produce a bypass**: those
  three functions register `@app.before_request`/`@app.after_request`/
  `@app.teardown_request` hooks on the Flask `app` object, which Flask applies to every
  request against every route once the app starts serving — hook execution is governed
  by request time, not by whether a route was registered before or after the hook was
  attached. Read `tenant_context.py` and `session_security.py` in full to confirm neither
  keys its before_request logic off blueprint registration order or an allowlist that
  could be gamed by registration position.
- `PUBLIC_ENDPOINTS` in `tenant_context.py:23-32` (also reused by `session_security.py`)
  — `dilution_calculator_api.solve` and `dilution_calculator_pages.dilution_calculator_index`
  are **not** in that set, so both routes get the full tenant-context load and
  session-timeout check like any other authenticated route.
- `PUBLIC_UI_SHARED_FILES` (`app_factory.py:31`) is scoped to `/ui/shared/<filename>`
  static assets only (currently just `password-policy.js`) — unrelated surface, nothing
  from this feature is in it or could be, since the feature has no static-asset route.
- CSRF exemption loop (`app_factory.py:382-384`) exempts only `auth.*` endpoints and the
  two telemetry ingest endpoints by exact endpoint name — `dilution_calculator_api.solve`
  is not, and cannot accidentally be, matched by that check. Flask-WTF's global
  `CSRFProtect(app)` therefore validates every POST to
  `/api/dilution-calculator/solve`, and the frontend sends `X-CSRFToken` correctly
  (`index.html:153-154,184`).
- Nested blueprint structure (`dilution_calculator_bp.py`) registers `api_bp`/`page_bp`
  under a parent with no `url_prefix`, so the effective paths are exactly
  `/api/dilution-calculator/solve` and `/dilution-calculator` as coded — no accidental
  prefix stripping or collision with an existing route.

## 4. Adversarial pass beyond "stateless, therefore safe"

Went beyond the prior audit's checklist to ask whether "no data model" is a *complete*
argument, not just a technically-true one:

- **Cross-tenant inference/exfiltration**: not possible. The endpoint takes no ID, no
  reference to any stored entity, and touches no shared mutable state — every response is
  a pure function of that request's own four numbers. There is no lookup path by which an
  Org A user could cause the server to read or reflect anything about Org B, because
  nothing server-side is keyed by org at all in this code path. This is the correct
  no-op case, not an unexamined absence of evidence.
- **Shared/global state as a side channel**: checked for `lru_cache`, module-level dicts,
  or any other cross-request memoization that could let timing or cached output leak
  information between callers — none exists. `_RHO_ETHANOL_PURE`/`_RHO_WATER_PURE` are
  the only module-level values and are input-independent constants.
- **Timing side channel**: the bisection (`_mass_fraction_for_abv`) runs a fixed 60
  iterations regardless of input value or magnitude (confirmed by reading
  `_BISECTION_ITERATIONS = 60` and the unconditional `for _ in range(...)` loop) — no
  data-dependent timing variance to exploit, and moot anyway since there is no
  cross-tenant data to time against.
- **Error-message leakage**: every `DilutionValidationError` message is a fixed template
  referencing only field *names* the caller itself supplied (e.g. `"'final_abv' must be
  between 0 and 100"`), never a value, never internal state, never another request's
  data. Checked there is no bare `except Exception` in the route that could let a raw
  exception (with a traceback or internal path) escape to the client — `api_routes.py`
  only catches `DilutionValidationError`; anything else would fall through to the app's
  standard (pre-existing, app-wide, not introduced by this feature) unhandled-exception
  path.
- **The observability log line** (`api_routes.py:29`,
  `logger.info("dilution_calculator.solved", solve_for=result["solved_field"])`):
  deliberately logs only *which field* was solved for, never the actual ABV/volume
  values — a good call given those numbers could reflect a tenant's real recipe/batch
  data (e.g. their production target ABV), even though logging them wouldn't be a
  cross-tenant leak per se (see next point). Confirmed by reading
  `app/observability/middleware.py:22-46` and `logging_config.py` that `org_id`/`user_id`
  are bound into `structlog.contextvars` per-request from `g.org_id`/`g.user_id` (set by
  `tenant_context.py`, which *does* run before this route despite the feature itself
  never touching org state) and explicitly cleared in `teardown_request`
  (`middleware.py:72-75) — so this log line is correctly attributed to the calling
  request's own org and can't bleed into or be mistaken for another tenant's log stream.
  `record_http_request` (`app/observability/metrics.py:60`) does not carry an `org_id`
  label either, so no cross-tenant cardinality/enumeration concern at the metrics layer.
- **CSP/XSS on the reflected calculation values**: `index.html` binds every dynamic
  value (`result.solved_field`, `result.solved_value`, `result.water_to_add_ml`,
  `result.disclaimer`, `error`) via Alpine `x-text` (`textContent`, not `innerHTML`) —
  confirmed by reading the whole template, including the uncommitted working-tree diff,
  which only adds `data-testid`/`role` attributes and doesn't touch any binding.

No subtler concern survived scrutiny. The feature genuinely has no tenant-scoped attack
surface to leak across, and the one place adjacent tenant state does flow through this
code path (structured-log context) is scoped and cleared correctly per request.

## Findings

None. Zero tenant-isolation or related findings — the prior audit's "not applicable"
verdict for this feature is confirmed correct by independent read-through and adversarial
reasoning, not merely re-asserted.

## Verdict rationale

This stage is BLOCKING by design (unlike build-review's advisory status), so a real
finding here would gate the chain regardless of how minor. No such finding exists for
this feature: `@requires_auth` is present and effective on both routes, blueprint
registration and middleware ordering do not create a bypass, no CSRF/PUBLIC_ENDPOINTS
exemption applies, and the control-flow read confirms zero tenant-scoped state anywhere
in the blueprint. Given the fallback disclosure above (Claude, not Codex, ran this pass),
this should still be read as a completed, blocking-stage clean verdict — not skipped, not
downgraded — with the caveat that the prescribed independent-model second-reader property
wasn't available in this environment.
