# Production pages clean-up plan

Started 2026-10-05. Same approach as the Production overview: a page header, then a
vertical run of full-width cards with clear groupings, built from the shared `workspace-*`
elements, and checked at phone (390px), laptop (1024px) and desktop (1440px) widths in
light and dark.

## The pattern every page follows

- Wrapper: `workspace-overview` (1280px column, 24px gutters; 16px on phones).
- Header: `workspace-header` with the page title, a one-line caption, and page-level
  actions on the right (they wrap under the title on phones).
- Body: `workspace-stack` of `workspace-card`s. One card per job the page does
  (find, add, review). A card that holds several of the same thing uses tiles inside it.
- Forms: `workspace-form` (labelled fields in a responsive grid, shared inputs and buttons).
- Lists and tables: inside a card, never bare on the page background.
- Secondary navigation: the shared "Manage production" card, placed in the page column.
- Each page gets a browser test at 390, 1024 and 1440px: blocks in order, full column
  width, nothing overflowing, no horizontal page scroll.

Shared elements added for this work live in `app/core/frontend/css/workspace-overviews.css`.

## Pages

Status: `[ ]` to do, `[x]` done and tested.

### Planner tab
- [x] **Planner** (`/core/planner`) — currently unstyled. Header with a "Production board"
      action; "Add demand" form card; "Production demand" list card; Manage production card.
- [x] **Production board** (`/core/planner/board`) — header; cards for View, Plan batches,
      Site capacity and the Board itself; days go three across on a laptop and stack on phones.
- [x] **Contract orders** (`/core/contracts`) — header with a "Customer raw materials" action;
      cards for Orders, New order, Contract customers and New contract customer.
- [x] **Customer materials** (`/core/contracts/materials`) — header; customer picker and
      materials in one card.

### Workflows tab
- [x] **Workflows** (`/core/processes`) — header with "Create product workflow"; one card
      holding search and the workflow list; Manage production card.
- [x] **Batches** (`/core/executions/live`) — remove the Production health and Get to work
      cards (they belong to the overview); the board in one card.

### Inventory tab
- [x] **Inventory** (`/core/inventory/view`) — header with Live inventory and Add to
      inventory actions; "Find stock" filter card; "Stock on hand" card; an "Inventory tools"
      card linking Trace and recall, Stocktake, Stock transfers, Record disposal and Suppliers.
- [x] **Live inventory** (`/core/inventory/live`) — remove the overview cards; snapshot card;
      items card.
- [x] **Add to inventory** (`/core/inventory/add`) — one card with the choices as an action grid.
- [x] **Record disposal** (`/core/inventory/dispose`) — header left-aligned like the rest; one card.
- [x] **Stocktake** (`/core/stocktake`) — already cards; move onto the shared wrapper, header
      and card styles.
- [x] **Trace and recall** (`/core/sourcemap`) — title matches its name; search and results
      card; wastage log and system findings as their own cards.
- [x] **Stock transfers** (`/core/site-transfers`) — header; content in a card.
- [x] **Suppliers** (`/core/suppliers`) — duplicate breadcrumb removed; Add and Import are
      header actions; "At a glance" and the supplier list are shared cards.

### Overview tab
- [x] **Production tasks** (`/core/tasks`) — remove the overview cards; filters card; board card.
- [x] **Cases** (`/core/cases`) — currently unstyled. Header with "New case"; filter selector;
      cases list card.

## Not in this pass

Full-screen task flows keep their own focused layouts. They are forms someone works
through, not pages someone lands on:

- Workflow editor and the create-workflow wizard (`/core/flows…`)
- Recording a production step (`/core/flows/batches/start`, step record pages)
- Add inventory manually / from a file / by barcode (`/core/inventory/add/…`)
- New case and case detail (`/core/cases/new`, `/core/cases/<id>`)
- Task settings (`/core/tasks/configuration`)

## Result

All sixteen pages done 2026-10-05. `tests/e2e/test_production_pages_layout.py` opens every
one at 390, 1024 and 1440px and checks the shared header, that its cards share one column,
that the overview-only cards are gone, and that the page does not scroll sideways.

Shared elements added along the way (all in `workspace-overviews.css`): `workspace-page`,
`workspace-header__actions`, `workspace-form` (+ `__wide`, `__actions`), `workspace-input`,
`workspace-list`, `workspace-form-list`, `workspace-table`, `workspace-chips`,
`workspace-empty`, `workspace-notice`, `workspace-scroll`.

Left as they were, inside their new cards:

- Stocktake keeps its own buttons, tables and count rows.
- The batch pipeline/timeline, the live-inventory filters and item tiles, the task lanes and
  the trace views keep their own internals.
- The Production board keeps three days across on a laptop and one on a phone: an existing
  phone test requires every control on a batch to stay on screen.
