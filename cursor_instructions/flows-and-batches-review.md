# Execute-step reconcile — `execution-render-outputs.js`

## Behaviour

- **`normalizeReconcileId`** — single string form for comparisons and map keys (`''` = no inventory row).
- **`RECONCILE_NONE_ID`** — named alias for that submit value (still `''` for `hiddenInput` / `execution-submit.js`).
- **`setReconcileState(false, defaultIdNorm)`** — initial state uses the same id as selection styling.
- **Confirm buttons** — **`dataset.untrackedId`** is set after innerHTML on None / inventory confirm buttons (`RECONCILE_NONE_ID` or **`idNorm`**). **Reads use `confirmBtn.dataset` only**, with **row `dataset` fallback** only if the button has no `untrackedId` (defensive).
- **Inventory cards** — **`idNorm = normalizeReconcileId(u.id)`** once per row; **`card.dataset.untrackedId = idNorm`**.
- **Fragment** — cards appended via **`DocumentFragment`** then single insert.

## Review topics

| Topic | Status |
|-------|--------|
| **`innerHTML` / XSS** | Dynamic fields use **`escapeHtml`** where interpolated; full **`createElement`/`textContent`** refactor is optional hardening (`.cursor/rules/js-review.mdc`). |
| **Dual getAttribute vs dataset** | Addressed: **write/read via `dataset`** on confirm buttons. |
| **`''` vs `null` sentinel** | Kept **`''`** to match submit pipeline; switching to **`null`** would need submit boundary changes. |
| **`closest` on confirm** | Still used for **container/row validation**; id comes from **`dataset` on the button**. |
