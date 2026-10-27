# Tastings advisory build review

Scope: `feat/tastings`, current tracked diff and untracked Tastings models, routes, services, migration, template, JS/CSS and tests. Spec: `.agents/specs/tastings.md`. Review performed as an inherited-model subagent fallback, with independent context; no claim of a different engine. The requested `.claude/skills/build-review/SKILL.md` is absent, and a hidden-file search beneath `/home/johnny` found no alternative. This review follows the new-feature and verification-chain read-only grader contract instead. No application, test, script or schema changes made.

## Findings

### P2 — Ambiguous prior-removal rows produce an unhandled server error

`app/features/tastings/services/tasting_service.py:289–299` assumes a destination stock item has at most one earlier out-transfer whose individual quantity covers its entire current balance. Existing `InventoryRepository.move_lot` (`app/core/db/repositories/inventory_repo.py:657–698`) deliberately coalesces repeated moves of the same batch into the same destination item. With two earlier 2-bottle out-transfers and four bottles remaining, dispatch rejects despite the existing four-bottle removal history. Once only one bottle remains, both 2-bottle rows match, and `.one_or_none()` raises `MultipleResultsFound`. Neither the HTTP `_write` boundary nor the service error handler catches it, so an ordinary historical stock pattern returns 500 instead of a reviewable validation error.

Reproduced against **only `workflow-engine-test_tastings_build`**, inside an outer transaction rolled back afterward: two actual `InventoryRepository.move_lot` calls returned the same destination UUID; balance 4 yielded `TastingError("Stock outside the licensed area needs attributable prior-removal evidence")`; balance 1 yielded `MultipleResultsFound("Multiple rows were found when one or none was required")`. No committed probe data or schema change remains. Ambiguous attribution may reasonably be rejected in v1, but it must produce a clear 4xx and no debit. Do not pick an arbitrary first row or silently create a second duty event. Add regression coverage for coalesced prior removals.

### P2 — Searching stock removes the rep and customer choices needed to save

`app/features/crm/frontend/js/tastings.js:193–200` sends the product search term to the shared choices endpoint and replaces **all three** option sets from the result. The endpoint filters rep email and customer name by that same term (`app/features/tastings/routes/tasting_routes.py:90–113`). Open a new event, search for a product before choosing the rep, and the rep list typically becomes empty because no rep email contains the product name; Rep remains required. Customer choices disappear as well. “More stock choices” also replaces rep/customer choices with the next offset rather than appending or preserving them. This is an actual ordinary ordering of the booking flow, not a hostile-input case.

Keep stock search/pagination independent from people/customer choice state, and expose usable bounded people/customer search or pagination rather than coupling them to the product term. Test the stock-first booking order and verify the chosen rep/customer survive stock searches and pagination.

### P2 — Completing a tasting silently destroys its planning notes

`app/features/tastings/services/tasting_service.py:573` turns omitted optional outcome notes into an empty string; line 610 then replaces the only `event.notes` field. The UI renders existing plan notes but initializes the separately labelled optional outcome textarea blank (`app/features/crm/frontend/js/tastings.js:226,263–265`). Therefore the standard completion flow removes the venue/rep instructions even when the user leaves the optional outcome notes untouched. Supplying outcome notes also overwrites those instructions. Finalised events cannot subsequently be edited, so the normal event detail permanently loses the planning information.

Reproduced in the same rolled-back scratch transaction: a plan with `notes="Brand sampling"` was dispatched, then finalised with valid usage and no notes key; the event's notes became `''`. Preserve planning notes and outcome notes separately, or append attributable outcome content without losing the original. Ensure idempotent replay still compares canonical outcome input rather than an already-appended note, and test both blank and nonblank outcome notes.

## Boundaries checked

- Generic CRM PUT/DELETE reach `CRMTaskRepository.update/delete`, which inspect the actual `task.tasting` relationship before mutation; Core CRM lane assignment also rejects linked tasks. No ordinary generic-task bypass found in those paths.
- Routes have explicit org-scoped reads and existing `sales.view`/`sales.record` policy entries; dispatch adds `inventory.adjust`. The Tastings blueprint is registered within successful enabled CRM setup, so the suspected global CRM feature-flag bypass is not present.
- Warehouse dispatch, pool reservation/finalisation/cancellation, immutable snapshot adapters, late adjustment propagation and source-CCA observations were read. The modern register deliberately remains incomplete, matching the spec; no claim of filing/payment is introduced.
- Visual judgement and final screenshot completeness remain the root's page-design stage. No screenshots were graded by this code review. Existing full-suite results were not rerun or claimed as this review's evidence.

VERDICT: findings-open
