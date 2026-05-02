# Execute-step reconcile — `execution-render-outputs.js`

## Design (current)

- **`normalizeReconcileId(v)`** — single canonical string (whitespace-only → `''`).
- **`RECONCILE_NONE_ID`** — name for submit/hidden “no row” value (still `''`, shared with `execution-submit.js`).
- **Initial state** — `setReconcileState(false, defaultIdNorm)` so the same normalized id is used for CSS and state.
- **Confirm clicks** — read **`data-untracked-id` on the button** first (`getAttribute`); only fall back to the row if the attribute is missing. Mirrors card id without relying on `closest` for the id (row still used for `contains` checks).
- **Buttons** — after building None / inventory cards, **set `data-untracked-id` on `.exec-reconcile-confirm-btn`** to `RECONCILE_NONE_ID` or **`idNorm`**.
- **Inventory rows** — **`idNorm = normalizeReconcileId(u.id)`** once; **`dataset.untrackedId`** stores **`idNorm`**.
- **Delta / sweep** — unchanged; missing map entries → warn → full sweep.

## Security note (from review)

**Expand/card `innerHTML`** still relies on **`escapeHtml`** for interpolated fields — aligns with `.cursor/rules/js-review.mdc`. Replacing with **`createElement` / `textContent`** would be a larger follow-up, not a drive-by change.

## Performance note

Confirm path avoids extra **`closest`** only for **reading the untracked id** (attribute on the clicked button). **`closest`** remains for **Details** / structural checks where needed.

## Lifecycle

**`reconcileCardById`** is a fresh object each render of this block; no stale map across renders unless the caller duplicates DOM without re-running this code path.
