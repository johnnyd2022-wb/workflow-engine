# Purchases page (live-cogs 8.1d) — plan

**What the page must answer:** "What did I buy that isn't in stock yet, and what is it?" — one
card per Xero purchase line, the next step obvious (record it, link it, not stock, skip).

## What other products do

| Pattern | Source | What it changes here |
| --- | --- | --- |
| Statement line left, proposed match right, one **OK** | Xero bank reconciliation (third-party guides; Xero's own help didn't surface) | Style 1: the card is a pair; a rule-prefilled card's primary button reads **OK** |
| "For review" list with checkboxes and a batch Accept; rules apply automatically | QuickBooks Online bank feed (Intuit help) | Style 3: review table + batch bar (skip / not stock) |
| One item at a time, single-key accept / decline / snooze | Linear Triage (Linear docs) | Style 2: one card, keys 1 / 2 / 3, ← → to move |
| Batch bar appears above the table once a row is selected; Cancel at the end; announce it | Carbon data table, Agriculture design system, Carbon a11y issue #5242 | Style 3's bar: count, actions, Cancel; `role="region"` with a label |

Not found: a production/inventory tool that turns bank-feed lines into stock receipts — the
nearest are accounting reconcilers, which stop at the ledger.

## Three directions

| | Style 1: Reconcile pairs | Style 2: One at a time | Style 3: Review table |
|---|---|---|---|
| Idea | Each card: what Xero says ← → what to do | One purchase fills the screen; keys act | Dense rows, select many, batch bar |
| Taken from | Xero reconciliation | Linear Triage | QuickBooks "For review", Carbon batch actions |
| Best at | A normal week at a laptop | Clearing a backlog fast | A big historical run of small purchases |
| Gives up | Fewer per screen | No overview, no bulk | Less room for the "last time" suggestion; no "Already in stock" in the row |

All three share: the tabs (To record / Recorded / Skipped / Not stock with counts), the record
dialog (pre-filled from a rule or last time, rows, "the rest isn't stock / record later"), the
link and refund pickers, review keep/unlink, undo toasts, and "Remember for <payee>".

## Chosen: Style 1 (Reconcile pairs) — 12 Nov 2026

The founder picked Style 1. The others lost on:
- **Style 2 (one at a time):** fast for a long queue, but hides everything else, and the keyboard
  flow didn't fit the phone-at-the-bench use.
- **Style 3 (review table):** dense, but cramped the proposal and actions at laptop width. Its
  one strength, bulk skip / not stock, now lives in Style 1 as a checkbox on each card.

## Not in this change

No API change. Home card and notifications (8.1d notice), purchase-rules settings UI, historical
run UI (API exists), and showing what a recorded purchase became on its card — follow-ups.

## Checks

`tests/test_costing_purchases_page.py` (served, gated, nav link); screenshot scenarios for
desktop / laptop / phone / dark × 3 styles, tabs, record and link dialogs, a full record, a
bulk selection.
