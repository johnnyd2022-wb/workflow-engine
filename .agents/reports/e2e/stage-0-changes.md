# Stage 0 — every change made, for review

Date: 2026-07-17. Spec: `.agents/specs/playwright-e2e.md`.

Verification after the last change:

| Check | Result |
|---|---|
| `uv run pytest tests/e2e -q` | **9 passed** (3/3 identical runs, no flake) |
| `uv run pytest tests/ -q --ignore=tests/e2e` | **252 passed, 30 skipped** — matches CLAUDE.md's documented baseline exactly |
| `uv run ruff check app/ tests/e2e/` | All checks passed |
| `uv run semgrep scan --config=auto` on changed files | **0 findings (was 1 blocking)** |
| DB residue after a full E2E run | 0 rows |

---

## A. Production code changes (4)

### A1. `app/api/app_factory.py` — public-asset allowlist for `/ui/shared` (**auth change**)

**Was:** the route carried `@requires_auth`, so every file under `/ui/shared` required a
session.

**Now:** module constant `PUBLIC_UI_SHARED_FILES = frozenset({"password-policy.js"})`.
The decorator is gone; auth is enforced *inside* the view for anything not on the
allowlist, with the identical check the decorator did (`g.current_user` → 401).

**Why:** the logged-out landing page loads `password-policy.js`. Gated, it 302'd to `/`
and returned `text/html`, so the browser refused to execute it. `landing.html:1506` guards
with `if (window.PasswordPolicy)`, so it failed **silently** — signup has never shown live
password warnings. Its endpoint `/auth/password-policy-check` is already public, because
signup must call it pre-session; the script being gated was the inconsistency.

**Why not `@requires_auth` + a second route:** two rules on one path is ambiguous
resolution. Enforcing inside the view is explicit and keeps one code path.

**Blast radius:** only `password-policy.js` becomes anonymous. Pinned by
`test_gated_shared_assets_still_require_auth`, which asserts `account-info.js`,
`workflow-engine-settings.js` and `sidebar.js` still refuse anonymous access. **Review
this one first** — it is the only change that alters auth posture.

### A2. `app/app.py` — `from initialize import db_conn` → `from app.initialize import db_conn`

Bare import only resolved when run as `python app/app.py` (script dir on `sys.path`), so
importing the app as a package raised `ModuleNotFoundError`. The file's other imports
(`app.api.app_factory`, `app.observability`, …) were already `app.`-prefixed; this was the
lone outlier and the only bare import in the codebase. Works both ways — `app.py:6-8` puts
the repo root on `sys.path` when run directly.

### A3. `app/app.py` — index route no longer uses `render_template_string`

**Was:** read `landing.html` off disk on every request and passed it through
`render_template_string`.

**Now:** `send_from_directory`, matching the sibling `/landing-diagram` route directly
below it.

**Why:** `landing.html` contains **zero** Jinja syntax (0 matches for `{%` / `{{`), so the
template pass bought nothing while costing a disk read plus a recompile on every hit of
the app's most-trafficked public page, and it was semgrep's one blocking finding
(`python.flask.security.audit.render-template-string`, SSTI). `send_from_directory` also
adds conditional-GET/etag handling. This was **pre-existing**, not introduced by this work,
but it sat in a file I was already changing and it was the only thing standing between the
repo and a clean scan.

### A4. `app/ui/templates/landing.html` — modal resets no longer wipe credentials

**Was:** `openModal()` ran a *full* reset (state **and** field values) on timers after the
modal was already visible — 50ms for login, 100ms **and** 300ms for signup.

**Now:** split each reset in two:
- `resetLoginModalState()` / `resetSignupModalState()` — display state only (2FA hidden,
  errors cleared, button/title reset). Safe to run on a timer.
- `resetLoginModalUI()` / `resetSignupModalUI()` — call the state reset, then clear values.
  Unchanged semantics, still used on open and on forced teardown.

`openModal`'s deferred calls now use the **state** variants. The timers stay, because they
fix a real stuck-2FA-state bug; they just may no longer destroy input.

**Why:** anything typed or autofilled inside that window was silently wiped and the form
submitted empty ("Please enter both email and password"). A human types slower than 50ms
and never sees it — **a password manager filling on modal-open does not.** The comment at
the old `landing.html:1188` said the reset existed to "catch any autofill", so the app was
deliberately fighting password managers on the login *and signup* paths.

**Callers checked:** `_resetLoginModalUI` (the window-exposed alias at ~1382) still points
at the full reset, so close/logout teardown callers keep their existing behaviour.
`test_login_modal_still_resets_stale_state_on_reopen` pins that the stuck-state fix
survives the split.

---

## B. New test infrastructure (3 files)

### B1. `tests/e2e/conftest.py` (new)

Session-scoped boot of the **real** app over **real TLS** on an ephemeral port, plus
`e2e_user`, `logged_in_page` (logs in once, reuses storage state), `login_through_ui`,
`attach_probe` / `PageProbe`, `assert_clean_page`, and `purge_org`.

Non-obvious decisions, all documented in the module docstring:

- **Boots `app.app:app`, not `create_app()`** — `app/app.py:24` composes the factory then
  registers `/`, `/dashboard`, `/healthcheck` on that instance. A bare `create_app()` is
  blueprint-only: no landing page, every navigation 404s.
- **Real TLS, not HTTP** — `SESSION_COOKIE_SECURE` defaults True and HSTS is only set on
  secure requests, so an HTTP boot breaks auth outright and makes the cookie/HSTS
  assertions untestable.
- **`ENVIRONMENT` unset** — `ENVIRONMENT=test` targets `host.docker.internal` and hangs
  from a host shell; the suite skips with that reason rather than hanging.
- **Rate limits deliberately NOT relaxed** — the limiter keys on `ip:email`, so unique
  per-run emails get their own bucket. Leaving it armed means Stage 1 can test it.
- **`purge_org` walks `Base.metadata.sorted_tables` in reverse** rather than a hand-written
  table list — logging in alone writes an `audit_logs` row FK'd to the user, and every new
  model would otherwise break teardown and get "fixed" by someone deleting the cleanup.
- **Chromium detected by filesystem, not `sync_playwright()`** — calling the sync API from
  a fixture raises "Sync API inside the asyncio loop" depending on test order, i.e. a flake.
- **Per-run uuid names, not `factory.Sequence`** — the sequence restarts at 0 each process,
  so one crashed run leaves `Test Org 0` and every later run dies on a unique violation
  before a single test executes.

### B2. `tests/e2e/test_smoke.py` (new)

Landing renders clean; login → dashboard; logged-out user cannot reach `/dashboard`.

### B3. `tests/e2e/test_landing_regressions.py` (new)

Pins A1 and A4 — both bugs were invisible to the entire existing unit suite.

---

## C. Config, docs, skill (4)

- **`pyproject.toml`** — added `pytest-playwright` to the `dev` extra; declared the `e2e`
  marker with its skip reason (markers are declared here so a typo is an error, not a
  silently-disabled gate).
- **`uv.lock`** — resolved for the above.
- **`.claude/skills/e2e-playwright/SKILL.md`** — corrected. It instructed
  `create_app()` + `ENVIRONMENT=test`, **both wrong**, either of which strands the next
  agent (blueprint-only app / hanging shell). Now documents the boot, the TLS requirement,
  and the skip-with-reason rule.
- **`.agents/specs/playwright-e2e.md`** — the spec itself: decisions D1–D5, staged
  checklists through Stage 6, findings, and CD deferred to "Later".

---

---

## E. Stage 1 — auth & 2FA (added 2026-07-17, same session)

**`tests/e2e/test_auth_flows.py` (new)** — 7 tests, all passing. Suite total now **16
passed**. No production code changed in this stage; no bugs found in the auth flows.

Covered: signup (happy + mismatched-confirmation unhappy path), login with a wrong
password (asserting *no session*, not just an error message), logout, the full 2FA
lifecycle through the UI (enroll → enable → wrong code rejected → right code admits →
disable returns login to one step), and password rotation (old password dead, new one
works).

**Two fixtures added to `tests/e2e/conftest.py`:**
- `fresh_user` — throwaway users for destructive tests. Without it, a test enabling 2FA on
  the session-scoped `e2e_user` would silently break every later test.
- `purge_after` — cleans app-created rows (signup) by email; registered *before* the action
  so cleanup survives a failing assertion.

**One harness bug fixed (mine, not the app's):** `assert_clean_page` treated Chromium's
"Failed to load resource: … status of 401" console message as an error. Status codes
already have their own channel in the probe — 5xx blocks, 4xx doesn't, because a 401/404 is
the *assertion* in unhappy-path and cross-tenant tests. The 2FA test's deliberate
wrong-code step therefore failed the clean check falsely. Console errors now mean
JavaScript faults only; the MIME-type signature that caught F1 is unaffected.

**Deliberately not covered yet** (recorded in the spec, not faked):
`/auth/2fa/cancel`, and session-timeout → `session_expired.html`, which needs a
short-timeout config for the E2E boot rather than a fabricated assertion.

---

## F. Stages 2–5 (added 2026-07-18, same session)

No production bugs found in these stages; the app's core flows and isolation are sound.
Suite total: **53 E2E tests, all passing.**

**`test_pages_render.py` (new)** — 21 authenticated pages (16 core + 5 CRM), each asserted
to render clean via the deterministic probe. Parametrised over the real route table so a
new page is one line and an untested page is a visible gap.

**`test_tenant_isolation.py` (new)** — the cross-tenant probe, the highest-value test here.
Two orgs in two real browser sessions; org B is denied org A's inventory by every surface:
barcode lookup (read-by-attribute — there is no GET-by-id route), PUT, DELETE, list, and
dashboard-summary aggregate. All correctly isolated. Notable: the app enforces **CSRF with
strict HTTPS referrer checking** on the core API (only `/auth/*` is exempt), so the probe
reads the token from the SPA's meta tag and sends a Referer exactly as the real client
does — CSRF stays armed and under test rather than disabled.

**`test_security_headers.py` (new)** — blocking-tier: `X-Content-Type-Options`, CSP,
`X-Frame-Options`, HSTS (≥180d, present because the E2E boot is real TLS), session-cookie
`Secure`/`HttpOnly`/`SameSite`, CSRF rejection of a token-less mutating POST, and JS served
with a real `javascript` MIME (the general form of the F1 bug). All pass.

**`test_inventory_flow.py` (new)** — the app's spine through the UI: manual add → redirect
to `/core` → item queryable in the API (the quantity write reached the DB). Plus the
unhappy path: a zero-quantity add writes no row.

**`test_crm_flow.py` (new)** — Xero OAuth entry builds a well-formed authorization redirect
**including the `state` parameter** (OAuth CSRF defence — a real security assertion, and
building the URL never contacts Xero); CRM API is auth-gated and org-scoped; CRM section is
navigable. Full Xero happy-path with a stubbed tenant is deferred (a test must never touch
a real tenant).

**Two fixtures added** (`fresh_user`, `purge_after`) in Stage 1 are reused throughout.

### git-commit-chain integration (Stage 5)

`skills/git-commit-chain/SKILL.md` step 7 now runs `uv run pytest tests/e2e -q` before push
for browser-touching changes, self-healing selector drift but treating app-behaviour /
tenant-isolation / security failures as real bugs to fix, never to silence. Skips cleanly
when chromium/cert/DB is absent.

---

## D. Known-failing / deferred

- **Nothing is failing.** The one test that failed on a real bug
  (`test_landing_page_renders_clean`) now passes because the bug is fixed, not because the
  test was weakened.
- **Test DB hygiene (pre-existing, untouched):** the test database holds months of
  leftovers — `CRM Test Org …` from May, `Execution Test Org …` from February/April,
  hundreds of rows. Not from E2E, whose teardown is verified to leave zero. It means unit
  fixtures elsewhere aren't cleaning up. Flagged for a `suite-warden` / `test-fixtures`
  pass; out of scope here.
- **Stages 1–6 not started.** Next is Stage 1 (auth/2FA flows).
