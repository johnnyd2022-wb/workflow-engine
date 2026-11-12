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
