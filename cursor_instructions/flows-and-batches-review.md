# Execute-step reconcile UI (`execution-render-outputs.js`)

## Canonical identity (single normalization)

All reconcile ids pass through **`normalizeReconcileId(v)`** (`null`/`undefined`/whitespace-only → **`''`** = none / no selection). Used for:

- **`setReconcileState`** reads/writes
- **`applyReconcileCardVisual`** (`dataset` vs `reconcileState.selectedId`)
- **Click handler** (`uid` vs **`''`**)
- **Index keys** (`reconcileCardById`)
- **Initial selection** — **`defaultIdNorm`** vs **`normalizeReconcileId(id)`** for row CSS (avoids whitespace mismatch with **`defaultId`**)

Hidden input and submit stay **`''`** or trimmed UUID strings (`execution-submit.js`).

There is **no** `__none__` sentinel or map translation layer.

## Delta vs sweep

- **Both** `reconcileCardById[oldSel]` and `[newSel]` present → update those two nodes only.
- **Either missing** → `console.warn` → **full sweep** (correctness over micro-optimisation).

## Remaining tradeoffs (by design)

- **`''` means none** — same as “falsy” id; backend oddities (`"none"`, `"0"`) are **not** remapped (would need an explicit product rule).
- **Index** built once per render; dynamic card injection would require a **reindex** (not used today).
- **Expand HTML** still string-built; security = **`escapeHtml`** everywhere (`.cursor/rules/js-review.mdc`).

The review text that referred to “three normalization sites” is **superseded** if it predates **`normalizeReconcileId`**.
