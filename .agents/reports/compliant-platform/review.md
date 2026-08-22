# REVIEW: compliant-platform
date: 2026-08-22
branch: mc/review-feature-20260822-093201-07baa9
baseline: tests green (5 passed, 0 pre-existing failures), working tree clean
verdict: **patched**

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration-safety | clean | 0 (1 out-of-scope, routed not fixed) | [migration-safety.md](migration-safety.md) |
| security-audit | findings-open → patched | 1 | [security-audit.md](security-audit.md) |
| e2e-playwright | patched | 1 app bug (found live, root-caused by orchestrator) | [e2e-playwright.md](e2e-playwright.md) |
| unit coverage + tests | patched | coverage 86%→92% (service.py 80%→92%, api_routes.py 88%→90%) | (see review body below) |
| test-evaluator | mixed → patched | 5 (1 real source defect + 4 test-strictness gaps) | [test-evaluator.md](test-evaluator.md) |
| perf-guardrails | clean | 0 | [perf-guardrails.md](perf-guardrails.md) |
| observability | patched | 2 (missing access_denied traces) | [observability.md](observability.md) |
| ci-gate | clean | 0 | [ci-gate.md](ci-gate.md) |

Execution mode: `herdr-tabs` per preflight for migration-safety/security-audit/
e2e-playwright/test-evaluator; the remaining stages (unit-coverage/test-authoring,
perf-guardrails, observability, ci-gate) ran in-process by the orchestrator after three
launched stages hit usage-limit boundaries mid-run in this session — `.agents/
verification-chain.md` §1 treats this as an equally valid mode ("only execution
differs"), and this is disclosed here per that same section's fallback-disclosure rule.
Two launched stages (migration-safety, e2e-playwright) stalled without writing their
report; one (test-evaluator) completed but its designated write was correctly rejected
by its read-only sandbox. All three are transcribed onto this branch by the orchestrator
per `.agents/verification-chain.md` §5 — see each report's own note.

No spec existed for compliant-platform before this review (`reviewed: never`); one was
reconstructed from the code and user-confirmed before the chain ran
(`.agents/specs/compliant-platform.md`).

Three real defects found and fixed, plus one incidental infrastructure incident repaired
along the way.

## What was wrong, and what now stops it recurring

### F1 — `/compliant/static/<filename>` was completely broken for every caller
`app/features/compliant/compliant_bp.py`. The custom static-file view was named `static`,
giving it the Flask endpoint `compliant.static` — which collides with a codebase-wide
convention (`app/api/middleware/tenant_context.py:71`,
`app/api/middleware/session_security.py:42`): any endpoint ending in `.static` is treated
as Flask's own built-in, intentionally-public static route and skipped when populating
`g.current_user`. Because this route is a *custom* view sharing that name, `@requires_auth`
always saw an unauthenticated request and the app's global 401 handler 302-redirected every
GET to `/` — `compliant.js`/`compliant.css` were never served to anyone, authenticated or
not. In a real browser this meant the whole `/compliant` dashboard rendered with no styling
and no interactivity. Found live by the e2e-playwright chain stage (6 test failures,
`test_dashboard_page.py`/`test_static_asset_security.py`), root-caused by the orchestrator
after the launched stage stalled mid-run before diagnosing it. Same bug class, independently
found and fixed the same way in the `process_templates` review that merged just before this
one (`process_templates_bp.py`'s own comment documents the identical failure mode).
**Fix**: renamed to `serve_compliant_static`, matching the pattern already established by
`crm_bp.py` and `process_templates_bp.py`. No `url_for()` call site to update — both
template references are literal paths. `scripts/finding_history.py` sig `771d29ea8634`.
Stops recurring: covered end-to-end by 6 of the 50 new E2E tests in
`tests/e2e/compliant-platform/test_static_asset_security.py` and
`test_dashboard_page.py`.

### F2 — CSV formula/DDE injection in the audit-pack export
`app/features/compliant/routes/api_routes.py`, `get_report`'s `?format=csv` branch. A
record's `title`/`evidence_reference` (free text, validated only for length) was written
straight into CSV cells. A title beginning `=`, `+`, `-`, or `@` round-trips unmodified into
the export — audit packs are handed to external auditors who open them in
Excel/Sheets/LibreOffice, where an unescaped leading formula character can trigger legacy
DDE execution or `HYPERLINK`-based exfiltration. Found by the security-audit stage (F1 in
its own report; confirmed by the community `csv-writer-injection` semgrep rule).
**Fix**: `_csv_safe()` helper prefixes any of `= + - @ \t \r` with a leading apostrophe
before the cell is written, applied to both attacker-controlled columns. No existing
sanitizer elsewhere in the app to reuse — this was the only CSV export. `finding_history.py`
sig from security-audit's own report. Stops recurring: 8 unit tests
(`tests/test_compliant_routes.py`) — a parametrized direct test of `_csv_safe` over all six
trigger characters (test-evaluator's own mutation check found the original round-trip test
only proved `=`/`+`, so a narrowed prefix set would have stayed green) plus the original
end-to-end CSV-export regression test.

### F3 — `POST /api/compliant/records` accepted records against a *disabled* profile
`app/features/compliant/routes/api_routes.py:239` checked `if profile is None:` instead of
`if profile is None or not profile.enabled:` — an org that had enabled Compliant and then
disabled it (`PUT /profile {enabled: false}`) could still attest new compliance records,
contrary to the spec's "Requires an existing **enabled** ComplianceProfile (409 otherwise)".
`POST /api/compliant/reports/<slug>` already had the correct check
(`service.build_audit_pack`). Found by the independent test-evaluator grader via a
test-strictness finding (the existing "requires a profile" test only covered *missing*
profile, not disabled), not by a scanner — the kind of defect that only surfaces when
someone asks "would this test actually catch a real regression?" **Fix**: one-line
condition change. Stops recurring: new E2E test in `test_records_flow.py` pins the disabled
case explicitly, separate from the missing-profile case.

## Incidental: shared test-DB schema drift, found and repaired
The launched migration-safety stage went beyond its scoped task (verifying
`compliant_nz_alcohol_001`'s own `-1`/`+1` round-trip, which it *did* complete and confirm
clean) into replicating CI's stricter `base → head → base → head` cycle, and hit a real,
pre-existing, **unrelated** bug: `api_idempotency_keys_001`'s `downgrade()` unconditionally
drops an index it may never have created (a parallel-branch-merge idempotent-upgrade
interaction), the same reversibility-fragility class already documented and left unfixed in
`.agents/reports/inventory/review.md`. That run left the **shared** test-DB fixture with the
index missing while `alembic_version` still claimed head — repaired directly
(`CREATE INDEX` matching the migration's own definition) and verified with a full local
suite run (1610 passed, 31 skipped, one unrelated flaky e2e connection error that passed
clean on retry) before continuing. Routed, not fixed here — belongs to whichever
migration/branch-merge owns `api_idempotency_keys_001`. See `migration-safety.md`'s
"Out of scope, found anyway" section.

## Coverage
Before this review: 86% (`app/features/compliant/`, platform-scope files only —
`modules/nz_alcohol/` excluded). After: 92%. `service.py`'s core business logic went from
80% to 92% — the pure `calculate_customs_reconciliation` LAL calculation (the product's
stated "live evidence" value proposition) had zero coverage before this pass, and several
`_control_state` branches (overdue/breached reasons, the reconciliation control's live-data
and declared-vs-calculated-variance attention states, the CRM-mapping setup fallback, the
consent-profile compliant state) were untested. `frameworks.py`/`registry.py` remain at 0% —
confirmed dead/compatibility-shim code (`registry.py`'s `register_compliant_checks` is
unused; Core imports `platform/registry.py` directly), out of this review's scope. A handful
of `api_routes.py`/`service.py` lines remain uncovered — mostly repetitive request-validation
boilerplate following an already-proven pattern, or defensive guards; disclosed here rather
than chased for diminishing returns.

## Disclosed, not chased
- `service.py` imports `NZ_ALCOHOL_FRAMEWORKS`/nz_alcohol catalogue functions directly in
  `evaluate()`/`build_audit_pack()` — the feature index itself flags this as documented,
  deliberate debt ("to split when a second module lands"), not a defect for this review to
  refactor.
- `app/features/compliant/registry.py`'s `register_compliant_checks()` wrapper is unused
  dead code (Core calls `platform/registry.py` directly); `frameworks.py` is a pure
  re-export. Left as-is — a cleanup, not a defect, and out of this review's stated scope
  ("do not refactor beyond what findings require").
- CLAUDE.md's documented test count ("730 passed, 30 skipped") is stale against the
  current suite (1610 passed, 31 skipped as of this run) — pre-existing, unrelated to this
  feature, a docs-truth item.

## Verification
```
uv run pytest tests/test_compliant_routes.py tests/e2e/compliant-platform -q
75 passed, 13 warnings in 133.73s (0:02:13)
```
Plus the full compliant-adjacent set (catalog, frontend-assets, execution-modal,
process_templates cross-slice tests): 155 passed. Full local ci-gate equivalent: see
`ci-gate.md` — lint, semgrep, gitleaks, uv_audit, migrations, e2e, perf all pass.

## Recommendation
Ship. Three real defects fixed (one user-facing frontend breakage, one security finding,
one spec-violating functional bug), coverage materially improved on the feature's core
business logic, tenant isolation independently verified clean by both the security-audit
grader and 7 dedicated cross-tenant E2E tests, and observability gaps closed to match the
codebase's established `access_denied` tracing convention.
