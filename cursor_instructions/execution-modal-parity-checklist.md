# Execution UI parity checklist

Use this when validating execute-step behaviour after changes to **modal/page shells**, **submit**, or any **`execution-*.js`** module. Each row in §A–H is a regression scenario to run manually (or automate later) before merging risky slices.

**Bootstrap / entrypoints:** `app/core/frontend/js/execution-modal.js` — assigns `openExecutionModal`, `submitExecution`; wires globals (`ExecutionModalConfig`, polyfills); **`ExecutionModalSecondary.install`**.

**Orchestration:** `execution-open-step.js` (`ExecutionOpenStep.openExecutionModal`) loads data and delegates rendering.

**Rendering:** `execution-render-docs.js`, `execution-render-prompts.js`, `execution-render-inputs.js`, `execution-render-outputs.js` · **Submit:** `execution-submit.js` · **Secondary flows / inventory refresh:** `execution-modal-secondary.js` · **Doc fullscreen iframe:** `execution-doc-overlay.js` · **Shared helpers:** `execution-shared-utils.js`, `execution-session.js`, `execution-ui-utils.js` (`ExecutionUI`).

**Markup:** `app/core/frontend/shared/execution-modal.html` (included from flows2 / core2). **Styles:** `execution-modal.css`, `batch-start.css`. **Batch page loader:** `execution-step-page.js`.

**Script load order** (see `batch-start.html` / `flows2.html` / `core2.html`): where linked, `execution-ui-utils.js` → `execution-shared-utils.js` → `execution-session.js` → `execution-doc-overlay.js` → `execution-render-docs.js` → `execution-render-prompts.js` → `execution-render-inputs.js` → `execution-render-outputs.js` → `execution-submit.js` → `execution-modal-secondary.js` → `execution-open-step.js` → **`execution-modal.js`** (last).

---

## How users reach the execution UI today

| Surface | Entry behaviour | Notes |
|--------|-------------------|--------|
| **Workflow page (`flows2`)** | `completeCurrentStep` / `startNextStep` **navigate** to `/core/flows/batches/start?execution_id=…&id=…&return_to=…` | Does **not** call `openExecutionModal` in-page; same execute-step UI as batch page. |
| **Core hub (`core2`)** | Calls `openExecutionModal(sourceExecutionId, targetStep, stepDefinition)` **without** `renderMode: 'page'` | True **overlay modal** (scroll lock, dimmed backdrop). |
| **Batch execute-step URL** | Full page + `execution-step-page.js` → `openExecutionModal(..., { renderMode: 'page', … })` | Chrome hidden via CSS; sticky **Record step** calls `submitExecution()`. |

---

## A. Overlay modal path (core2)

Work through on **Core** view where execution is opened from the hub (same patterns as any code path that still calls `openExecutionModal` without page mode).

- [ ] **Open:** Modal appears centered; backdrop visible; page scroll locked.
- [ ] **Title:** `#execute-step-name` matches the step being executed.
- [ ] **Close:** Header ✕ and **Cancel** hide modal and restore body scroll.
- [ ] **Variable inputs:** Inventory picker (cards/dropdown per current UX); quantity + unit behaviour; multiple rows if applicable.
- [ ] **Confirm inputs:** Non-inventory confirmation fields validate and submit.
- [ ] **Compliance / prompts:** Text, number, date, select; required markers enforced on submit.
- [ ] **Evidence prompts:** File staging uploads before complete; required evidence blocks submit when empty.
- [ ] **Outputs:** Variable outputs + fixed outputs collected correctly.
- [ ] **Documentation:** If step has docs, Documentation section shows; links / full-screen doc overlay if used.
- [ ] **Submit:** **Complete Step** runs validation; success closes modal (not page mode), notification, `ExecutionModalConfig.onStepCompleted` runs (inventory/execution refresh as configured).
- [ ] **Draft / create execution:** If this surface ever opens draft (`executionId` null + `processId`), creation-on-submit still works (match current product behaviour).

---

## B. Page / dedicated route (`/core/flows/batches/start`)

Use **flows2 “Next step”** navigation or open the URL directly with valid `execution_id`, `id` (process), optional `return_to`, `draft`, `step_id`.

- [ ] **Shell:** No modal backdrop; content flows in page; hero subtitle updates (`execution-step-page.js`).
- [ ] **Chrome:** Modal header/footer hidden via CSS; sticky **Record step** remains the primary submit.
- [ ] **Submit:** Success does **not** rely on hiding `#execute-step-modal` overlay (page mode); redirect/navigation matches `ExecutionModalConfig` / `returnTo` behaviour.
- [ ] **`return_to`:** Only same-app paths under `/core/flows` (guarded server-side); client fallback in `batch-start.html` still sane.
- [ ] **HTMX / full load:** If testing boosted swaps, `initExecutionStepScreen` / single-flight load still works after navigation.

---

## C. Draft batch (“start new batch” on execute-step)

- [ ] **Context:** `draft` + `step_id` + `process_id`; `openExecutionModal(null, null, stepDefinition, { processId, renderMode: 'page' })`.
- [ ] **Submit:** Creates execution then completes step (`execution-submit.js` draft handling); datasets updated before `completeStep`.
- [ ] **No duplicate phantom state:** Re-opening or refreshing does not duplicate inputs from `_inputStateByKey` leaks.

---

## D. Inventory edge cases

- [ ] **Expired / not-ready / untracked chips** (or warnings): Still visible and block or warn per current rules.
- [ ] **Ready-date confirmation:** Intercepts submit when “not ready” inventory chosen; **Cancel** vs **Use anyway** paths.
- [ ] **Add missing item:** `openAddInventoryModalForMissingInput` opens add-inventory flow; on success `refreshExecutionModalInventory` refreshes pickers.
- [ ] **Refresh after add:** New item appears; selection can be applied; submit enables when all required selections filled.
- [ ] **Page mode visibility:** `refreshExecutionModalInventory` (`execution-modal-secondary.js`) uses **`renderMode === 'page'`** or **`body.batch-start-spa`**, not only `modal.style.display === 'none'`.

---

## E. Evidence

- [ ] **Staging:** Files held in `pendingEvidenceFilesByStepId` until submit uploads.
- [ ] **Existing evidence:** Loaded into UI where applicable; merge with pending on submit.
- [ ] **Validation:** Required evidence sections block submit until satisfied.

---

## F. Secondary modals (shared HTML partial)

- [ ] **Add untracked output:** `add-untracked-output-modal`; form validation (notes required); success closes modal and refreshes execution context / inventory as today.
- [ ] **Ready-date confirm:** `ready-date-confirm-modal`; confirm/cancel wiring.

---

## G. Globals and integrations

- [ ] **`CoreAPI`:** `getExecution`, `getProcess`, `getExecutionWithProcess`, `getInventory`, `getExpiredMaterials`, `getUntrackedItems`, `getStepDocumentation`, `completeStep`, evidence upload helpers — unchanged contracts unless intentionally versioned.
- [ ] **`escapeHtml`, `getCurrentUser`, `showNotification`:** Globals (execution-modal polyfills `showNotification` / `getCurrentUser` if missing); render/submit modules read from `window` where needed.
- [ ] **`ExecutionModalConfig.onStepCompleted`:** Runs after successful step on both modal and page flows.
- [ ] **`execution-ui-utils.js`:** Loaded on **batch-start** and **flows2** before the execution stack; provides **`ExecutionUI`** (`setRenderMode`, `getRenderMode`, `isPageMode`). **core2** does not include this script; modal/page mode still works via `dataset.renderMode` fallbacks in **`execution-open-step.js`** / **`execution-modal.js`**.

---

## H. Browsers / viewport (spot-check)

- [ ] Desktop: modal centered (core2); page layout readable (batch).
- [ ] Mobile: sticky **Record step** usable; picker cards scroll; no trapped focus if you add focus trap later.

---

## Sign-off

| Date | Scope (e.g. “Part 5 renderer — inputs only”) | Tester | Pass / notes |
|------|-----------------------------------------------|--------|----------------|
|      |                                               |        |                |

---

## Automated checks (local)

```bash
# Python guardrails + Node unit tests for tests/js/*.test.js (requires Node 18+ on PATH)
uv run pytest tests/test_execution_modal_frontend_assets.py tests/test_execution_shared_utils_js.py -v

# JS only
node --test tests/js/*.test.js
```

---

## Next refactor parts (reference)

1. ~~Parity checklist (this doc)~~  
2. ~~Extract pure utils → `execution-shared-utils.js`; pytest + `node --test`~~  
3. ~~Picker CSS in `execution-modal.css`; remove JS injector~~  
4. ~~`execution-ui-utils.js` with `ExecutionUI` (modal/page helpers)~~  
5. ~~`refreshExecutionModalInventory` page-embed guard (`pageEmbed` / `batch-start-spa`)~~  
6. ~~Formal session state → `execution-session.js` + `ExecutionSessionAPI` (WeakMap); pytest + node tests~~  
7. ~~Step docs renderer → `execution-render-docs.js` (`ExecutionRenderDocs`)~~  
8. ~~ExecutionRenderer chunks → `execution-render-inputs.js`, `execution-render-prompts.js`, `execution-render-outputs.js`~~  
9. ~~Submit pipeline → `execution-submit.js`~~  
10. ~~Open-step orchestration → `execution-open-step.js` (`ExecutionOpenStep.openExecutionModal`); `execution-modal.js` is bootstrap + submit delegate only~~  
11. ~~Doc fullscreen overlay → `execution-doc-overlay.js` (`openDocFullScreenOverlay`)~~  
12. ~~Cleanup duplicate `shared/execution-modal.js` (removed; HTML partial `execution-modal.html` remains)~~  

The duplicate **`shared/execution-modal.js`** file was deleted; templates never loaded it. **`shared/execution-modal.html`** remains the shared DOM shell.

When a risky slice merges, add a short note under **Sign-off** with what was covered.
