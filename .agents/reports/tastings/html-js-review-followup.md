# Tastings HTML/JS review follow-up

Date: 2026-10-27. Read-only recheck of F1/F2/F3 from `html-js-review.md`; no source/test/script edits.

- **F1 closed.** The selected warehouse source now stores product, batch and canonical unit on its allocation line. Another stock search can replace the available choices without losing the original line's metadata or fractional quantity step. Changing sources explicitly clears stale metadata before capturing the new source's fields. The real browser regression selects 0.5L, searches another product, checks original name/batch/unit and native validity, adds a second source and proves the successful saved canonical quantity. The supplied pre-fix run failed the native-validity assertion, demonstrating that the test catches the actual defect.
- **F2 closed.** The template's dispatch capability now requires both `sales.record` and `inventory.adjust`, matching the server's cumulative permission checks.
- **F3 closed.** The error border uses `var(--error)`, which exists in the shared `app/core/frontend/css/styles2.css`; the hardcoded accent is removed.

Validation: independently inspected current source and the regression assertions; `node --check app/features/crm/frontend/js/tastings.js` passes. Read the supplied final browser run log `~/.cache/tastings/browser-final7.log`: **20 passed**, three existing/advisory warnings, 34.34s. This log was produced by root's real browser runner, not rerun or represented as this grader's own browser execution. No open finding remains from these three items.

VERDICT: clean
