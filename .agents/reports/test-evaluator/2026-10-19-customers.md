# Customers independent review — 2026-10-19

Scope: new tests/e2e/test_customers_design.py (four behavior cases + twelve temporary responsive concept cases); customers template, script and CSS against d1890a70. Existing tests unchanged.

Static tests: valid. Exact row lists/URLs/mailto/tel, server filters/order, 503 recovery versus empty, page2 query and boundary state, all three layouts at four widths, overlap/overflow, preview content and dark header contrast make falsifiable claims. No broadening, skips, xfails, tautologies or assertions removed. Pagination's mock deliberately isolates the UI query and rendering; existing CRM API tests cover server behavior.

Mutation sample in separate disposable worktree: replace customer-name links with /crm/customers/broken. Keyboard/link case fails at expected exact customer href (1 failed in9.84s). Restore original links: 1 passed in3.43s. Mutation reversed; disposable worktree removed. Author's worktree never mutated. No auth/tenant/money implementation changes in this batch.

HTML/JS: safe x-text bindings, encoded record URLs, existing permission guards and CRMAPI calls preserved, no sensitive browser storage. Content-local deferred script and scoped CSS serve boosted navigation. Form bindings retain blank address initialization and existing Xero errors.

Findings sent to author and resolved: (1) closing Desk preview leaves empty grid column and hidden contact columns; (2) resizing open Desk to phone needs focus transfer when region becomes modal. Resolved with data-preview-open gating all Desk layout rules and resizePreview focus transfer on the region-to-modal transition. Added two close-width cases and one resize-focus case went red before fixes. Three further cases check persisted URL style and real filtering after a boosted return. The test waits for initial network activity before typing; all search-result assertions remain. Removed redundant explicit x-init because Alpine invokes init automatically. No code or tests edited by reviewer.

Verdict: valid for all22 new cases. Final static HTML/JS/CSS review: clean. No existing assertions changed. Runtime suite results are the author’s separate verification, not inferred from this grade.
