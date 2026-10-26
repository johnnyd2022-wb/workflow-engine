# Tastings HTML and JS review

Date: 2026-10-27. Read-only serial stages: HTML/Jinja/CSS review first, then JS review, following `.claude/skills/html-review/SKILL.md` and `.claude/skills/js-review/SKILL.md`. Reviewed final Tastings template/CSS/JS and the changed `tasks-calendar.js` handlers. No source changes made.

## Findings

- **F1 P2 — Stock searches lose the canonical unit of previously selected new lines.** `app/features/crm/frontend/js/tastings.js:184–188,199` stores only source ID and quantity on a newly selected line, then replaces the stock choices during another product search. When the original source is no longer in the result set, its label falls back to “Selected stock” and its unit to “units”, forcing whole-number HTML validation (`step=1`). A valid 0.5-litre line becomes invalid simply by searching for a second product. Existing edited allocations retain backend `unit`, so the bug specifically affects new lines. Reproduced by executing the actual extracted `renderLines` function with minimal DOM nodes: before search, `Quantity · l`, quantity0.5, step0.0001; after replacing stock results with another product, `Quantity · units`, quantity0.5, step1. Preserve chosen source display/unit metadata independently from the current search result page, and prove a fractional volume line remains valid after another search.

- **F2 P3 — Dispatch affordance does not require both backend permissions.** `app/features/tastings/frontend/templates/tastings/index.html:9` sets `data-can-dispatch` using only `inventory.adjust`. A custom role with `sales.view` plus `inventory.adjust`, but no `sales.record`, can read a planned event and sees the dispatch form (`tastings.js:265`) even though the endpoint policy correctly denies the POST403. Compute this UI capability from both write permissions, matching the server. This is a confusing denied action, not an authorization bypass.

- **F3 P3 — Error accent bypasses the shared theme token.** `app/features/crm/frontend/css/tastings.css:69` hardcodes `#c06a46` for the error border, contrary to the HTML skill's design-token rule. Use the existing error/danger token. The translucent dialog backdrop is an overlay rather than a semantic status colour; no issue raised for it.

## Checks that passed

- Page extends the shared SPA shell; no duplicated shell, unsafe Jinja output, sensitive hidden attributes, or incorrect HTMX target. Workspace header/cards follow the surrounding workspace implementation; native `dialog.showModal()` supplies dialog semantics and modal focus behavior, with named headings and labelled controls.
- CSS is scoped to Tastings selectors; responsive/dark token usage, native labels, focus outlines and reduced-motion handling were inspected. Root's screenshot inspection and 19 browser tests twice were supplied evidence, not claimed as my independent screenshot review.
- Non-Core API wrapper supplies CSRF, same-origin credentials, bounded/encoded query values, visible mutation errors and a root AbortController. No user-controlled HTML injection or sensitive storage found; localStorage stores only the design preference. People and stock searches remain independent after the previous fix.
- Root initialization uses a DOM property rather than a serialized dataset marker; global lifecycle listeners bind once and reference the current initializer. Boosted swap aborts requests; history restoration can reinitialize a fresh restored root. Source node guards and visible loading/error states are present.
- Main search filters the bounded in-memory list without network traffic, so network debouncing is unnecessary there. Server searches require an explicit button/Enter, with request tokens to discard superseded results. Nodes are predominantly built in detached containers; no layout-reading loop was found that would justify speculative DOM batching changes.
- Tasting task edit/done/delete actions route back to the tasting; dragging is suppressed. Backend lifecycle and permission checks remain authoritative.
- `node --check` passes for both changed JS files.

VERDICT: findings-open
