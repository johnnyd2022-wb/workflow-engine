# TEST-EVALUATOR: compliant-nz-alcohol
date: 2026-08-23
engine: codex (gpt-5.6-sol), read-only sandbox
verdict: mixed

Note: this stage's sandbox correctly rejected its own report write (§5 of
`.agents/verification-chain.md` — a `--sandbox read-only` Codex stage cannot write even
its designated report file). The orchestrator captured its verbatim final message and
transcribed it here; the content below is Codex's own words, not the orchestrator's
analysis.

## Scope graded
1. `tests/e2e/compliant-platform/test_nz_alcohol_framework_applicability.py` (5 new
   tests, written by the e2e-playwright chain stage).
2. `tests/test_compliant_routes.py` — 3 new tests covering `module.py`'s `run_check()`
   (0% coverage before this pass): `test_run_check_is_not_flagged_when_module_not_enrolled`,
   `test_run_check_is_not_flagged_when_no_control_needs_attention`,
   `test_run_check_flags_and_counts_attention_frameworks`.
3. `tests/e2e/compliant-platform/test_alcohol_products_flow.py` — the `abv_percent`
   parametrize list extended with `nan`/`-nan`/`Infinity`, plus a new
   `test_create_alcohol_product_rejects_overlong_customs_product_code`, both proving the
   fixes for security-audit findings F1/F2.

Runtime pytest execution inside the sandbox failed on `host.docker.internal` DNS
resolution (the exact host-shell `ENVIRONMENT=test` trap CLAUDE.md documents — the
Codex stage's own environment set it, unrelated to the tests' validity); the grader
fell back to a standalone Python mutation harness against the pure functions, plus
static reasoning, per its own report below.

## Findings

1. **`test_trade_waste_framework_reflects_selected_council` under-asserts** — it checks
   `source_url`/`version`/`source_title` match the selected council's catalogue entry but
   never asserts `controls`. A mutation that drops the `controls` overlay from
   `framework_for_profile()` (still copying `version`/`source_title`/`source_url`) leaves
   every existing assertion green — confirmed by the grader's harness
   (`drop-controls-overlay: existing-assertions-pass=True`,
   `behavior-broken=True`). The spec's own AC text explicitly includes `controls` in what
   must be bound (`"its source_url/version/controls match that council's catalogue
   entry"` — `.agents/specs/compliant-nz-alcohol.md`), so this is a real gap against the
   AC as written, not just a nice-to-have. Already fixed by commit `6cdbea7`:
   `tests/e2e/compliant-platform/test_nz_alcohol_framework_applicability.py:89-91` now
   asserts `controls` (verified 2026-08-25 by findings-sweep).

2. **`test_run_check_flags_and_counts_attention_frameworks` under-asserts the count** — it
   creates exactly one attention-state framework and asserts the message says "1 ...".
   A regression that hardcodes the message to always say "1" regardless of how many
   frameworks are actually in attention state passes this test unchanged — confirmed by
   the grader's harness (`hardcode-count-one: two-framework-behavior-broken=True`, i.e.
   the hardcoded version's output for a 2-framework case differs from what the real
   pluralized count would say, and the existing 1-framework assertion doesn't catch it).
   Already fixed by commit `6cdbea7`: `tests/test_compliant_routes.py:531-556` now creates
   two failed records across two frameworks and asserts the count is 2 (verified
   2026-08-25 by findings-sweep).

3. **Minor, not a defect**: the audit-pack test
   (`test_build_audit_pack_rejects_a_real_but_inapplicable_framework`) proves the 400
   response but not the AC's "before any database query runs" ordering claim — a
   regression that ran the query first and then rejected would still pass. Not fixed by
   the grader (advisory only, no write access); left to the orchestrator to judge whether
   the ordering claim is worth instrumenting.

4. **Minor, not a defect**: including `"Infinity"` alongside `"nan"`/`"-nan"` in the
   extended `abv_percent` parametrize list is harmless (still correctly 400s) but doesn't
   itself prove the F1 crash regression — `Decimal("0") < Decimal("Infinity") <=
   Decimal("100")` never raised `InvalidOperation` even before the fix (only NaN variants
   do). The `nan`/`-nan` cases do validly reproduce and pin F1. Already handled: not a
   defect, no action needed (reviewed 2026-08-25 by findings-sweep).

5. Explicitly confirmed clean: an `is_finite()` short-circuit alone (without also moving
   the comparison inside the `try`/`except`) is a legitimate, sufficient fix for F1 — the
   tests correctly don't couple to one specific implementation shape of the fix. The
   remaining framework-applicability tests and the two negative `run_check()` tests
   (not-enrolled, no-attention) are honest and falsifiable per the grader's review.

VERDICT: mixed
