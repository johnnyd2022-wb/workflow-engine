# Batches refactor — findings checklist (by criticality)

Source: `cursor_instructions/batches-refactor.md`  
Work order: top to bottom; `[x]` = implemented or reviewed with resolution.

## Critical — security & data integrity

- [x] **C1** `execution-doc-overlay.js` — iframe: `sandbox` + `referrerPolicy`; remove duplicate overlay; ESC + `popstate` cleanup
- [x] **C2** `execution-render-docs.js` — document preview iframe: `sandbox` + `referrerPolicy` (same-origin app URLs)
- [x] **C3** `execution-modal-secondary.js` — `refreshExecutionModalInventory`: generation token to drop stale in-flight refresh
- [x] **C4** `execution-modal-secondary.js` — `bindUntrackedOutputForm`: prevent duplicate `submit` binding; double-submit guard on untracked form
- [x] **C5** `execution-open-step.js` — open generation: ignore stale async completion when user opens another step quickly
- [x] **C6** `execution-doc-overlay.js` + `execution-render-docs.js` — defense in depth: block `javascript:`/`data:` and **cross-origin** URLs for embedded iframe/img (links still available)

## Performance — scoped fixes

- [x] **P1** `execution-step-spa.js` — inventory picker: **event delegation** instead of attaching new click handlers on every `rerender()` (listener accumulation)

## High — maintainability / correctness (scoped fixes)

- [x] **H1** `execution-shared-utils.js` — log (warn) when `/org/users` fetch fails (empty map is silent today)
- [x] **H2** `execution-render-docs.js` — optional: reduce `summary.innerHTML` static strings — **done** (`createTextNode` + hint spans)

## Medium / architectural (review or defer; document rationale)

- [x] **M1** Global `window.*` / execution context isolation — **partially addressed**: still no ES modules; **AbortSignal** on open-step + refresh cancels in-flight API work when superseded. Full isolation remains a bundler follow-up.
- [x] **M2** `core-api.js` — **AbortSignal** on `request()` / key GETs (`getInventory`, `getExpiredMaterials`, `getUntrackedItems`, `getStepDocumentation`, `listEvidence`, `getEvidenceConfig`, `getMatchingUntracked`, `uploadEvidence`); **AbortError** rethrown without treating as network failure. Retry/caching still **not** implemented.
- [x] **M3** HTML templates — **partial**: shared include `shared/execution_modal_stack_scripts.html` used by `batch-start.html`, `flows2.html`, `core2.html` (single load-order source). Page-specific scripts (e.g. `core.js`, `execution-ui-utils.js`) stay per page.
- [ ] **M4** `batch-start.css` — `!important` / modal-as-page — **still deferred**: large CSS unwind; no change in this pass.
- [x] **M5** `execution-render-prompts.js` — **signal wired**: `listEvidence` / `getEvidenceConfig` use open-step `AbortController`; abort errors propagate. Evidence list click handlers remain per-render (one render per open).
- [x] **M6** `execution-modal-secondary.js` — innerHTML vs `createElement` for cards — **deferred**: inventory labels use `escapeHtml`; full DOM build is large refactor for marginal gain.
- [x] **M7** `execution-render-inputs.js` — `filterAddAnotherDropdown` complexity — **reviewed**: nested loops acceptable for typical dropdown sizes; optimize only if profiling shows pain.

## Tests

- [x] **T1** Pytest: source guards for C1–C5 patterns — `tests/test_batches_refactor_frontend_guards.py`

---

## Findings → files → criticality → notes

| Finding (from audit) | File(s) | Criticality | Resolution / notes |
|---------------------|---------|-------------|---------------------|
| Iframe no sandbox / referrer | `execution-doc-overlay.js` | Critical | Added `sandbox` (same-origin + scripts + popups + downloads), `referrerPolicy`, duplicate overlay removal, ESC + `popstate` teardown |
| Doc preview iframe trust | `execution-render-docs.js` | Critical | Same iframe hardening on inline preview iframe |
| Summary `innerHTML` | `execution-render-docs.js` | High / Medium | Replaced with `createTextNode` + hint elements |
| `refreshExecutionModalInventory` race | `execution-modal-secondary.js` | Critical | `refreshInventoryGeneration` token; abort stale DOM pass after `getInventory` |
| Duplicate submit bind / double submit | `execution-modal-secondary.js` | Critical | `_executionUntrackedFormBound`, `_untrackedSubmitInFlight` + `finally` |
| Stale open / async chain | `execution-open-step.js` | Critical | `openExecutionModalGeneration` + guards after `Promise.all`, prompts, outputs, before `showModal` |
| Untrusted embed URLs | `execution-doc-overlay.js`, `execution-render-docs.js` | Critical | `isSameOriginDocumentUrl`; blocks dangerous schemes + cross-origin **embed** (Open/Download unchanged) |
| Picker listener pile-up | `execution-step-spa.js` | High (perf) | Delegated click on `#exec-spa-cards-*` via `_execSpaPickerDelegate` |
| Silent org users failure | `execution-shared-utils.js` | High | `console.warn` when `/org/users` fails; empty map unchanged |
| Globals / isolation | Many | Medium | Deferred — see M1 |
| core-api retry/cancel | `core-api.js` | Medium | Deferred — see M2 |
| Template duplication | `batch-start.html`, etc. | Medium | Deferred — see M3 |
| batch-start `!important` | `batch-start.css` | Medium | Deferred — see M4 |
| Prompts async/listeners | `execution-render-prompts.js` | Medium | Reviewed — see M5 |
| Card `innerHTML` | `execution-modal-secondary.js` | Medium | Deferred — see M6 |
| filterAddAnother complexity | `execution-render-inputs.js` | Medium | Reviewed — see M7 |

---

## Tests mapped to files

| Test module | Asserts (intent) | Files covered |
|-------------|------------------|---------------|
| `tests/test_batches_refactor_frontend_guards.py` :: `test_execution_security_utils_embed_policy` | Shared embed URL policy, dangerous schemes, origin via `URL(href)` | `execution-security-utils.js` |
| `tests/test_batches_refactor_frontend_guards.py` :: `test_doc_overlay_sandbox_and_teardown` | Overlay teardown helpers, sandbox, referrer, ESC/popstate, delegates to `ExecutionSecurityUtils` | `execution-doc-overlay.js` |
| `test_render_docs_iframe_hardening_and_summary_dom` | Iframe sandbox/referrer, DOM-built summaries, embed same-origin guard | `execution-render-docs.js` |
| `test_execution_step_spa_picker_event_delegation` | Single delegated click handler (no per-rerender listener pile-up) | `execution-step-spa.js` |
| `test_open_step_generation_guard` | Generation counter and stale guards | `execution-open-step.js` |
| `test_modal_secondary_bind_refresh_and_submit_guards` | Refresh token, form bind + in-flight flags | `execution-modal-secondary.js` |
| `test_shared_utils_org_users_warn` | Warn on org users fetch failure | `execution-shared-utils.js` |

**Note:** Guards are string/pattern checks on source so refactors cannot drop protections silently; they do not execute in a browser.

---

## Security & performance — gaps still worth knowing

These were **not** fully closable in one refactor pass; prioritize by risk.

| Area | Status | Why it still matters |
|------|--------|---------------------|
| **`CoreAPI` + `AbortSignal`** | **Addressed** | `fetch` uses `signal`; new open aborts previous `AbortController`; refresh inventory aborts in-flight `getInventory`. |
| **`execution-render-prompts.js`** | **Addressed** (network) | `listEvidence` / `getEvidenceConfig` use the same `signal` as `openExecutionModal`. |
| **`ExecutionSubmit` / modal submit** | **Addressed** | `modal._submitExecutionInFlight` with `try`/`finally` on the full submit path. |
| **Sandboxed iframe + PDF** | Tradeoff | `allow-scripts` + `allow-same-origin` is needed for many PDF viewers; risk is reduced by **same-origin URL enforcement** + server-side doc URLs only. |
| **Globals (`window.*`)** | Open | Partially mitigated by refresh/open generations; true isolation needs architectural change. |
| **SPA picker (`execution-step-spa.js`)** | **Fixed** | Replaced per-card listeners on every rerender with **one delegated** handler on the card container (performance + avoids listener accumulation). |
| **Doc embed URLs** | **Hardened** | **`javascript:` / `data:` / cross-origin** blocked for iframe/img embed; links below still allow explicit user navigation to download/open. |
| **Origin fallback bypass** (code review) | `execution-security-utils.js` | **Fixed** | Central `getPageOrigin()` via `new URL(loc.href).origin`; **fail closed** if `location`/`href` missing — never `resolved.origin === resolved.origin`. |
| **Duplicated URL policy** (code review) | `execution-security-utils.js` | **Fixed** | Single module `ExecutionSecurityUtils.isSameOriginEmbedUrl`; overlay + render-docs call through `urlAllowedForEmbed`. |
