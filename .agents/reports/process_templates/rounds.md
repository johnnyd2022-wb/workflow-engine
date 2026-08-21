# process_templates — verification rounds

## Spec critic

- Round 1 (2026-08-22): gaps-found. AC9 mechanism didn't exist in real code
  (requires_inventory_selection is frontend-only); AC6/AC10 response-shape conflict;
  missing catalogue-page/redirect AC; undefined description-fallback text. Report:
  .agents/reports/process_templates/spec-critic.md
- Round 2 (2026-08-22): sound. All four fixes verified against real code
  (backend.py line numbers checked). One non-gating note: `catalogue_version` type/
  starting value undefined — resolved during build as a per-template static int
  starting at 1. Report: .agents/reports/process_templates/spec-critic-round2.md

## build-review (Codex, advisory)

- Round 1 (2026-08-22): inconclusive, not blocking. Herdr-tab prompt used
  "Architect/Breaker" framing which triggered Codex's ambient
  `herdr-multi-agent-collab-breaker` skill; it explored that protocol's docs before
  reading the real diff, then appears to have exhausted its `medium`-effort budget
  mid-review with no closing summary or VERDICT line. `blocking: false` per
  model-routing.json, so this did not gate the chain — real diff coverage came from
  security-audit (blocking, clean) and test-evaluator (blocking) instead. Report:
  .agents/reports/process_templates/build-review.md

## security-audit ∥ e2e-playwright (parallel group)

- Round 1 (2026-08-22): security-audit clean (2 mitigated false-positives; flagged a
  process note that a prior run improperly self-recorded false-positive verdicts to
  finding_history.py — needs human ratification). e2e-playwright: an orchestrator
  mistake launched a duplicate invocation while the herdr-tab one was still running,
  causing a real two-writer collision on tests/e2e/process_templates/*; one process
  detected it and stood down, the other's work survived intact. Running that surviving
  suite for the first time (never run before) surfaced two real, deterministic bugs
  it was written correctly to catch: (1) the static-asset route's Flask endpoint name
  collided with tenant_context.py's `.static`-suffix public-endpoint convention,
  making @requires_auth 401 unconditionally, which the global 401 handler turned into
  a silent redirect-to-`/` that broke the JS/CSS entirely; (2) `.pt-modal-overlay`'s
  `display: flex` defeated the `[hidden]` attribute's default hiding, blocking clicks
  through an invisible-but-present modal. Both fixed; a same-class pre-existing bug in
  compliant_bp.py's own static route was flagged but left unfixed (out of scope).
  8/8 e2e tests green after fixes; full regression (unit + e2e + the wizard suite)
  re-run clean, 59/59. Reports: .agents/reports/process_templates/security-audit.md,
  .agents/reports/process_templates/e2e-playwright.md

## security-tenant-audit (Codex, blocking)

- Round 1 (2026-08-22): clean. Ran directly via `codex exec --sandbox read-only`
  (avoided the "Architect/Breaker" phrasing that derailed build-review). Independently
  re-verified org_id provenance through every service call site, the registry's
  family-permission intersection at both the detail and copy call sites, the
  sample_only override's scoping, every route's @requires_auth, and — by actually
  registering the blueprint and inspecting `app.url_map` — that the static-route
  rename genuinely produces a non-`.static` endpoint name. No findings. Report file
  written by the orchestrator on the grader's behalf (its own write was correctly
  rejected by the read-only sandbox): .agents/reports/process_templates/security-tenant-audit.md

## perf-guardrails

- Round 1 (2026-08-22): within-budget. Added `/core/flows/create/template-catalog`
  and `/api/core/process-templates` to .agents/perf/budgets.json's measure lists.
  Measured: page 4.8ms/2 queries/68ms LCP, api 8.2ms/4 queries — both comfortably
  inside shared defaults, no custom calibration needed. 0 ceiling breaches. The one
  standing advisory breach (`/api/core/dashboard/summary`, 39 vs pinned 38 queries) is
  pre-existing and unrelated to this diff. Report:
  .agents/reports/perf/2026-08-22-process-templates.md

## test-evaluator (Codex, blocking, two-round circuit breaker)

- Round 1 (2026-08-22): weakened. 7 findings across the unit + e2e suites (wrong
  repo method in AC7, ignored PUT result, service-only AC4 coverage, missing positive
  control in the e2e family filter, advisory tests comparing against the production
  constant they were proving, AC11's `>= 1` permitting duplicate events, AC13 with no
  negative control). All 7 fixed; 37/37 green. Report:
  .agents/reports/process_templates/test-evaluator.md
- Round 2 (2026-08-22): valid. Every fix independently re-verified against the real
  code it claims to match (confirmed `get_process_with_steps` is what the route
  actually calls, confirmed the AC4 fixture ordering is sound, confirmed the literal
  advisory strings match the production constant verbatim). No new issues from the
  round-1 edits themselves. Report:
  .agents/reports/process_templates/test-evaluator-round2.md

## observability

- Round 1 (2026-08-22): instrumented. Added the missing snake_case structlog channel
  (entity_events/EventWriter was already in place from the build step) — one INFO
  state-change log (`process_templates_template_copied`) and reuse of the repo-wide
  generic `access_denied` WARNING log for the tenant-boundary-probe case AC3 guards.
  Two new tests assert both log lines fire, using the same log-capture technique
  test_dilution_calculator.py established. Report:
  .agents/reports/process_templates/observability.md
