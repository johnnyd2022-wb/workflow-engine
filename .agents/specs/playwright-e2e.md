# Spec: Playwright E2E suite

Status: **draft for review** — nothing built yet.
Owner skill: `e2e-playwright` (exists as docs only; this spec is its implementation).

## Goal

A headless Playwright suite covering every core flow, run locally by
`/git-commit-chain` before it pushes, that self-heals test-side breakage and stops on
app-side breakage. Plus a dynamic skill that picks the right subset from the diff and
writes tests for surfaces that don't have one.

Deploy/CD gating is **out of scope** — captured in "Later" at the bottom. The app is
still being built locally; there is nothing to deploy yet.

## Decisions taken

| # | Decision |
|---|---|
| D1 | E2E boots `create_app()` on an ephemeral port with `ENVIRONMENT` **unset** (→ `local.ini`, test DB on :8401). `ENVIRONMENT=test` hangs from a host shell (`test.ini` → `host.docker.internal`). `e2e-playwright/SKILL.md` currently instructs the broken way and gets corrected as part of Stage 0. |
| D2 | **Two tiers.** *Blocking* checks are deterministic and stop a push. *Advisory* checks are heuristic — they run everything worth catching (visual diff, perf budgets, a11y, agent screenshot review) and **report without blocking**. Rationale: a non-deterministic blocking gate becomes a coin flip, and a flaky gate gets disabled within a month and then protects nothing. Two tiers catch strictly more than deterministic-only, without buying that. |
| D3 | Self-healing covers **selectors and locators only**. A test failing on app behaviour is reported, never rewritten to match. Assertions are never weakened to get green (`.agents/autonomy.md`, suite-warden). |
| D4 | Missing chromium is a **skip with a reason**, never a failure (suite-warden's rule, same shape as the existing `live_server` marker). |
| D5 | Test selection is a **deterministic script**, `scripts/e2e_select.py`, not agent judgement. Follows the house pattern set by `preflight.py` / `error_scan.py` / `skill_graph.py`: stdlib only, `--json` first, reports but does not fix — the calling skill decides. |

## Stage 0 — Foundation ✅ done (2026-07-17)

- [x] `uv add --optional dev pytest-playwright` and `uv run playwright install chromium`
- [x] Declare an `e2e` marker in `pyproject.toml` `[tool.pytest.ini_options]` with a reason string
- [x] `tests/e2e/conftest.py`: boot the app once per session on an ephemeral port (D1), tear down after
- [x] Skip the whole `tests/e2e` suite with a reason when chromium / TLS cert / test DB is absent (D4)
- [x] Reuse `OrganisationFactory` / `UserFactory` from `tests/factories.py` — no parallel world
- [x] `logged_in_page` fixture: authenticate once through the real login flow, reuse storage state
- [x] `assert_clean_page` helper implementing D2's blocking-tier checks
- [x] Correct `.claude/skills/e2e-playwright/SKILL.md` (D1 + the `create_app()` trap below)
- [x] Proof: login → `/dashboard` → clean. 3/3 identical runs, no flake, zero DB residue.

### What Stage 0 turned up

Corrections to the harness's own design, now encoded in `tests/e2e/conftest.py`:

| Finding | Consequence |
|---|---|
| `create_app()` is **not** the app. `app/app.py:24` composes it, then registers `/`, `/dashboard`, `/healthcheck` on that instance | The skill's documented boot gives a blueprint-only app where every page 404s. Boot `app.app:app`. |
| `SESSION_COOKIE_SECURE` defaults True; HSTS only set on secure requests | E2E must serve real TLS. An HTTP boot breaks auth outright. |
| `app/app.py:16` used a bare `from initialize import db_conn` | Only resolved when run as a script; broke package import. Fixed to `from app.initialize import db_conn` (the file's other imports were already `app.`-prefixed). |
| `factory.Sequence` restarts at 0 per process | A crashed run leaves `Test Org 0`, and every later run dies on a unique violation before any test runs. E2E names carry a per-run uuid. |
| Logging in writes an `audit_logs` row FK'd to the user | Naive teardown dies on the FK. `purge_org()` walks `Base.metadata.sorted_tables` in reverse so new models are covered automatically. |
| Checking chromium via `sync_playwright()` inside a fixture | Raises "Sync API inside the asyncio loop" depending on test order — an order-dependent skip, i.e. a flake. Now a filesystem check. |

**Two real app bugs found (not test bugs) — see Findings below.**

## Stage 1 — Auth & 2FA ✅ mostly done (2026-07-17) — `tests/e2e/test_auth_flows.py`

- [x] Signup → org created → landed logged in
- [x] Login (happy) → `/dashboard` (in `test_smoke.py`)
- [x] Login (bad password) → error shown, **and no session** (asserted by then requesting
      a protected route, not just by the error text)
- [x] 2FA enroll → secret → enable with two valid consecutive TOTPs
- [x] Login with 2FA active → gate appears → valid code → dashboard
- [x] 2FA verify with wrong code → error, still gated
- [x] 2FA disable → login returns to one step
- [x] Signup unhappy path: mismatched confirmation → error, no account
- [x] Change password → old password rejected, new one works
- [x] Logout → protected route no longer reachable
- [ ] 2FA **cancel** path (`/auth/2fa/cancel`) — not yet covered
- [ ] Session timeout → `session_expired.html` — not yet covered; needs either a
      short-timeout config for the E2E boot or session-cookie manipulation. Deferred
      rather than faked.

New fixtures this stage (`tests/e2e/conftest.py`):

- **`fresh_user`** — throwaway users a test may mutate. `e2e_user` is session-scoped and
  backs the shared login state, so a test that enables 2FA or rotates a password on it
  would silently break every later test. Distinct emails also give each test its own
  `ip:email` rate-limit bucket.
- **`purge_after`** — cleans rows created *through the app* (signup), by email. Registered
  before the action so cleanup still runs when the assertion between fails; otherwise one
  failing signup test poisons the next run.

### Harness correction found this stage

`assert_clean_page` counted Chromium's "Failed to load resource: … status of 401" console
messages as errors. HTTP status already has its own channel in the probe (5xx blocks; 4xx
does not, because a 401/404 is the *assertion* in unhappy-path and cross-tenant tests), so
any test deliberately exercising a rejection could never also assert the page was clean —
it surfaced as a false failure on the 2FA test, whose wrong-code step 401s on purpose.
Console errors now mean JavaScript faults only. The MIME-type error that caught F1 does
not match the filter, and F1 stays independently pinned by its own status/content-type
assertion.

## Stage 2 — Core: flows, executions, inventory

- [ ] Process/flow create wizard end-to-end: `/core/flows/create` steps 1–4 → process persisted and listed at `/core/processes`
- [ ] Wizard fragments render and advance: process-overview, step-name, inputs, outputs, evidence-and-prompts, summary, next-steps
- [ ] Wizard unhappy path: invalid step input → error, no partial process created
- [ ] Batch start (`/core/flows/batches/start`) → execution created
- [ ] Execution step (`/core/flows/executions/step`) → complete a step → progress reflected
- [ ] `/core/executions/live` shows the running execution
- [ ] Inventory add — manual (`/core/inventory/add/manual`) → quantity write with a reason
- [ ] Inventory add — CSV upload (`/core/inventory/add/csv`)
- [ ] Inventory add — barcode (`/core/inventory/add/barcode`)
- [ ] `/core/inventory/view` and `/core/inventory/live` reflect the write
- [ ] Inventory dispose → confirm → wastage recorded
- [ ] Inventory unhappy path: quantity write without a valid reason is rejected
- [ ] `/core/dashboard`, `/core/settings`, `/core/integrations`, `/core/notifications` render clean

## Stage 3 — CRM

**Nothing here is skipped.** `crm_enabled` is forced **on** for the E2E boot rather than
skipped when off — a flag being off must not silently drop this coverage.

**Hard constraint:** a test never touches a real Xero tenant. It would write real invoices
against live accounting data. Xero is stubbed at the HTTP layer — which costs no coverage,
because the code under test is ours, not Xero's. The stub replaces their server, not our flow.

- [ ] Force `crm_enabled` on for the E2E app boot; assert it's on rather than skip
- [ ] `/crm`, `/crm/customers`, `/crm/customers/<id>`, `/crm/tasks`, `/crm/analytics`, `/crm/configuration` render clean
- [ ] Customer create → appears in list → detail page
- [ ] Customer edit and delete
- [ ] Tasks: create, complete
- [ ] Analytics and configuration pages render with real seeded data, not empty states
- [ ] Xero stub at the HTTP layer (fixture-owned, asserts no real network egress)
- [ ] `/crm/xero/auth` → redirect carries correct client_id, scopes, state
- [ ] `/crm/xero/callback` → happy path → tokens stored
- [ ] `/crm/xero/callback` → error/denied path → handled, no broken UI
- [ ] `/crm/xero/callback` → **state mismatch is rejected** (CSRF on the OAuth leg)
- [ ] `/crm/xero/select-tenant` GET renders tenants; POST selects and persists
- [ ] Invoice create against the stub → success reflected in the UI
- [ ] Xero API failure (500/timeout) → error surfaced, no silent data loss
- [ ] Token refresh path exercised against the stub
- [ ] Cross-tenant: org B cannot reach org A's contacts or Xero connection

## Stage 4 — Cross-cutting (mandatory regardless of flow)

- [ ] Cross-tenant probe: logged in as org B, request org A's object URL directly → 404. Repeat per resource type (process, execution, inventory item, CRM contact).
- [ ] Org user management: add user, remove user, non-member is refused
- [ ] Every form has an unhappy-path test: invalid input → error shown, no record written
- [ ] `assert_clean_page` applied to every page-rendering test (D2 blocking tier)
- [ ] Flake gate: full suite 3x green before the suite is trusted or wired anywhere

### Blocking tier — deterministic, stops a push (D2)

Security:
- [ ] Cross-tenant probe (above) — the highest-value check in this suite
- [ ] Session cookie flags: `HttpOnly`, `Secure`, `SameSite` set on auth cookies
- [ ] CSP and HSTS response headers present on every page
- [ ] CSRF: a state-changing POST without `X-CSRFToken` is rejected
- [ ] No secrets, tokens, or other orgs' identifiers rendered into the DOM
- [ ] Protected route while logged out → redirect, never content

UI:
- [ ] Zero console errors and zero failed network requests per page
- [ ] No zero-height / unstyled / unrendered container (catches CSS or template breakage)
- [ ] No offscreen or overlapping interactive element
- [ ] Every interactive element has an accessible handle

Performance (generous budgets — catch collapse, not jitter):
- [ ] Page load and key interactions under a fixed budget
- [ ] No runaway request count or payload size per page (catches N+1 leaking to the UI)

### Advisory tier — heuristic, reports, never blocks (D2)

- [ ] Visual diff against baselines — surfaced as a report; baseline drift never fails a push
- [ ] Agent review of screenshots for "something looks off" — genuinely catches what rules miss, precisely because it isn't rule-bound
- [ ] Full a11y scan (axe) beyond the blocking handle check
- [ ] Tight perf budgets that would be too noisy to block on
- [ ] Output: `.agents/reports/e2e/advisory.md` — read by a human, or by the agent as evidence when something is already suspected
- [ ] Advisory findings that prove reliable get **promoted** to the blocking tier; that promotion is a deliberate decision, not a default

## Progress snapshot (2026-07-18)

Stages 0–5 substantially built. **53 E2E tests, all passing**, 3× no flake; unit suite
still `252 passed, 30 skipped`; ruff + semgrep clean. Test files:
`test_smoke.py`, `test_landing_regressions.py`, `test_auth_flows.py`,
`test_pages_render.py` (21 pages), `test_tenant_isolation.py` (the cross-tenant probe),
`test_security_headers.py`, `test_inventory_flow.py`, `test_crm_flow.py`.

Deferred (recorded, not faked): full Xero OAuth happy path with a stubbed tenant;
session-timeout page; `/auth/2fa/cancel`; a UI-driven process→execution walk (the wizard
is many fragments — covered at render level, not yet click-through); Stage 6 dynamic
selection script. None block the current PR.

## Stage 5 — `/git-commit-chain` integration ✅ done (2026-07-18)

Step 7 of `skills/git-commit-chain/SKILL.md` now runs `uv run pytest tests/e2e -q` before
push when the change touches a browser-exercised surface, with the self-heal rule bounded
by D3 (fix selectors, never weaken assertions; tenant-isolation and security failures are
always app bugs). The suite skips with a reason when chromium/cert/DB is absent, so it is
safe to run unconditionally.

### Original Stage 5 checklist

Note: the skill lives at `skills/git-commit-chain/`, **not** `.claude/skills/` — confirm
how it's registered before editing.

- [ ] Step 7 (tests + semgrep before push) also runs `tests/e2e`
- [ ] E2E failure blocks the push, same as a unit-test failure
- [ ] Self-heal loop, bounded by D3: selector/locator drift is repaired and committed; app-behaviour failure is reported and stops the chain
- [ ] Chromium absent → skip with reason, chain proceeds (D4) — a missing browser must not block a commit
- [ ] Document the E2E step in the skill's reported output

## Stage 6 — Dynamic test selection (`scripts/e2e_select.py` + skill)

The mapping is a **script**, not agent judgement (D5). The skill calls it and acts on
the JSON; the script decides nothing about repair.

### The script

- [ ] `build_index()` — walk `tests/e2e/`, extract each test's `page.goto()` routes and
      asserted handles → `{test: [routes]}`
- [ ] `map_routes_to_source()` — resolve each route to its handler and template via the
      `@bp.route` decorators, then to that template's `{% include %}` / `{% extends %}`
      children and its `app/ui/shared` + `app/core/frontend` JS/CSS. A wizard fragment
      changing must select the wizard test.
- [ ] `changed_files(base)` — `git diff --name-only <base>...HEAD`
- [ ] `select(changed)` → `{"run": [tests], "uncovered": [routes], "reason": {...}}` —
      every selection traceable to the file that caused it
- [ ] `--json` machine-readable, human summary by default, stdlib only (D5)
- [ ] Index persisted at `.agents/cache/e2e-index.json` and incrementally updated —
      re-walk only files newer than the cache, so it's cheap enough to run every commit.
      Gitignored, not committed: it's derived, and a stale committed index is a silent
      wrong answer inside a PR.
- [ ] The cache also feeds **test creation**, not just selection: it's the record of which
      routes already have coverage, so `uncovered` is a lookup rather than a re-derivation.
- [ ] Fail-safe: anything unmappable (shared CSS, `conftest.py`, a factory, a cache miss)
      selects the **full suite**. Unknown means run everything, never run nothing.
- [ ] Unit tests for the mapper itself — a selector that silently under-selects is worse
      than no selector, because it reports green over untested code

### The skill

- [ ] Calls `e2e_select.py --json`, runs only the selected subset on the commit path
- [ ] `uncovered` non-empty → scaffold a test from the route + template, run it, include it
- [ ] New route/page/button in the diff → new test scaffolded against it
- [ ] Bounded by D3: may add tests and fix selectors; may never rewrite an assertion
- [ ] Full suite still runs in CI (Later); the subset is a local-speed optimisation, never the only gate

## Later (notes, not scope)

- Split CI vs CD once the app deploys. Today `.gitlab-ci.yml` has `test`/`security`/`migrations` and **no deploy stage**; deploy is `scripts/git_workflow.sh prod` locally (tags, healthchecks :8000, pushes tag on pass).
- Full E2E suite runs on CD post-merge, pre-deploy, with screenshots + traces as artifacts.
- `/git-commit-chain` watches that CD pipeline for failures (it already monitors pipelines to terminal state in steps 9–11).
- `deploy_prod()` gains an E2E precondition.
- Revisit visual regression then, if deterministic checks (D2) prove insufficient.

## Findings — real app bugs ✅ both fixed (2026-07-17)

Both were caught by the blocking-tier checks on their first run, on the landing page —
the one page every prospect sees, and both invisible to the entire existing unit suite.
Fixes and full rationale: `.agents/reports/e2e/stage-0-changes.md` (A1, A4), pinned by
`tests/e2e/test_landing_regressions.py`.

A third, pre-existing, was fixed while in the same file: the index route ran
`render_template_string` over a Jinja-free `landing.html` on every request — semgrep's one
blocking finding (SSTI) plus a per-request disk read and recompile on the busiest public
page. Now `send_from_directory`. Scan is clean (see A3).

### F1. `password-policy.js` never loads on the landing page ✅ fixed

`/ui/shared/<filename>` is `@requires_auth` (`app/api/app_factory.py:100-103`), but
`landing.html:1585` loads `/ui/shared/password-policy.js` while logged out. Confirmed:
the request 302s to `/` and returns `text/html`, so the browser refuses to execute it
("MIME type ('text/html') is not executable").

Impact: `landing.html:1506` guards with `if (window.PasswordPolicy)`, so it fails
**silently** — signup gets no live password-policy warnings, ever. Users hit rejection on
submit instead of guidance while typing. Not a security hole (the server still validates
at `/auth/signup`), but a real UX regression on the signup path.

The tell that this is an inconsistency rather than a design choice:
`/auth/password-policy-check` (`auth_routes.py:1242`) is itself **public** — because
signup needs it. The endpoint is public; the script that calls it is gated.

**Fixed** with option (a): module constant `PUBLIC_UI_SHARED_FILES` in `app_factory.py`
allowlists `password-policy.js`; everything else under `/ui/shared` stays authenticated,
pinned by `test_gated_shared_assets_still_require_auth`.

### F2. The login modal wipes its fields 50ms after opening ✅ fixed

`openModal()` (`landing.html:1170-1177`) runs `resetLoginModalUI()`, opens the modal, then
schedules **another** `resetLoginModalUI()` 50ms later. Anything typed in that window is
cleared and the form submits empty ("Please enter both email and password").

A human types slower than 50ms and never sees it. **A password manager autofilling on
modal-open does not** — and the comment at the old `landing.html:1188` said the reset
existed to "catch any autofill", so the app was deliberately fighting password managers.
**Signup had it worse**: full resets at 100ms *and* 300ms, on the conversion path.

**Fixed** by splitting each reset into a state-only variant (2FA hidden, errors cleared,
button reset — safe on a timer) and the existing full variant (state + values — used on
open and forced teardown). `openModal`'s deferred calls now use the state variants, so the
stuck-2FA-state fix the timers exist for still works while input survives. The harness no
longer needs to synchronise past it, which is itself the proof.

## Housekeeping (not blocking)

The test DB carries months of accumulated leftovers — `CRM Test Org …` from May,
`Execution Test Org …` from February/April, hundreds of rows. Pre-existing and unrelated
to E2E (whose teardown is verified to leave zero residue), but it means fixtures elsewhere
aren't cleaning up. Worth a `suite-warden` / `test-fixtures` pass.

## Open questions

All settled.

1. ~~Stage 3 — stub Xero, or skip the OAuth leg?~~ Stub at the HTTP layer, cover every
   leg, never touch a real tenant.
2. ~~F1 — auth posture on `/ui/shared`?~~ Allowlist the single public asset.
3. ~~F2 — fix the deferred reset?~~ Fixed, login and signup.

Standing instruction from the founder (2026-07-17): work autonomously for the rest of the
session — refactor where it is the right call, optimise for the app being secure,
performant, and for catching real bugs before prod. CI is the backstop. Document every
change for review in `.agents/reports/e2e/`.
