# Customers independent review — 2026-10-19

Scope: new tests/e2e/test_customers_design.py (four behavior cases + twelve temporary responsive concept cases); customers template, script and CSS against d1890a70. Existing tests unchanged.

Static tests: valid. Exact row lists/URLs/mailto/tel, server filters/order, 503 recovery versus empty, page2 query and boundary state, all three layouts at four widths, overlap/overflow, preview content and dark header contrast make falsifiable claims. No broadening, skips, xfails, tautologies or assertions removed. Pagination's mock deliberately isolates the UI query and rendering; existing CRM API tests cover server behavior.

Mutation sample in separate disposable worktree: replace customer-name links with /crm/customers/broken. Keyboard/link case fails at expected exact customer href (1 failed in9.84s). Restore original links: 1 passed in3.43s. Mutation reversed; disposable worktree removed. Author's worktree never mutated. No auth/tenant/money implementation changes in this batch.

HTML/JS: safe x-text bindings, encoded record URLs, existing permission guards and CRMAPI calls preserved, no sensitive browser storage. Content-local deferred script and scoped CSS serve boosted navigation. Form bindings retain blank address initialization and existing Xero errors.

Findings sent to author and resolved: (1) closing Desk preview leaves empty grid column and hidden contact columns; (2) resizing open Desk to phone needs focus transfer when region becomes modal. Resolved with data-preview-open gating all Desk layout rules and resizePreview focus transfer on the region-to-modal transition. Added two close-width cases and one resize-focus case went red before fixes. Three further cases check persisted URL style and real filtering after a boosted return. The test waits for initial network activity before typing; all search-result assertions remain. Removed redundant explicit x-init because Alpine invokes init automatically. No code or tests edited by reviewer.

Verdict: valid for all22 new cases. Final static HTML/JS/CSS review: clean. No existing assertions changed. Runtime suite results are the author’s separate verification, not inferred from this grade.

## Directory selection independent review — 2026-10-19

Scope: selection cleanup relative to dd934a79; app template/JS/CSS and tests/e2e/test_customers_design.py. Reviewer made no edits in the author worktree.

Static: four behavioral cases unchanged. Twelve temporary layout cases become four Directory cases preserving customer rows, contact visibility, no overlap, drawer content/open/close and 4.5:1 dark-header contrast. Old ?style=2 and stored Style3 no longer change layout. Three Desk-only cases retire with the removed region/resize behavior. Three concept round-trip cases become one actual Directory navigation/search test, retaining exact one-result filtering. These are intentional removals of retired behavior, not weakened regression assertions.

Mutation sample: in separate disposable checkout force #customers-page min-width1100px at390px. Initial document-only overflow assertion escaped it (1 passed6.94s), exposing a real test validity gap. Author strengthened all four cases with the actual #page-content scroller assertion while retaining the document assertion. Verified mutation now fails at that added assertion (1 failed7.25s); restore exact CSS: 1 passed8.19s. One intermediate attempt restored CSS too early and is discarded; only *-verified logs support the final red/green claim. Author production source never mutated. Scratch mutation reversed and disposable worktree removed.

HTML/JS/CSS: losing DOM and selectors removed, shared visually-hidden labels retained, preview stays a modal drawer at every width with focus trapping/restoration. Encoded URLs, safe x-text, permission gates and existing customer/Xero APIs/forms remain. No further cleanup findings.

verdict: valid
