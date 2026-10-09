# Trace and recall: redesign plan

The Trace and recall page (`/core/sourcemap`) answers two questions: where did this come
from, and where did it go. This plan covers how the page shows the answer. The trace
APIs, the recall arithmetic and the CSV export are unchanged.

## What is wrong today

- **The "Map" is not a map.** It is an indented list. One lot feeding two batches repeats
  the whole process twice with nothing showing they share a source, and customers sit in a
  separate green box under it rather than at the end of the chain they belong to.
- **The trace opens on a summary that hides the answer.** The Timeline lists step names;
  what was consumed, what was made and who bought it are behind "Details" or further down.
- **The headline numbers are missing.** "1 process, 2 executions" is on the trace header.
  Units sold, customers reached and stock still on hand are only on the Recall tab.
- **It does not look like the rest of the app.** Blue accents, pill badges and its own
  control styles, where every other Production page uses the shared teal workspace cards.
- **Controls crowd the trace.** A full-width date field ("Replay as of") and a colour
  legend sit between the view tabs and the content on every trace.

## What other products do

| Source | Pattern | Use here |
|---|---|---|
| Data lineage tools (dbt, Collibra, Paradime, DataHub) | Left-to-right graph, upstream left, downstream right, centred on a selected node. Nodes coloured by type. Select a node to light up its path. | The Map becomes this. |
| Same, at scale | Start shallow, collapse repeated stages, warn before expanding very large graphs. | Columns are ranks, so depth is bounded by the number of steps. A wide trace scrolls sideways inside the card. |
| SAP Global Batch Traceability | Top-down (what went into this) and bottom-up (where was this used) as two directions of one graph. | One graph, both directions, from whichever lot is picked. |
| Food-safety recall guidance (BRCGS mock recall, regulator templates) | A recall is judged on quantity reconciliation: produced = sold + on hand, and on customer contact gaps. | Those three numbers and the customer count go on the trace header, not only on Recall. Customers with no contact details are flagged on the graph. |
| Stripe, Linear | One accent colour, hairline borders, status as text plus colour. | Shared workspace tokens replace the page's own palette. |

## Design

### 1. Find something to trace

Unchanged in structure: search, then Inventory / Batches / Suppliers / Activity. Restyled
to the shared tokens: tiles instead of blue-bordered cards, a segmented control in the
house style, type shown as a dot and a word.

### 2. Trace header

Name, batch, and "Back to browse", then one row of figures:

- **Batches** made from or leading to this lot
- **Sold**, **Customers**, **On hand**: the same figures the Recall tab computes
- **Findings**, only when there are any

### 3. Map: a lineage graph (the default view on wide screens)

Columns left to right: source lots, then one column per production stage, then finished
lots, then customers.

- A node is one lot: type, name, batch, quantity. Source lots also show the supplier.
- A customer node shows the quantity allocated, the number of invoices, and
  "No contact details" when both phone and email are missing.
- Curved edges join each lot to what it became. A lot used by two batches has two edges
  leaving it, which is the fact a recall turns on.
- The traced lot is ringed. Pointing at or focusing any node dims everything not upstream
  or downstream of it.
- Selecting a lot opens its history panel (the existing story panel).
- On a phone the page opens on Timeline; Map remains available and scrolls sideways.

### 4. Timeline, Table, Recall

Kept, restyled. Timeline's "Sales" box becomes a plain "Sold to" list in the house style.
Recall's actions use the shared button styles.

### 5. Controls

View tabs on the left, "As of" date on the right at its natural width. The legend goes:
nodes now label their own type.

## Not in this change

- No change to `/api/core/inventory/trace*` or `/api/core/sourcemap/*`.
- No change to what a recall includes or to the CSV export.
- Wastage log and System findings keep their content; they are restyled only.
- Deep links to a specific lot (`?item=`) and grouping very wide columns are follow-ups.

## Checks

- Existing e2e suites for this page (`tests/e2e/traceability`, `source_to_sale/test_mock_recall.py`,
  `activity_log/test_activity_tab.py`) keep passing; tests that assumed Timeline is the
  first view select it explicitly.
- New e2e: the graph shows a shared source lot once with an edge to each batch; customers
  appear as the last column with allocated quantities; hovering a node dims unrelated
  nodes; header figures match the Recall tab.
- Screenshots at 1440, 1024 and 390 wide, light and dark.
