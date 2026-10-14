# Contract orders redesign: three directions

Scope: `/core/contracts`, the Contract orders page reached from the Planner.
Purpose: **show which customer orders are due and which are late, and let someone take a new order.**
The order page (`/core/contracts/<id>`), the customer portal and customer raw materials
are separate pages and are not changed here.

## What is wrong today

Observed in the seeded screenshots (`~/.cache/workflow-engine-ui-shots/contracts-00-before`, 1440, 390 and dark):

- Every order is one table, sorted by due date, so finished and cancelled orders sit between the open ones.
- Due dates are raw ISO dates (`2026-10-12`). An order three days late looks the same as one due next month.
- Status is plain text with no colour or badge. Quantities carry padding zeros (`600.0000 bottles`).
- The new order form is always open: twelve fields in a five-column grid, in no particular order,
  with the CCA reference wedged between Duty and Product.
- The new customer form is always open, and every customer is an open edit form (name, CRM
  contact, access, Save). Four customers take a full screen of inputs. Nothing says how many
  orders each customer has.
- The page has no solid primary action. "Create order" and "Add customer" are pale.

## What other products do

| Source | How it was read | Pattern | What it changes here |
|---|---|---|---|
| [Katana, Make screen schedule](https://support.katanamrp.com/en/articles/5914378-using-the-make-screen-schedule) | Page read | Open orders worked as a queue; done orders in a separate table | Completed and cancelled orders move to their own collapsed list in every style |
| [Katana, creating a manufacturing order](https://support.katanamrp.com/en/articles/5914365-creating-a-new-manufacturing-order) | Search summary only | Order creation is its own form, reached from one button | The new order form hides behind a solid **New order** header button |
| [Packiyo, brand owner's portal](https://help.packiyo.com/portal/en/kb/articles/the-brand-owner-s-guide-to-the-packiyo-portal) | Search summary only | A contract fulfiller organises work by client, each client with its own orders | Style 3 groups open orders under each customer |
| [Amtech, customer portal](https://www.amtechsoftware.com/michcor-container-implements-amtechs-customer-portal/) | Search summary only | Contract manufacturers expose order status per customer | The customer list shows open orders per customer, not an edit form |
| [Stripe, manage invoices](https://docs.stripe.com/invoicing/dashboard/manage-invoices) | Search summary only | Status tabs over one list; each row has a coloured status badge; overdue called out | Status becomes a badge; due date becomes words ("3 days overdue") with only late work in the alert colour; Style 2 uses tabs |
| [Carbon, data table](https://carbondesignsystem.com/components/data-table/usage/) | Search summary only | Primary action in the table toolbar; rows hold data, not inputs | Customer rows become read-only lines with an Edit disclosure |
| [Carbon, tabs](https://www.carbondesignsystem.com/building-blocks/core/components/tabs/guidelines) | Search summary only | Tabs switch between related views of the same level, with counts | Style 2's Orders / Customers tabs carry their counts |
| [Carbon, empty states](https://carbondesignsystem.com/patterns/empty-states-pattern/) | Search summary only | An empty state says what to do next | No orders shows one sentence and the New order button |

Research limits: only the Katana schedule article was opened and read. The rest are
search-result summaries, so they are pointers rather than quoted guidance. Nothing found
compares these layouts in use; the arrangements are design judgement.

## Three directions to choose from

| | Style 1: Board | Style 2: Tabs | Style 3: By customer |
|---|---|---|---|
| Idea | Figures strip (open, overdue, due this week), then orders with customers beside them on wide screens | One sentence, then Orders and Customers as two tabs | One sentence, then open orders grouped under each customer, customers after |
| Taken from | Planner Board (!522), Production board | Stripe invoices | Packiyo, Amtech portals |
| Best at | Matching Planner and Home; volume at a glance | A short page; one thing at a time | Answering "what do we owe this customer?" |
| Gives up | Customers sit below the orders under 1200px of content | Customers are a click away; figures become a sentence | One due-date order across customers |

All three share: **New order** as the one solid action, with the form behind it in four
labelled groups (Customer and reference; Product and quantity; Materials and specification;
Duty and status); due dates in words with the date kept for anything over two weeks out;
status badges; quantities without padding zeros; completed and cancelled orders collapsed;
customers as read-only rows with open-order count, an Active / "Not taking new orders"
badge and an Edit disclosure; **Add customer** behind a button.

## Not in this change

No API, calculation, permission or audit change. The form posts the same fields to the same
endpoint; customer edits use the same PATCH. The order page, portal and raw materials pages
are untouched. Grouping and due wording happen in the template and browser.

## Checks

Browser tests cover due wording and figures, the closed list, the new order form's four
groups, creating an order (lands on the order page), the customer disclosure and add form,
and returning by an in-app link. A `CONCEPT ONLY` group loads each style at 390, 1024, 1440
and 1920 for sideways scroll and checks each style's arrangement. Screenshots: each style at
desktop, laptop with the sidebar open, tablet, phone, wall and dark, plus new order, customers
open and closed list. `scripts/ui_shots.py` gains a `contracts` seed: four customers (one
paused) and six orders across overdue, this week, later, draft, completed and cancelled.

## Review outcome

Five screenshot passes. Pass 1: the style switch did nothing (the root's own
`data-contracts-tab` matched the click handler's selector); content touched the sidebar.
Pass 2: Style 3's per-customer tables had different column widths. Pass 3: at 1440 the
Board put figures and customers first and pushed the orders below the fold. Pass 4: with
orders beside customers at 1440, order references and products wrapped mid-word. Pass 5:
no defects found. Awaiting the pick.
