# Product workflows redesign: three directions

Scope: `/core/processes`, the page behind the Production section's Workflows tab.
Purpose: **find a product workflow and open it, see which are in production, and create a new one.**
The workflow editor is a separate change (!521).

## What is wrong today

Observed in the seeded screenshots (`~/.cache/workflow-engine-ui-shots/pw-00-before`, 1440, 390 and dark):

- Every row reads "v4 · 2 runs · 0% success" for a workflow whose two batches are simply
  still under way. The percentage counts unfinished batches as failures, so healthy
  production looks like a product that never works.
- A row's state is three numbers ("3 steps · 2 active · 0 completed"), not a word. Nothing
  says which workflows are running without reading every row.
- Rows are in no useful order; a workflow with three batches under way can sit below an idle one.
- "Create product workflow" is a pale button; sibling pages have one solid primary action.
- The search box carries its own label and runs the full width of the card for a product name.
- A decorative icon leads every row, and "History" is an outlined button on each.
- A failed load says "Failed to load products." inside the loading placeholder, with no way to retry.

## What other products do

| Source | How it was read | Pattern | What it changes here |
|---|---|---|---|
| [Katana, Make screen schedule](https://support.katanamrp.com/en/articles/5914378-using-the-make-screen-schedule) | Page read | Production status is a named state per row ("Not started", "Work in progress", "Done") | Each workflow shows a state in words: "3 under way", "Not running", "Draft" |
| [Zapier, managing Zaps](https://help.zapier.com/hc/en-us/articles/8496182140941) | Search summary only | A table of assets with name, status and last-modified columns, sortable; run outcomes live on a separate history page | Style 3 is a register with a column per fact; run history stays behind History, and the success figure leaves the row |
| [Odoo, bills of materials](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/basic_setup/bill_configuration.html) | Search summary only | The product is the record; its recipe and operations are one click from it | Style 2 is a catalogue of one card per product |
| [Tulip, app design](https://support.tulip.co/docs/app-design-best-practices) | Search summary only | Consistent layouts and colour used only to carry meaning cut training time | The accent marks running workflows and nothing else |
| [Carbon, lists and data tables](https://carbondesignsystem.com/components/data-table/usage/) | Search summary only | A simple related set suits a list; several columns suit a table; the toolbar holds search and the primary action | Style 1 keeps a list; Style 3 uses columns; search is sized for a name |
| [Carbon, empty states](https://carbondesignsystem.com/patterns/empty-states-pattern/) | Search summary only | An empty state says what to do next | No workflows shows one sentence and a create button |

Research limits: only the Katana article was opened and read. The rest are search-result
summaries of the linked pages. No source compares these layouts in use; the arrangements
are design judgement. I looked for a manufacturing product that lists recipes with live
batch counts beside them and did not find one documented.

## Three directions to choose from

| | Style 1: Board | Style 2: Catalogue | Style 3: Register |
|---|---|---|---|
| Idea | Figures beside what is in production now, then every workflow one per line | One sentence, then a card per product | One sentence, then a table with a column per fact |
| Taken from | Production board (!515) | Odoo product records | Zapier asset list, Carbon data table |
| Best at | Matching Home and Production; seeing production at a glance | A handful of products, recognised by name | Many workflows, compared down a column |
| Gives up | The list starts lower on the page | Rows of cards take more height as the range grows | Figures as boxes; needs width (falls back to two lines on a phone) |

All three share: the sibling page header with **Create product workflow** as the one solid
action; state in words; running workflows first, then by name, drafts last; a quiet History
control; search sized for a name; the same empty, no-match and failed-load states.

## Not in this change

No API, permission or history change. The list still calls the same endpoint and reads the
same fields. The success percentage is removed from the row rather than recalculated; the
runs themselves are still in each workflow's History. There is no "start a batch" action on
the row; that needs the batch-start route's return contract and is a follow-up.

## Checks

Browser tests cover ordering and state words, the figures, search and its no-match state,
the empty state, a failed load and retry, and returning by an in-app tab. A `CONCEPT ONLY`
group loads each style at 390, 1024, 1440 and 1920, and checks each style's arrangement and
the register's column alignment. Screenshots: each style at desktop, laptop with the
sidebar open, tablet, phone, wall and dark, plus search, no match, history, quiet and failed load.

## Review outcome

Four screenshot passes. Pass 1: the search ran full width; the register's headings did not
line up with their columns; the empty state said "0 product workflows". Pass 2: dark-theme
chevrons were yellow; the catalogue wrapped its fourth card onto a row of its own. Passes 3
and 4: no defects found. Awaiting the pick.

The shared Production layout test required every card on a sub-page to sit in one column.
It now accepts the board's paired rows, checking that each row starts and ends at the same
edges. One existing test clicked "the" link to this page from Home, which now has several;
it clicks the first.

## Decision: Style 1, the Board

Chosen by the founder on 14 October 2026. Figures sit beside what is in production now, then
every workflow one per line, matching Home and Production. The Catalogue's cards take more
height as the range grows; the Register needs width and drops its columns on a phone. The
preview switch, both losing layouts, the summary sentence and column headings they used, and
the concept-only tests are removed. The success percentage stays out of the row until the
founder decides how it should be counted.
