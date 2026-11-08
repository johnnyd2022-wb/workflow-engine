# Take stock out: tastings and events

Founder's question (2026-10-28): "I take 12 bottles of gin to a tasting, sell 7, return 5. Are
we expecting people to only say they took 7, or do we have the return logic as well in case
they want to be by the book?"

Before this change, Tastings could only record **millilitres poured**. Selling bottles at the
event, or bringing unopened bottles back, had no place to go: the honest workaround was to
take out only what you expected to sell, which is exactly what a by-the-book producer
shouldn't have to guess.

## Decisions

- **One flow** for tastings and events (founder, 2026-10-28). An event is a tasting that also
  sells bottles; the editor asks which it is, and the close form adapts.
- **Event sales are recorded both ways** (founder, 2026-10-28): some are invoiced in Xero,
  some are only counted at the end of the day. The close form takes a count and a list of the
  day's Xero lines to tick.

## How it works

Take 12, sell 7, bring 5 back:

| Moment | Stock | Excise |
|---|---|---|
| **Taken out** (dispatch, unchanged) | 12 leave the warehouse into tasting stock | A removal of 12, dated the day they left, owned by the source CCA |
| **Closed**: 7 sold (counted, or Xero lines ticked) | Nothing more leaves the warehouse | Nothing: they were removed when they left |
| **Closed**: 5 brought back | A new lot of 5 at the place they came from, marked *duty paid* with the event it came back from | Listed under returns as "Back from <event>": a possible credit to raise with Customs, never claimed automatically |
| **Later**: 2 of the 5 sold through Xero | The returned lot goes to 3 | Nothing: they were removed when they first left |

- **Poured, sold, back.** Each bottle line closes with mL poured, bottles sold, and unopened
  bottles brought back. Their total can't be more than was taken; what's left (an open
  bottle) stays in tasting stock for the next outing, as before.
- **Xero sales at the event.** The sync matches every invoice line to the oldest warehouse
  batch. An invoice raised at the event would take bottles from the warehouse that are
  actually in the rep's car, and both the event and the sale would be removals. Ticking the
  line at close undoes the warehouse match and records the sale against the event's stock
  instead. Later syncs, manual batch assignment, and voiding the invoice all leave a linked
  line alone.
- **Which lines are offered**: approved or paid sales invoices dated on the event's days, for a
  product the event took as bottles, not already linked to an outing. A line for the event's
  own customer is ticked for you.
- **Pool lines** (mL drawn from earlier tasting stock) can only record mL poured; bottles can
  only be sold or brought back from stock taken as bottles.

## What changed

- Migration `stock_outings_001`:
  - `tastings.kind` (`tasting` | `event`);
  - per line, `sold_units`, `returned_units` and `return_item_id`;
  - `crm_sales_fifo_allocations.tasting_allocation_id`;
  - the one-lot-per-batch-and-place index (`uq_inventory_items_org_name_batch_location`) leaves
    out duty-paid returns, as it already leaves out transfer and material receipts. Bottles back
    from an event keep their batch number, so a recall still finds them, beside the
    duty-suspended lot of the same batch.

  Downgrade refuses while any of these hold data.
- `tasting_service.finalise` takes `sold_units`, `returned_units` and `invoice_lines`. The new
  `invoice_line_choices` backs `GET /api/crm/tastings/<id>/invoice-lines`.
- `SalesTraceabilityService` never re-matches, reassigns or reverses an event-linked line.
- NZ Alcohol excise: event-linked sales and sales from returned lots are not removals; returns
  from outings appear as returns with their event named.
- Tasks → Tasting: the editor asks "Tasting" or "Event or market". The close form has Poured,
  Sold and Brought back per bottle line, a running tally in words ("Took 10 · 6 sold · 4
  back"), and the day's Xero lines to tick. Task cards say "Event" for an event.

## Not in this change

- **Editing or voiding a linked invoice after close** doesn't change the event's sold count.
  The event's record is what the rep counted on the day; the invoice change shows in Xero.
- **The return credit** is listed, not claimed. Whether Customs grants a refund or drawback for
  duty-paid stock coming back into a CCA is a question for Customs (see `source-to-sale-plan`
  2.6e, the variance table's "Came back from a rep or event").
- **Library stock** stays outside this flow, as before.

## Checks

- `tests/test_stock_outings.py`:
  - take ten, sell six, bring four back;
  - returned bottles sold later are not a second removal;
  - a Xero sale at the event comes from event stock, not the warehouse, survives a resync and
    a later edit of the invoice, and refuses manual reassignment;
  - a close that doesn't add up is refused;
  - only live sales on the event's days are offered and linkable;
  - voiding a linked invoice puts nothing back in the warehouse;
  - bottles can only come back from stock taken as bottles;
  - the invoice-lines API is scoped to the organisation;
  - a pour-only tasting still closes as before.
- `tests/e2e/test_tastings_page.py`: an event closes with bottles sold and brought back, on a
  laptop and a phone, with the tally refusing more than was taken.
- Screenshots: the close form at laptop, phone and dark. This refines the Tastings close form
  rather than redesigning a page, so there is one version.
