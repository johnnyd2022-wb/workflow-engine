# Batches refactor — findings checklist (by criticality)

Source: `cursor_instructions/batches-refactor.md`  
Work order: top to bottom; `[x]` = implemented or reviewed with resolution.

## Critical — security & data integrity

- [x] **C1** `execution-doc-overlay.js` — iframe: `sandbox` + `referrerPolicy`; remove duplicate overlay; ESC + `popstate` cleanup
- [x] **C2** `execution-render-docs.js` — document preview iframe: `sandbox` + `referrerPolicy` (same-origin app URLs)
- [x] **C3** `execution-modal-secondary.js` — `refreshExecutionModalInventory`: generation token to drop stale in-flight refresh
- [x] **C4** `execution-modal-secondary.js` — `bindUntrackedOutputForm`: prevent duplicate `submit` binding; double-submit guard on untracked form
- [x] **C5** `execution-open-step.js` — open generation: ignore stale async completion when user opens another step quickly

## High — maintainability / correctness (scoped fixes)

- [x] **H1** `execution-shared-utils.js` — log (warn) when `/org/users` fetch fails (empty map is silent today)
- [x] **H2** `execution-render-docs.js` — optional: reduce `summary.innerHTML` static strings — **done** (`createTextNode` + hint spans)

## Medium / architectural (review or defer; document rationale)

- [x] **M1** Global `window.*` / execution context isolation — **deferred**: moving off globals requires bundler/module graph and touch many templates; incremental guards (C3–C5) reduce worst races.
- [x] **M2** `core-api.js` — retry, cancellation, caching — **deferred**: cross-cutting API layer; should be a dedicated initiative with AbortSignal propagation.
- [x] **M3** HTML templates — duplicate script stacks, load order — **deferred**: needs single entry/build or import maps; duplicate bind mitigated for untracked form (C4).
- [x] **M4** `batch-start.css` — `!important` / modal-as-page — **deferred**: unwinding risks regressions in SPA vs modal; tracked as tech debt.
- [x] **M5** `execution-render-prompts.js` — async races / listener accumulation — **reviewed**: open-step generation (C5) prevents stale full orchestration; prompts module would still benefit from render-scoped abort in a follow-up.
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
| `tests/test_batches_refactor_frontend_guards.py` :: `test_doc_overlay_sandbox_and_teardown` | Overlay teardown helpers, sandbox, referrer, ESC/popstate | `execution-doc-overlay.js` |
| `test_render_docs_iframe_hardening_and_summary_dom` | Iframe sandbox/referrer, DOM-built summaries | `execution-render-docs.js` |
| `test_open_step_generation_guard` | Generation counter and stale guards | `execution-open-step.js` |
| `test_modal_secondary_bind_refresh_and_submit_guards` | Refresh token, form bind + in-flight flags | `execution-modal-secondary.js` |
| `test_shared_utils_org_users_warn` | Warn on org users fetch failure | `execution-shared-utils.js` |

**Note:** Guards are string/pattern checks on source so refactors cannot drop protections silently; they do not execute in a browser.
