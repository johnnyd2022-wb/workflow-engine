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
