## Purchases page (roadmap 8.1d)

Spec `.agents/specs/live-cogs.md` → "The Purchases page"; plan `docs/purchases-page-plan.md`. Stacked on !693.

**Style 1 (Reconcile pairs) chosen 12 Nov.** Styles 2 and 3 are deleted; Style 3's bulk skip / not stock now lives on Style 1 as a checkbox per card.

| Laptop, two selected | Record dialog | Phone |
|---|---|---|
| ![laptop-selected](/uploads/44686ba79610ca510f566043ed199bd7/laptop-selected.png) | ![record-dialog](/uploads/dd9638e9f399dbbd7bbad07ccc7f4e39/record-dialog.png) | ![phone](/uploads/e6f39e1549f912e04ed3d64ba47ca407/phone.png) |

### What it does
Production › Purchases: To record / Recorded / Skipped / Not stock. Each card shows what Xero says on the left and what to do on the right (pre-filled from a rule or last time): Record stock, Already in stock, Not stock, Skip, refunds, review (Keep / Edit amounts / Unlink), undo, "Remember for <payee>", bulk, and **Load earlier purchases** (date range, historical view, back). Without Xero connected it explains how to cost stock with "Total paid" instead.

### Behaviour to be aware of
- Every write carries one idempotency key per logical action, kept for retries: a lost reply can't record twice.
- Amounts are exact 4-dp strings; one blank amount takes the exact rest.
- "Already in stock" asks how much of each lot the purchase paid for.
- Card allocations now carry lot names (for Edit amounts).

### Tests
- `tests/test_costing_purchases_page.py`: page, permissions, nav.
- `tests/e2e/test_costing_purchases_browser.py` (10): double-click and lost-reply saves record once, exact 4-dp and blank-rest amounts, out-of-order loads, errors stay on screen, Xero text as text, boosted re-entry, no-Xero state, bulk with no style switch. 6 failed on the code before the Codex round-1 fixes.

Codex round 1: 9 findings, all fixed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012K4jB79TxztZobCHJU3cVj
