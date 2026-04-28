# Execution Step SPA parity checklist

This checklist is used to verify the dedicated **Execution Step SPA page** matches the legacy **Execute Step modal** behavior.

## Entry + routing

- [ ] **Deep link works**: opening the execution step URL directly loads without relying on prior page state.
- [ ] **Back button works**: browser back returns to the prior page (typically flows workspace), without leaving the app in a broken state.
- [ ] **HTMX boosted nav works**: navigating via in-app links loads as fragment swaps (no full page reload) where expected.

## Data loading + context

- [ ] **Execution context**: page loads the target `execution_id`, finds the `ready` step, and uses the correct step definition from the process.
- [ ] **Step name shown**: header displays the correct step name.
- [ ] **Batch/execution metadata**: any visible batch ID / execution identifier matches existing UI expectations.

## Inventory (variable inputs)

- [ ] **Matching inventory list**: inventory options are filtered per input name (same matching logic as modal).
- [ ] **Sort preference**: inventory items associated with the current execution are prioritized (when applicable).
- [ ] **Unit display**: quantity entry unit matches selected inventory unit (and conversion rules match modal behavior).
- [ ] **Validation**:
  - [ ] inventory selection required fields are enforced
  - [ ] quantity is required and \(> 0\)
  - [ ] quantity cannot exceed available inventory quantity
- [ ] **Missing inventory** disables completion and shows an error (same as modal).

## Confirm inputs (no inventory selection)

- [ ] **Required validation**: quantity and unit required inputs are enforced.
- [ ] **UI behavior**: matches modal (errors highlighted, first error scroll/focus where applicable).

## Execution prompts

- [ ] **All prompt types render**: text, number, date, select.
- [ ] **Required prompts validation**: required fields block submit.

## Outputs (confirmation + rules)

- [ ] **Variable outputs**: quantity overrides work and are sent correctly.
- [ ] **Static outputs**: included in payload as per step definition.
- [ ] **Custom expiry rules**:
  - [ ] `fixed_duration` shows warning banner
  - [ ] `set_at_execution` UI renders and validates
  - [ ] warn period is not longer than expiry period (validation matches modal)
- [ ] **Ready date rules**:
  - [ ] `fixed_duration` warning/banner matches modal
  - [ ] `set_at_execution` requires a date and blocks submit when missing
- [ ] **Expiry vs ready-date cross validation**: expiry cannot be before ready date (blocks submit).

## Ready-date consumption override

- [ ] If selected inventory has `output_ready_date` finding:
  - [ ] confirmation modal appears listing the items
  - [ ] Cancel blocks submit
  - [ ] “Use anyway” proceeds and sets `allow_consumption_override` in the request

## Reconciliation / untracked flows

- [ ] Inventory items flagged “Untracked inventory item — reconciliation required” are clearly indicated.
- [ ] Untracked output creation flow works:
  - [ ] open “add untracked output”
  - [ ] save creates item, flags for reconciliation
  - [ ] inventory pickers refresh and can select the new item
- [ ] Reconciliation selection is preserved even when output quantity is empty (regression guard from `execution-modal.js`).

## Submit + post-submit behavior

- [ ] `CoreAPI.completeStep(...)` call succeeds with the same payload shape as modal.
- [ ] Success UX:
  - [ ] a success notification is shown
  - [ ] user is returned to flows workspace (or a clear “Back to workflow” affordance is provided)
- [ ] Flows workspace shows updated state (execution step advanced + inventory updated).

## Non-regressions

- [ ] Modal still works via legacy entrypoint (kept temporarily for safety).
- [ ] No new console errors in page load, submit, or after navigation.

