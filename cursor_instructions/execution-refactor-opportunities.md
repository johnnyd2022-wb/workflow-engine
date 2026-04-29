# Execution / batches area — follow-on refactor opportunities

Companion to `batches-refactor-checklist.md` and the merge review in `batches-refactor.md`.  
Items below are **optional**; the current stack is merge-safe. Order reflects **sensible sequencing** (dependencies, risk, leverage).

---

## How to read each item

- **Where it lives** — primary code or documentation touchpoints.
- **What it achieves** — security, performance, and/or ease of reasoning.
- **When** — recommended position in the sequence (1 = first).

---

### 1. Harden and document server trust for process documents

**Order: 1** (highest security leverage; client work is already defense in depth)

| | |
|---|---|
| **Where it lives** | Backend: `app/core/backend/process_docs/` — e.g. `process_docs_routes.py` (download/view), `process_docs_service.py` (`get_file_for_download`, listing by step). Frontend: URLs built via `CoreAPI.getProcessDocViewUrl` / `getProcessDocDownloadUrl` in `app/core/frontend/js/core-api.js`; consumers `execution-render-docs.js`, `execution-doc-overlay.js`. |
| **What it achieves** | **Security / audits:** Authoritative org scoping, step/process binding, and MIME handling live on the server (today much of this exists; the opportunity is **explicit policy review**, tests, and maybe **short-lived signed URLs** for embed if you ever expose docs cross-origin). **Reasoning:** One documented “trust boundary” diagram: browser embed policy vs API guarantees. |
| **Notes** | Client `ExecutionSecurityUtils` stays; backend is the source of truth. Do this before investing heavily in CSP on doc routes alone. |

---

### 2. Introduce a single execution “session” / context object

**Order: 2** (clarifies mental model before more caching/cancellation logic)

| | |
|---|---|
| **Where it lives** | Orchestration: `app/core/frontend/js/execution-open-step.js`. Consumers: `execution-render-prompts.js`, `execution-render-inputs.js`, `execution-render-outputs.js`, `execution-modal-secondary.js` (over time). Optional: `execution-step-spa.js` for parity. |
| **What it achieves** | **Reasoning:** One object carrying `openGeneration`, `AbortController` / `signal`, `executionId`, `executionStepId`, `processId` instead of inferring from `modal.dataset` + globals only. **Correctness:** Fewer ad hoc reads of `window.*` and clearer invalidation rules. |
| **Notes** | Can be a plain object + JSDoc; no need for a framework. Pair with a one-page `cursor_instructions/execution-context-contract.md` when you define it. |

---

### 3. Bounded cache + invalidation for hot read APIs (inventory first)

**Order: 3** (after (2) so cache keys and invalidation hook to a clear “session” or user action)

| | |
|---|---|
| **Where it lives** | `app/core/frontend/js/core-api.js` (optional `CoreAPI` cache layer) or a tiny `app/core/frontend/js/execution-data-cache.js` used by `execution-open-step.js` and `execution-modal-secondary.js` (`refreshExecutionModalInventory`). Backend unchanged unless you add ETag/Cache-Control. |
| **What it achieves** | **Performance:** Less duplicate `getInventory` / related GETs when opening steps in quick succession. **Reasoning:** Explicit TTL and invalidation (e.g. after step complete, after refresh inventory, on logout) so staleness is predictable. |
| **Notes** | Avoid blanket “cache forever”; pair invalidation with submit success and manual refresh paths. |

---

### 4. Retry / backoff for idempotent GETs only in CoreAPI

**Order: 4** (orthogonal to cache; implement with clear separation from POST/complete)

| | |
|---|---|
| **Where it lives** | `app/core/frontend/js/core-api.js` — `request()` or a wrapper used only by safe GET helpers. |
| **What it achieves** | **Performance / UX:** Fewer visible failures on flaky networks. **Reasoning:** Mutations (`completeStep`, uploads) stay strict (no silent retry without idempotency keys). |
| **Notes** | Cap retries and document which endpoints are eligible. |

---

### 5. Single bundler entry or import map for the execution script stack

**Order: 5** (reduces load-order class of bugs; can follow after (2)–(3) clarify boundaries)

| | |
|---|---|
| **Where it lives** | Build config (if added), or `app/core/frontend/shared/execution_modal_stack_scripts.html` (today’s single include) → evolve to one rolled bundle. Touch pages: `batch-start.html`, `flows2.html`, `core2.html` and any other includers of the stack. |
| **What it achieves** | **Reasoning:** Dependency graph enforces order. **Security / ops:** One artifact to version and subresource-integrity if you go that far. |
| **Notes** | `execution-modal.js` already throws if `ExecutionSecurityUtils` is missing; a bundle makes that structurally harder to break. |

---

### 6. Tighten Content-Security-Policy (incremental)

**Order: 6** (large touch surface; do after server doc policy (1) and when inline scripts are understood)

| | |
|---|---|
| **Where it lives** | App shell / Flask (or reverse proxy) CSP headers; templates with inline script in `app/core/frontend/`. |
| **What it achieves** | **Security:** Smaller XSS blast radius when combined with nonces or strict `script-src`. |
| **Notes** | Requires inventory of inline handlers and CDN scripts; often paired with (5). |

---

### 7. Unwind `!important` in `batch-start.css` (execute-step SPA)

**Order: 7** (pure maintainability/perf of CSS; needs visual QA)

| | |
|---|---|
| **Where it lives** | `app/core/frontend/css/batch-start.css` (or path used in `base_spa.html`); test on `batch-start` and any HTMX swap that includes execute-step. |
| **What it achieves** | **Reasoning / performance:** Fewer specificity wars, easier theming, slightly less override churn. |
| **Notes** | Do with before/after screenshots or a short visual checklist. |

---

## Lower priority (track but don’t block)

| Topic | Where it lives | What it would achieve |
|--------|----------------|------------------------|
| **Card `innerHTML` → DOM APIs** in inventory refresh | `execution-modal-secondary.js` | Marginal XSS hardening if `escapeHtml` regresses; high churn for small gain. |
| **Explicit picker teardown** on SPA route change | `execution-step-spa.js` | Defensive if profiling shows retained nodes; current `root.innerHTML` reset already drops most listeners. |
| **Deeper `signal` in every renderer internal** | `execution-render-inputs.js`, etc. | Finer abort granularity; diminish returns after `throwIfAborted` in prompts. |

---

## Suggested tackle order (summary)

1. Server process-doc / download **policy + tests** (security, clarity).  
2. **Execution context** object from open-step (reasoning, future cache/abort).  
3. **Inventory (and related) cache** with invalidation (performance).  
4. **GET-only retry** in CoreAPI (reliability).  
5. **Bundle / import map** for execution stack (reasoning, load safety).  
6. **CSP** hardening (security, coordinated with templates).  
7. **`batch-start.css` `!important` unwind** (maintainability, with QA).

This file can be updated as items are completed or re-prioritized.
