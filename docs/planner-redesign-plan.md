# Planner redesign: three directions

Scope: `/core/planner`, the page behind the Production section's Planner tab.
Purpose: **show what needs making and when it is due, and let someone add a new order or forecast.**
The production board (`/core/planner/board`, UX overhaul 4.3) is a separate page and is not
changed here.

## What is wrong today

Observed in the seeded screenshots (`~/.cache/workflow-engine-ui-shots/pw-00-before`, 1440, 390 and dark):

- The add-demand form is the first card. What needs making starts below five form fields.
- Each demand is a line of raw values: `240.0000 L`, `Due 2026-10-12 · Priority 80 · open`.
  A demand two days late looks the same as one due next month.
- Every row ends in an outlined "Cancel demand" button, so the most prominent control on
  the page, seven times over, is the destructive one.
- A cancelled demand sits in the same list as the open ones.
- Nothing adds the demand up: there is no answer to "how much gin do I need to make?".
- "Add demand" is a pale button; the page has no solid primary action as its siblings do.

## What other products do

| Source | How it was read | Pattern | What it changes here |
|---|---|---|---|
| [Katana, Make screen schedule](https://support.katanamrp.com/en/articles/5914378-using-the-make-screen-schedule) | Page read | One queue of open orders ranked by priority, worked top to bottom; done orders in a separate table | Style 2 is a numbered queue, highest priority first; closed demand moves to its own collapsed list in every style |
| [MRPeasy, production planning](https://mrpeasy.com/demo-videos/production-planning-and-management) | Search summary only | Order status moves through named stages; red text flags what is not on track | Due state is words plus the alert colour, and only late work takes the colour |
| [Odoo, bills of materials](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/basic_setup/bill_configuration.html) | Search summary only | Product is the organising record, with related records one click away | The "To make" card adds open demand up by product output |
| [Linear, due dates](https://linear.app/docs/due-dates) | Search summary only (page returned 404) | Due date icon is red when overdue, orange within a week, grey otherwise; lists can be ordered by due date | Three due states (overdue, this week, later); Style 3 groups the list by them |
| Stripe Dashboard home | Not searched this round; carried from the Sales plan | A few figures first, then the list | Style 1's figures card: open, overdue, due this week |
| [Carbon, empty states](https://carbondesignsystem.com/patterns/empty-states-pattern/) | Search summary only | An empty state says what to do next | No demand shows one card with one sentence and an Add demand button, not three zeros |
| [Carbon, data table](https://carbondesignsystem.com/components/data-table/usage/) | Search summary only | The toolbar holds the primary action and search; rows hold the data | The form leaves the page body for the header's primary action |

Research limits: only the Katana article was opened and read. The rest are search-result
summaries of the linked pages, so they are pointers rather than quoted guidance. Nothing
found compares these layouts in use; the arrangements are design judgement.

## Three directions to choose from

| | Style 1: Board | Style 2: Queue | Style 3: Timeline |
|---|---|---|---|
| Idea | Figures beside what to make, then demand soonest-due first | One sentence, then a numbered queue in the order to make it | One sentence, then demand grouped Overdue / This week / Later with totals alongside |
| Taken from | Production board (!515), Stripe home | Katana Make screen | Linear due dates |
| Best at | Matching Home and Production; seeing volume at a glance | Deciding what to make next | Seeing what is late and what is coming |
| Gives up | The list starts lower on the page | Totals move below the queue; due order is lost | Figures as boxes; priority order |

All three share: the page header its sibling Production pages use, with "Production board"
outlined and **Add demand** as the one solid action; the form behind that action; due dates
in words with the date in a tooltip; quantities without padding zeros; a quiet "Cancel" per
row; closed demand collapsed; the same empty, loading and failed-load states.

## Not in this change

No API, calculation, permission or audit change. The demand API still returns rows soonest
due first; Style 2 re-orders them in the browser. Priority stays a number from 0 to 100.
The production board, planning batches and capacity are untouched. There is still no link
from a demand to planning it on the board; that needs the board to accept a demand in its
address and is a follow-up.

## Checks

Browser tests cover due wording, figures and totals, the form opening and closing, the
empty state, a failed load and retry, and returning by an in-app tab. A `CONCEPT ONLY`
group loads each style at 390, 1024, 1440 and 1920 for sideways scroll and row containment,
and checks each style's ordering. Screenshots: each style at desktop, laptop with the
sidebar open, tablet, phone, wall and dark, plus add form, closed list, quiet and failed load.

## Review outcome

Four screenshot passes. Pass 1: the paired layouts never applied (a container cannot be
styled by its own query). Pass 2: Timeline's totals landed above the list, leaving a blank
half screen; the quiet state was three zeros and two empty cards; a failed load showed
dashes. Pass 3: a sticky totals card slid under the top bar. Pass 4: no defects found.
Awaiting the pick.

The shared Production layout test required every card on a sub-page to sit in one column.
It now accepts the board's paired rows, checking that each row starts and ends at the same edges.
