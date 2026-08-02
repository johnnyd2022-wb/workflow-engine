# REVIEW: compliance-checks
date: 2026-08-02
branch: review/compliance-checks (worktree cut fresh from origin/main)
baseline: tests green (41 passed: test_corechecks.py + test_finding_history.py + test_rule_candidates.py), working tree clean
verdict: **patched**

Execution mode: preflight (this worktree) reported `verification_mode: subagents`,
`grader_engine: claude`, `codex` capability `false`, `herdr_cli` capability `false` — the
router-level dispatch text for this task said `herdr-tabs`/`codex`, but neither tool was
actually present in this environment (`which codex` empty, no Herdr partner pane). Ran the
chain in-process instead and did the grading myself rather than fabricate an independent
pass — noting the fallback here per the verification-chain contract (§1: "on a fallback,
say so in the MR description").

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| spec reconstruction | reconstructed | — | [.agents/specs/compliance-checks.md](../../specs/compliance-checks.md) |
| security-audit | patched | 1 | this report (§ Findings) |
| unit coverage | patched | 3 modules/gaps closed | this report (§ Coverage) |
| e2e-playwright | clean (existing smoke test still green) | 0 new | this report (§ E2E) |
| ci-gate (ruff, semgrep, gitleaks) | clean | 0 | this report (§ Static analysis) |

## What was wrong, and what now stops it recurring

### F1 — no tenant-isolation test coverage anywhere on the check registry or its routes
The slice was semantically well-scoped (every check function takes an explicit `org_id`
and filters every query by it — `org_id = UUID(g.org_id)` in every route, `g.org_id`
itself derived only from the session user's `user.org_id` in
`app/api/middleware/tenant_context.py`, never a client-supplied header/param), but **zero
test proved it**. `tests/test_multi_tenant_isolation.py` (the repo's own
cross-tenant-isolation suite) had no reference to `corechecks`, and none of the five API
routes (`/api/core/system-findings`,
`/api/core/inventory/{expired-materials,untracked-items,output-expiry,output-ready-date}`)
appeared in any test file at all — not even a plain 200-OK smoke test. Per the feature
index's own cross-cutting invariant #5 ("Tenant isolation is tested... A new cross-org
read path needs a test there"), and given this registry is explicitly the plug-in point
for the unbuilt COMPLIANT tier (`.agents/feature-index.md`), an untested cross-org leak
here would leak compliance-relevant findings across tenants — the exact class of bug that
tier is being built to prevent, not create.

Manual review found no actual leak (semgrep: 0 findings across the backend + JS files in
scope; gitleaks: clean; manual trace of every query in `corechecks.py`,
`checks/*.py`, and `system_status.py` confirmed every query is `org_id`-filtered). But
"reviewed and looks fine" is not the same guarantee as "a test fails the day someone
removes a filter," so this review closes the gap rather than just noting it:

- `tests/test_corechecks.py::TestComplianceChecksTenantIsolation` (4 tests) — proves
  `run_expired_materials_check`, `run_untracked_items_check`,
  `get_system_findings_by_item`, and `CoreChecksRunner.run_all_checks()` all exclude a
  hostile-neighbour org's rows, using the shared `two_org_two_user` fixture.
- `tests/test_corechecks_routes.py` (new file, 12 tests) — the stronger version of the
  same claim, exercised through the real HTTP path (session → `g.org_id` → route →
  runner) rather than calling the check function directly: all 5 routes require auth
  (401 unauthenticated), all 5 return the documented response shape when authenticated,
  and two dedicated cross-tenant probes (`/api/core/inventory/untracked-items` and the
  aggregate `/api/core/system-findings`) prove org B never sees org A's item and vice
  versa.

## Coverage

Before this review, `system_status.py` (drives the dashboard compliance summary AND the
notifications page health state) and `app/core/domain/expiry_ready_date_rules.py` (the
documented single source of truth for the ready-date/expiry ordering invariant) had
**zero** test coverage — `coverage.py` warned `Module ... was never imported` for both.
`corechecks.py` itself was at 45%, almost entirely the route handlers in
`register_routes` (no HTTP-level test existed for any of them — see F1).

| module | before | after |
|---|---|---|
| `app/core/backend/corechecks.py` | 45% | 79% |
| `app/core/backend/system_status.py` | 0% (never imported) | 66% |
| `app/core/domain/expiry_ready_date_rules.py` | 0% (never imported) | 79% |
| slice total (9 modules measured) | 59% | 66% |

Added: `TestSystemStatus` (7 tests: onboarding completion, health-state derivation,
activation vs. health mode) and `TestExpiryReadyDateInvariant` (5 tests: both the
duration-based and date-based forms of the ready-date ≤ expiry-date invariant, including
the "missing values → no error" path callers rely on).

Remaining gaps, not closed in this pass (proportionality — see Rules in the skill):
`output_expiry_check.py` (72%) and `output_ready_date_check.py` (53%) have the densest
branch counts in the slice (unit-normalization fallbacks, legacy config shapes, the
`set_at_execution` per-item override paths) and `expiry_rules.py` (38%,
`assert_warning_within_expiry` / `duration_to_timedelta`) is exercised only through its
sibling `ready_date_rules.py` tests, not directly. None of these are new code and none
came up in the security pass; flagging for a follow-up coverage sweep rather than
expanding this review's diff further.

## E2E

`tests/e2e/test_pages_render.py::test_core_page_renders_clean[chromium-/core/notifications]`
already existed and passed before and after this review (console-clean, no failed/5xx
requests, non-zero body height). That is the full extent of e2e coverage for this slice —
no test drives the interactive flows (snooze/hide a finding, switch Active/Archive tabs,
open the reconcile modal, trigger "dispose of inventory item"). All of that state is
client-side only (`sessionStorage`, confirmed by reading both JS files — no
server-persisted dismiss/snooze), so the blast radius of a regression there is UI-only,
not data-integrity or tenant-isolation. Recommend a follow-up e2e-playwright pass to add
interaction coverage; not added here to keep this review's diff to what F1 required.

## Static analysis

- `semgrep` (`.semgrep/` custom rules + `p/flask` + `p/owasp-top-ten`, 246 rules) against
  every backend/domain file in scope plus both frontend JS files: **0 findings**.
- `gitleaks`: **0 findings** across the backend/domain files.
- Manual read of both frontend JS files for the DOM-injection class specifically (every
  `innerHTML` call site): every dynamic value that reaches `innerHTML` goes through
  `escapeHtml()` first (including the shared `window.renderReadyDateStatus` helper in
  `core-api.js`, which takes `escapeHtml` as an explicit parameter rather than assuming
  its caller escaped already); `system-findings-notifications.js` uses `textContent`
  exclusively for user-controlled strings and never touches `innerHTML` except to clear a
  list and set one static (non-interpolated) glyph. No finding.
- `ruff check` / `ruff format --check` on both new/changed test files: clean.

## Regression check

`uv run pytest tests/ -q --ignore=tests/tmp_cleanup_test.py --ignore=tests/e2e`: **679
passed**, 0 failed (170s). `tests/test_corechecks.py` + `tests/test_corechecks_routes.py`
+ `tests/test_finding_history.py` + `tests/test_rule_candidates.py` +
`tests/test_multi_tenant_isolation.py` together: **76 passed**. The e2e notifications
smoke test: **1 passed**. No production code was changed by this review — every change is
additive test coverage, so the regression surface is the test suite's own correctness,
not application behavior.

Pre-existing, unrelated to this slice: `tests/tmp_cleanup_test.py` is an **untracked**
scratch script (not in `origin/main`, present before this review started) that pytest
tries to collect as a test module and fails on import (a stray top-level DB cleanup
script, not a real test — no test functions, runs mutating code at import time). It
breaks `pytest tests/` run without an `--ignore`. Left untouched (not part of this
slice, and not safe to delete someone else's uncommitted work without asking) — flagging
here since it will surprise the next person who runs the bare command from
`CLAUDE.md`.

## Spec

No spec existed at `.agents/specs/compliance-checks.md` before this review.
Reconstructed with `status: reconstructed`, 24 acceptance criteria across the four
built-in checks, the aggregate API, the registry contract, and the frontend
escaping/session-storage behavior. Status is being set to `reviewed` in this same commit
per the skill's Step 5 instruction.
