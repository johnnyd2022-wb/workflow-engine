# OBSERVABILITY: dilution_calculator
date: 2026-08-21
role: chain stage, instrument mode (invoked from review-feature)
verdict: clean

## Existing instrumentation (found, not added)
`app/features/dilution_calculator/routes/api_routes.py`:
- `logger.info("dilution_calculator_solved", solve_for=result["solved_field"])` on
  every successful solve — the feature's one state-representing event (though
  stateless/no DB write), asserted in
  `test_ac1_endpoint_logs_solved_event_on_success`.
- `logger.warning("dilution_calculator_rejected", reason=str(exc))` on every 400 —
  asserted in `test_ac4_endpoint_logs_rejection_event_on_validation_failure`.
- Both event names follow the repo's `<slug>_<verb_past_tense>` snake_case convention.

## access_denied
Both routes carry `@requires_auth`, the shared app-wide decorator
(`app/core/security/permissions.py:55`), which already logs `access_denied` (reason,
path, method) on every unauthenticated request — this is app-wide plumbing, not
per-feature, and applies to this slice without any extra code. There is no
per-feature `<slug>.access_denied` gap to add: per the spec (`tenant_scoped: no`) and
security-audit's independent check this run, the slice has no cross-tenant or
resource-level authorization surface (no `org_id`, no ownership check) — the kind of
denial the skill's `<slug>.access_denied` convention exists to catch on CRM-style
resource access simply doesn't exist here to log.

## External calls
None — no third-party APIs, webhooks, or outbound calls in this slice (confirmed by
spec's "External surfaces: none" and by code inspection: only stdlib `math`).

## Gaps
None found. This slice's only two meaningful events (success, rejection) are both
logged, asserted in tests, and there is no tenant/cross-org surface for an
`access_denied` audit trail to be missing from.

VERDICT: clean
