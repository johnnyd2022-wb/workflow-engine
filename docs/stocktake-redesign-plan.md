# Stocktake redesign: three directions

Scope: `/core/stocktake`, reached from Inventory. Three views on one page: home (when the next
count is due, what's open, where stock is), the count, and the reconciliation.
Purpose: **know when the next count is due, count every line, explain every difference, and
show where stock is right now.**

## What is wrong today

Observed in `~/.cache/workflow-engine-ui-shots/stocktake-00-before` (seeded: a finished July
count, today's count with one line matching, one short, one over and one under investigation):

- **Home leads with settings.** The first card is the schedule form (frequency, bulk tolerance, Save), and the Start buttons sit under it. With a count already open, home still offers "Start stocktake" and the open count is one link in a list at the bottom.
- **Tolerance bug.** The bulk-tolerance box is always empty. The API never returned it, so saving a new frequency sent no tolerance and quietly reset a custom one to 0.5%.
- **Nothing reads as a status.** Open differences are underlined text ("-6 L · not resolved"). History is dates and chips with no kind. The batch column of the stock position is all dashes for this data.
- **Count view.** The input takes most of the row and the button is squeezed to "Reco / unt". There is no progress, and no way to see only what is left to count or resolve.
- **Reconciliation on a phone.** Ten columns at 390px print one letter per line.

## What other products do

| Source | How it was read | Pattern | What it changes here |
|---|---|---|---|
| [Unleashed, steps to completing a stock take](https://help-unleashed.theaccessgroup.com/en/articles/15137174-steps-to-completing-a-stock-take-in-unleashed) | Search summary only | A count stays In Progress; count, review variances, recount, and complete only once variances are dealt with, because completing locks it | The open count is home's primary action; Finish appears only when nothing is left to count or resolve (unchanged rule, now visible) |
| [Shopify-based count apps / Shopify POS counts](https://www.shopify.com/blog/how-to-do-inventory-counts-with-shopify-pos) | Search summary only | A progress bar of items counted; uncounted items flagged "Not counted"; scan a product to see if it is counted | Count view gets a progress bar and a "To count" filter; the find box stays scan-first |
| [Lightspeed Retail, inventory counts](https://retail-support.lightspeedhq.com/hc/articles/229129948) | Search summary only | Review the count's changes, then Recount a miscounted item | Recount stays on every counted line, sized so it reads |
| [GOV.UK Design System, task list](https://design-system.service.gov.uk/components/task-list) and [tag](https://design-system.service.gov.uk/components/tag/) | Search summary only | Status as a short adjective tag, never the clickable part; the whole row is the link | Differences and stocktakes become rows: the name links, the state is a tag at the end ("Not resolved", "Investigating until…", "Finished") |
| Linear filter views (third-party guides only) | Search summary only; no official doc found | Saved filters by status over one list | Count view's All / To count / Differences / Done chips |

Research limits: no source was opened and read in full. Searches for craft references on this
shape (Linear's own docs) returned only third-party guides, so no craft source is cited with
confidence; the arrangements follow the house style and the Planner Board.

## Three directions to choose from

| | Style 1: Board | Style 2: Next step | Style 3: Position first |
|---|---|---|---|
| Idea | Four figures (next count, counting now, open differences, on hand), then differences beside stocktakes, then the position | One sentence, then a card saying the one thing to do now with its button | One sentence, then the stock position beside differences and stocktakes |
| Taken from | Planner Board (!522) | Task-list pattern; Unleashed's in-progress-first flow | What an inspector asks for first |
| Best at | Seeing everything at a glance; matches Planner | A first-time user who just needs to know what to press | A visit from Customs |
| Gives up | More on the page | Figures as boxes | Counting is a click further |

All three share:
- the header leads with **Continue stocktake** when a count is open (Start is hidden then; the inspector's count can still start);
- the schedule moves to a card at the foot, with the form behind a disclosure that now shows the saved tolerance;
- differences and history are rows with a status tag;
- the batch column only appears when some lot has a batch;
- the count view has a progress bar, All / To count / Differences / Done filters, and fixed-size count controls;
- on a phone the reconciliation is one labelled card per product and the position rows stack.

## Not in this change

No change to counting, resolving, reconciliation maths, excise drafts or the CSV. One API
addition: `schedule.bulk_tolerance_percent` in `GET /api/core/stocktakes`, so the form can show
and keep it (the bug above).

## Checks

- `tests/test_stocktake.py`: the schedule includes the tolerance (fails on the old code with a KeyError).
- `tests/e2e/source_to_sale/test_stocktake_design.py`:
  - Continue becomes the primary action while a count is open;
  - saving a new frequency keeps the tolerance;
  - the count filters and progress;
  - the reconciliation as labelled cards at 390px;
  - a CONCEPT ONLY group for each style at 390, 1024, 1440 and 1920.
- Existing: the customs stocktake e2e, production layout, boosted navigation, pages render and go-live suites.
- Screenshots: each style at desktop, laptop, tablet, phone, wall and dark; the count at desktop, phone and dark; the differences filter; the schedule open; resolving both differences and finishing; home after finishing.

## Review outcome

Four screenshot passes:

1. **Pass 1.** A batch column of dashes; difference rows squeezing their tag.
2. **Pass 2.** Style 2's header repeated the next-step Continue button.
3. **Pass 3.** At laptop width the three header buttons wrapped onto two rows. Start is now hidden while a count is open.
4. **Pass 4** (including resolving, finishing and the quiet home). No defects found.

Awaiting the pick.
