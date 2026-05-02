# Execute-step reconcile UI — `execution-render-outputs.js`

## Implemented model (single canonical id)

- **`''` (after trim) = no inventory row** — same value in `reconcileState.selectedId`, hidden input, and submit (`execution-submit.js`).
- **Non-empty string = untracked id** — `data-untracked-id` on cards uses the same trimmed string as the map key.
- **No `__none__` sentinel** — removed the translation layer (`reconcileMapKeyFromStateSel` / `reconcileCardMatchesSelection`); selection is **`cardId === stateId`** with both sides `.trim()`.
- **None row** — `data-untracked-id=""` (empty). Only one such row; duplicate `''` keys are rejected at index time (first wins, second logs + skips).

## Update paths

- **Delta** (lock unchanged, selection changed): look up `reconcileCardById[oldSel]` and `[newSel]`; if **both** exist, apply visuals to those two nodes only.
- **Fallback**: if either lookup is missing → **`console.warn`** with context → **`sweepAllReconcileCards()`** so the UI never stays half-updated silently.
- **Sweep**: bootstrap and **`locked` change** → full pass over the map (elements guarded).

## Index build

- Keys: **`String(dataset.untrackedId).trim()`** — duplicate keys skip assignment + warn (`'(none)'` in message for empty).

## Remaining risks

- Imperative UI / index rebuilt once per render (no dynamic card injection today).
- Expand HTML still string-built; XSS boundary = **`escapeHtml`** (see `.cursor/rules/js-review.mdc`).
