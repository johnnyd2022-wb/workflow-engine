# Execute-step reconcile — `execution-render-outputs.js`

## Current behaviour

- **`normalizeReconcileId`** — canonical id strings (`''` = no inventory selection).
- **`RECONCILE_NONE_ID`** — named alias for submit/hidden empty id (`''`).
- **Buttons** — **`dataset.untrackedId`** set after innerHTML (`RECONCILE_NONE_ID` or **`idNorm`**).
- **Confirm `uid`** — **`normalizeReconcileId(confirmBtn.dataset.untrackedId ?? rowCard.dataset.untrackedId)`** — `??` preserves **`''`** on the none button (nullish only), avoids redundant **`in`** checks.
- **Fragment** — cards batched with **`DocumentFragment`**.

## Risks / follow-ups

| Area | Note |
|------|------|
| **`innerHTML`** on cards / expand | XSS posture = **`escapeHtml`** on interpolated fields (`.cursor/rules/js-review.mdc`); DOM/`textContent` build is optional hardening. |
| **Button vs row id** | Buttons carry id first; **`??`** falls back to row when unset — keeps one expression without drifting `getAttribute`/`dataset`. |
