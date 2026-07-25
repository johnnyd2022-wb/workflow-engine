# build-review: dilution_calculator

**Engine note (fallback disclosure, per .agents/verification-chain.md §1):** build-review is
routed to Codex (gpt-5.6-sol) for independent fresh eyes. Codex was unavailable in this
environment (preflight `grader_engine=claude` fallback), so this pass ran on Claude
(Sonnet 5) instead — the review happened, but not with an independent engine. Flagging
per the fallback-disclosure rule. Read-only pass, no code was or could be edited.

**Scope:** `git diff main...HEAD` in the worktree at
`/home/johnny/workflow-engine-dilution_calculator`, branch `feat/dilution_calculator`,
one commit (`478c684`) ahead of `origin/main`. Verified the existing test claim first:
`env -u ENVIRONMENT uv run pytest tests/test_dilution_calculator.py -v` → **31 passed**,
confirming the PR's own claim before hunting for what it doesn't cover.

## Findings

### 1. `solve_for` as a non-hashable JSON value crashes the endpoint with an unhandled 500, not the AC4-mandated 400

**File:** `app/features/dilution_calculator/services/dilution_service.py:80`

```python
solve_for = payload.get("solve_for")
if solve_for not in FIELD_NAMES:
```

`FIELD_NAMES` is a `frozenset`. `payload.get("solve_for")` returns whatever JSON value the
caller sent, unvalidated in type. If the caller sends `"solve_for": ["final_volume_ml"]`
or `"solve_for": {"a": 1}` (both trivially valid JSON, no special client needed — this is
a raw `POST` body, not something the Alpine.js frontend prevents since server-side
validation is the real trust boundary), `list not in frozenset(...)` raises
`TypeError: unhashable type: 'list'` instead of returning cleanly. `api_routes.py`'s
`solve()` only catches `DilutionValidationError`:

```python
try:
    result = solve_dilution(payload)
except DilutionValidationError as exc:
    return jsonify({"error": str(exc)}), 400
```

so the `TypeError` propagates all the way to Flask's default handler.

**Verified end-to-end** (full app, real login, real HTTP request via `test_client()`,
`TESTING=False` to mimic prod-like error handling — not just the service function in
isolation):

```
POST /api/dilution-calculator/solve
{"solve_for": ["final_volume_ml"], "starting_abv": 40, "starting_volume_ml": 1000, "final_abv": 20}

→ HTTP 500, generic Flask error page ("Internal Server Error"), plus a second-order bug:
  the app's own structlog exception formatter (structlog/dev.py) itself throws
  (`TypeError: can only concatenate str (not "list") to str`) while trying to render the
  traceback, because `solve_for` (the list) gets interpolated into a log line — so the
  incident isn't even cleanly logged.
```

This directly violates AC4's contract ("`solve_for` is missing or not one of the four
valid field names" → 400 with a clear message) for one shape of "not one of the four valid
field names" that the spec's authors evidently didn't consider: not just a wrong string,
but a wrong *type*. Fix is a one-line type guard before the membership test, e.g.
`if not isinstance(solve_for, str) or solve_for not in FIELD_NAMES:`.

**Severity:** Medium — not a security bypass (auth still required, no data touched,
no tenant isolation issue), but it's a clean, single-request crash reachable by any
authenticated user, breaks the "always 400 on bad input" contract this feature is
supposed to have, and pollutes logs with a secondary formatting crash. Not covered by
any of the 31 tests.

### 2. Solved values / `water_to_add_ml` can overflow to `Infinity`, which Flask happily serializes as invalid JSON — for volume solve targets only

**File:** `app/features/dilution_calculator/services/dilution_service.py:138-141`

```python
if solve_for in ABV_FIELDS and not (0.0 <= solved_value <= 100.0):
    raise DilutionValidationError(...)
if solve_for in VOLUME_FIELDS and not (solved_value > 0.0):
    raise DilutionValidationError(...)
```

Volume inputs are validated as `> 0` with **no upper bound**. If a caller submits a large
enough `starting_volume_ml` against a small `final_abv` (both individually valid: ABV in
`[0,100]`, volume `> 0`), the closed-form division overflows a Python/IEEE-754 `float` to
`inf`. For `solve_for in VOLUME_FIELDS`, the post-solve guard is `solved_value > 0.0` —
and `inf > 0.0` is `True` in Python, so **the overflow silently passes validation**. (The
`ABV_FIELDS` branch is accidentally safe: `0.0 <= inf <= 100.0` is `False`, so an ABV
solve that overflows *is* correctly rejected — this asymmetry is exactly the kind of gap
the AC5-divisor-history pattern predicts a third instance of, just one class up from
literal division-by-zero: unguarded overflow instead of unguarded zero-divisor.)

**Verified end-to-end**, real HTTP call through the full app:

```
POST /api/dilution-calculator/solve
{"solve_for": "final_volume_ml", "starting_abv": 40, "starting_volume_ml": 1.5e308, "final_abv": 0.001}

→ HTTP 200, body (raw bytes, confirmed via resp.data):
  {"disclaimer":"...", "final_abv":0.001, "final_volume_ml":Infinity,
   "solved_field":"final_volume_ml", "solved_value":Infinity, "starting_abv":40.0,
   "starting_volume_ml":1.5e+308, "water_to_add_ml":Infinity, "water_to_add_naive_ml":...}
```

`Infinity` is not a valid JSON token per RFC 8259 — Python's stdlib `json` (which Flask's
`jsonify` uses under `allow_nan=True`, confirmed by direct test:
`jsonify({"x": float('inf')})` → `'{"x":Infinity}'`) emits it anyway, but a standards-
compliant JSON parser does not accept it. Concretely, this feature's *own* frontend
(`index.html`'s `const data = await res.json();`) is exactly such a parser — browsers'
`Response.json()` throws a `SyntaxError` on a literal `Infinity` token, which the
frontend's `try/catch` swallows into a misleading `"Network error — please try again"`
message (there was no network error; the server returned 200 with a body the client
can't parse).

This is reachable with only moderately extreme (not maliciously crafted-to-look-benign)
inputs — no negative numbers, no NaN, no zero divisor, just "volume near float64 max" —
and produces a response that is a 200 with a semantically nonsensical answer
(no real dilution needs `Infinity` mL of water) instead of a 400.

**Severity:** Medium — same "should have been a 400" class as finding 1, discoverable by
fuzzing the two numeric ranges the spec leaves unbounded (`starting_volume_ml`,
`final_volume_ml` have no stated upper limit — spec's Out-of-scope section doesn't
mention one either). Fix: after `_solve_value`, add an explicit
`math.isfinite(solved_value)` check for the `VOLUME_FIELDS` branch (or better, a shared
`isfinite` check before either branch, so the fix isn't ABV-specific by accident).

## What I checked and found solid

- **AC5 divisor-safety proof, all four `solve_for` directions** — re-derived from first
  principles independently of the spec's own proof, then confirmed by direct execution
  against `dilution_service.py`. All four divisors (`final_abv`, `final_volume_ml`,
  `starting_abv`, `starting_volume_ml`) are provably non-zero at the point of division:
  two are guaranteed by the unconditional `volume > 0` validation, one has an explicit
  `== 0.0` guard (including the `-0.0` case, since `-0.0 == 0.0` is `True` in Python), and
  the fourth (`starting_abv` when solving `starting_volume_ml`) is caught upstream because
  `starting_abv == 0` makes the `final_abv >= starting_abv` pair-check unconditionally
  true (every valid `final_abv` is `>= 0`). No third division-by-zero hole found — the
  two prior spec-critic-caught holes appear genuinely closed. (What I *did* find is
  finding 2 above, which is adjacent but distinct: overflow, not exact zero.)
- **Bisection solver correctness near `w=0`/`w=1`** — both boundaries are short-circuited
  to exact analytic values (`abv_pct <= 0.0 → 0.0`, `abv_pct >= 100.0 → 1.0`) before the
  loop runs, so the solver never actually executes at the boundary and there's no
  0/0 or asymptote risk inside `_abv_from_mass_fraction`. Fixed 60-iteration bisection is
  deterministic (AC7) and vastly exceeds float64 precision (2⁻⁶⁰ ≪ machine epsilon).
- **CSRF / auth** — `@requires_auth` correctly applied to both the API and page routes.
  `CSRFProtect(app)` in `app_factory.py` is applied globally with no new exemption added
  for this blueprint (the exemption list only covers `auth.*` and the two telemetry
  routes), so `POST /api/dilution-calculator/solve` is CSRF-protected exactly like every
  other mutating-looking endpoint in the app — consistent with existing convention, no
  regression.
- **Frontend injection surface** — `index.html`'s Alpine component uses only `x-text`
  bindings (auto-escaped) for every piece of server-derived or user-derived data; no
  `x-html`, no `innerHTML`, no template-string HTML construction. No XSS surface found.
- **Path traversal** — `page_bp`'s `template_folder="../frontend/templates"` is a fixed,
  code-authored relative path resolved once at blueprint-creation time, not
  request-influenced; `render_template("dilution_calculator/index.html", ...)` uses a
  hardcoded template name. No user input reaches template/file resolution anywhere in
  this feature.
- **Frontend payload-building vs. API contract** — `submit()` correctly omits the
  `solve_for`-named field from the outgoing JSON (the `for (const opt of this.fieldOptions)
  { if (opt.key === this.solveFor) continue; ... }` loop), coerces the other three via
  `Number(raw)` with an `Number.isFinite` guard before sending, and matches the four field
  names exactly. `setSolveFor()` clears both `result` and `error` on every solve-target
  change, so there's no stale-result-shown-after-switching-solve_for bug.
- **`app_factory.py` blueprint registration** — inserted between `core_bp` and the
  feature-flagged CRM registration, registered unconditionally (matches the spec's own
  stated rationale: no data model, no rollout risk, no flag needed), and doesn't reorder
  or otherwise touch the existing `auth_bp`/`org_bp`/`core_bp`/CRM registration lines.
  Minimal diff (+7 lines) doing exactly one thing.
- **`sidebar-v2.html` nav link** — added as a plain unconditional `<li>` (correctly *not*
  wrapped in the `{% if crm_enabled %}` guard that CRM uses, since this feature has no
  flag), positioned between Core and the commented-out Compliance entry, using the same
  `active_page` pattern as every other nav item. Doesn't touch or reorder any existing
  `<li>`. `active_page='dilution_calculator'` is correctly passed from `page_routes.py`'s
  `render_template(...)` call and matches the `{% if active_page == 'dilution_calculator' %}`
  check in the new `<li>`.
- **Simplification / dead code** — nothing obviously over-engineered found. The module is
  tight: one explicit divisor guard (justified in a comment referencing the prior
  spec-critic finding it fixes), no unused branches, no speculative abstraction. The
  `_RHO_ETHANOL_PURE`/`_RHO_WATER_PURE` module-level constants (computed once from
  `_mixture_density`) are a reasonable, self-documenting way to avoid recomputing them
  per-request without introducing caching machinery.
- **AC9 (no server-side rounding) / AC7 (determinism, no DB writes)** — spot-checked
  independently (exact-value assertion, repeated-call byte-identity, row-count-before/after
  the app's own test DB) and consistent with what the 31 existing tests already assert;
  nothing to add here.

## Verdict rationale

Both findings are input-validation gaps at the boundary the spec explicitly cares about
(AC4's "reject with 400" contract) rather than errors in the core algebra/physics, which
held up under adversarial pressure. Both are cheap, well-scoped fixes (a type guard on
`solve_for`, an `isfinite` check on the solved value) that don't touch the exact-identity
math or the density model the spec spent three spec-critic rounds getting right. Routing
to the orchestrator to patch and add regression tests for both.

VERDICT: findings-open
