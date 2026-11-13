# Live cost — polish backlog (after 8.1a–e)

Noted 12 Nov 2026 at the founder's request, for after Whistlebird's first real run through the
Purchases page. Nothing here is a bug; each is something to judge against real use first.
Spec: `.agents/specs/live-cogs.md`. Roadmap: 8.1 in `docs/source-to-sale-plan.md`.

## Purchases page
- **Pre-filled amounts to cents.** Last-time and rule pre-fills are exact to 4 dp, so a row can
  read "277.4221". Round suggestions to cents and let the "rest" (or the remainder line) take
  the difference. Server side in `actions.prefill`; keep the 4-dp exactness for what's saved.
- **"The rest of this purchase" radios** use browser-default styling; give them the house
  segmented-choice look.
- **Payees in rules are stored normalised** ("moore wilson's wellington"). Keep the typed
  casing for display alongside the normalised matcher.
- **Batch cost link.** The lot panel's "Made in a … batch" links to the Batches page, not the
  batch itself; the Batches sheet isn't deep-linkable yet (`?execution=` would fix both).
- **Transfer provenance** names "the lot it came from" but not the site; add the site name.

## Costs page
- Show the latest cost per unit next to each ready product (the batch card has it; the list
  doesn't), so the page answers "what does a bottle cost" without a click.
- An uncosted material with no lot (declared inputs only) could link straight to Add Inventory
  with the name pre-filled.

## Add Inventory
- CSV: the "Total Paid" column could accept a currency symbol and thousands separators the way
  the manual field does.
- The manual form's "= $x per kg" hint could also show when the quantity unit is a pack size.

## Engine / performance (accepted, revisit at scale)
- Readiness walks batch history level by level: two queries per level, for every product at
  once. Fine for Whistlebird's depth (2–3 levels); revisit if products chain through many
  batches. (Codex 8.1e-1 round 3, accepted.)
- `semgrep` exceptions marked `nosemgrep` with reasons: per-document upserts under row locks in
  `purchase_sources`, bulk per-line savepoints, 1,000-lot chunks in `CostEngine.prime`.

## Tests still worth adding (Codex final review, 12 Nov)
Behaviour is fixed; these would pin it:
- Browser: refund picker, existing-lot quantity on "Already in stock", Edit amounts, dialog
  focus/return, historical run and its way back.
- CSV review: rapid double activation of Add (the card locks; no test drives it).
- Barcode add-quantity: two concurrent deliveries with distinct keys both succeed.
- Rules dialog: keyboard focus lands on the matchers after a 409.

---

## Status after polish batch 2 (14 Nov 2026)

**Done** (everything above except what's listed under "Still open"):
- Purchases: cents suggestions that add up (!705); a segmented "rest of this purchase" choice
  (!705); rules keep payees and descriptions as typed (!707).
- Lot panel: "Made in a … batch" opens that batch, finished ones read-only (!708); transfers
  name their site (!705).
- Costs page: latest cost per unit on the list, with its status (!705); declared inputs link to
  Add Inventory with the name filled in (!705); a "How costs are worked out" settings sheet for
  last known price and the litres split (!705); "What you pay for materials" (!702).
- Add Inventory: CSV Total Paid reads `$1,234.50`, `NZ$ 80`, `1 234.50` (!705); the hint
  gives a per-litre / per-kg price when the name carries a pack size (!710).
- Tests: every item in "Tests still worth adding" landed (!706). They found a real bug:
  concurrent barcode deliveries lost stock (5 + 2 + 3 left 7); fixed in !706.
- Engine: an over-budget walk leaves nothing marked in-progress, so later solves never read
  it as a cycle (!700/!705).
- Readiness: once its shared engine budget is spent, each later product's material rows are
  costed on a budget of its own, and a row that ran out of budget is never kept for the next
  product, so a list row reads as its own page does (!MR).
- "Remember this" on an existing rule keeps the payee and description as typed; a rule saved
  before the typed form existed takes the purchase's casing (!MR).
- Costing settings (and the litres-split alcohol profiles) are read once per request:
  `CostEngine.own_budget()` is the one way to get an engine with budgets of its own, and it
  passes on what the first engine read. Readiness, price history, the materials picker and
  margins use it instead of building engines that re-read them (!MR).

## Still open

- **Open question — "Paid for by" on Add Inventory.** The spec names it but never defines it:
  (a) link the stock to the Xero purchase that paid for it, or (b) who paid (the business, or
  the owner personally). Founder (12 Nov 2026): leave it open; hunch is it should be optional,
  with options the org selects. Not built until settled.
- **Multipack reading in the pack-size hint.** "Tonic 24 x 200ml" treats one unit as the whole
  pack of 24. Someone counting single bottles gets a per-litre figure 24× too low. The forms only
  offer units/pieces, so pack-as-unit was the likelier reading; revisit if it misleads.
- **Credit-note tax backfill** runs on each Xero sync, up to 500 older notes a time. Until a
  note is backfilled, a multi-line tax-inclusive credit's revenue is untracked rather than
  guessed. Looked at again on 14 Nov 2026 and left as is, on purpose: the cap is 13 Xero
  requests a sync (batches of 40), so raising it only spends more of the Xero allowance on
  every sync, and the other way to close the gap, splitting a note's GST across its lines,
  is the guess this was written to avoid. It converges on its own (oldest first, and notes
  Xero no longer returns are marked unavailable and not retried). Revisit only if a tenant
  has thousands of old multi-line credits.
