# Production board redesign: three directions

Scope: `/core/planner/board`, the Production board reached from the Planner (UX overhaul **4.3**).
Purpose: **show which batches are due to start on which day, whether each can start, and let
someone plan a demand or move a batch.** The Planner, the batch API, planning calculations and
capacity rules are not changed.

## What is wrong today

Observed in the seeded screenshots (`~/.cache/workflow-engine-ui-shots/board-00-before`: 1440, 390 and dark,
seeded with five demands planned into fifteen batches and an overloaded still):

- The page is 5,500px tall at 1440 and 14,500px on a phone. Every batch card carries all of its
  forms (priority, pin, new start date, cancel, start) and the full list of blockers, so one
  card is about 900px tall in a 150px column.
- The first screen is two form cards (Period, Plan batches). No batch is visible without scrolling.
- Every card repeats the same five blockers word for word; nothing says at a glance whether a
  batch can start.
- Quantities and dates are raw values (`40.0000 L`, `Proposed start 2026-10-13`, title `2026-10-12 – 2026-10-18`).
- The capacity list names the batch to move by an id fragment ("consider moving batch 5d6d290e").
- There is no way to step to the next week; the date has to be typed and "Show board" pressed.
- Settings (batch sizes, step timings, resource calendars) sit between the controls and the board.

## What other products do

| Source | How it was read | Pattern | What it changes here |
|---|---|---|---|
| [MRPeasy, production schedule](https://www.mrpeasy.com/resources/user-manual/production-planning/production-schedule/) | Page read | Calendar and Gantt views of manufacturing orders; an order block shows status by colour and parts availability by text colour; drag to reschedule; started operations cannot be moved | Each card shows its state in words and a left-edge colour; started and pinned batches lose the drag handle; Style 3 is a lane (Gantt-like) view |
| [Katana, using the schedule](https://support.katanamrp.com/en/articles/151-using-the-schedule) | Search summary only | One list of orders ranked by priority, reordered by drag, worked top to bottom | Priority stays on every card; Style 2 reads each day as a list |
| [MRPeasy, capacity overview](https://www.mrpeasy.com/blog/production-capacity-overview/) | Search summary only | Workstation load beside the order schedule | Overloads are listed under the board by day and resource, naming the batch to move |
| [SAP Fiori, calendar](https://www.sap.com/design-system/fiori-design-web/v1-139/ui-elements/calendar/usage) | Search summary only | Visible previous / next buttons that step by the view's unit, and a way back to today | Previous, Today and Next beside the period title, stepping a day, week or month |
| FullCalendar-style toolbar (third-party docs, low-trust domain) | Search summary only | Week titles as a range ("Jan 5 – 11, 2026") | Period title reads "12 – 18 Oct 2026", "October 2026" or a weekday |
| [SAP Fiori, calendar (Android)](https://www.sap.com/design-system/fiori-design-android/v26-1/components/calendar/usage) | Search summary only | Today marked apart from the selected day; week views are poor where space is limited | Today's column has an accent border and a "Today" tag; the phone shows one day per row and folds empty days |

Research limits: only the MRPeasy schedule page was opened and read. Searches for craft
references (Linear, Height) on this shape returned nothing usable, so no craft source is cited;
the card treatment follows the house style and the Planner Board (!522).

## Three directions to choose from

| | Style 1: Week | Style 2: Agenda | Style 3: By demand |
|---|---|---|---|
| Idea | Figures strip, then a seven-day grid; empty weekends narrow | One sentence, then a row per day with its batches side by side; empty days fold to one line | One sentence, then a lane per demand across the days |
| Taken from | Planner Board (!522), MRPeasy calendar | Katana schedule list, calendar agenda views | MRPeasy Gantt by order |
| Best at | Seeing the week's load at once; matching the Planner | Reading on any width; wide cards | Seeing how one order spreads across days |
| Gives up | Narrow cards in a week | A day's shape across the week | Wide: scrolls sideways inside the board on a phone |

All three share:
- **Controls.** One controls card: Previous / Today / Next and the period title on one row, with the view and date beside them. Planning a demand ("Plan batches", the one solid action, and "Check materials") sits on the row below. The site picker shows only when there is more than one site.
- **Cards.** A compact batch card:
  - a drag handle and a Pin toggle;
  - the batch heading;
  - its state in words ("5 checks to clear" or "Ready to start");
  - quantity and product;
  - site and priority.
- **Details.** Proposed and ready dates, the blockers, materials, and the priority, move, start and cancel actions sit behind a per-card **Details**. It stays open while the board re-renders after an action. A batch that can start shows **Start batch** on the card itself.
- **Capacity.** The capacity review moves below the board and names the batch to move.
- **Settings.** Batch sizes, step timings and resources move to a Planning settings card at the foot of the page.

## Not in this change

No API, calculation, permission or audit change. Capacity wording ("overloaded resource-day(s)")
is kept. The board still loads every batch in the period; there is no paging. Dragging between
lanes in Style 3 moves the day only, as before.

## Checks

- **Browser tests.** `tests/e2e/planning/test_board_design.py`:
  - the compact card and its Details staying open;
  - period stepping;
  - the month starting under its weekday;
  - figures and the empty period;
  - arriving by an in-app link;
  - a CONCEPT ONLY group loading each style at 390, 1024, 1440 and 1920 with no sideways page scroll.
- **Existing tests.** The board phone, capacity and material tests now open a card's Details before using its actions, and read the period from the title's `data-start` / `data-end`. The shared layout test now finds the board by its "Planned batches" card.
- **Screenshots.** Each style at desktop, laptop, tablet, phone, wall and dark, plus an open card after an action, next week, a month, an empty month, the settings, reviewing an overload, and returning by an in-app link.

## Review outcome

Five screenshot passes:

1. **Pass 1.** No batch on the first screen; status text truncated in seven narrow columns; empty weekends as wide as weekdays.
2. **Pass 2.** Style 2 fell back to seven columns (the quiet-weekend rule beat it); figures still pushed the board below the fold.
3. **Pass 3.**
   - The month started in the first column whatever its weekday.
   - An empty month showed four zero figures.
   - A date input overflowed its card.
   - Style 3 repeated the demand name in every cell and clipped Sunday.
4. **Pass 4.** Pale settings save button and unstyled working-days fieldset; an open card stretched its neighbours in Style 2.
5. **Pass 5.** No defects found.

Also fixed in `scripts/ui_shots.py`: `purge` imported only modules named `*.models`, so planning's `batch_models` tables were never deleted and the purge stopped at `processes`.

## Decision: Style 1, the Week

Chosen by the founder on 16 October 2026. The controls card, then the figures strip and the
seven-day grid with quiet weekends narrowed; on a phone each day is a row and empty days fold.
The preview switch, Style 2's agenda rows and one-sentence brief, and Style 3's demand lanes are
removed. The CONCEPT ONLY tests became one permanent check at 390, 1024, 1440 and 1920: the
figures and every batch show, with no sideways scroll. A final screenshot pass
(`board-06-final`) of the locked page found nothing to fix. A by-demand view remains a
candidate follow-up if planners ask how one order spreads across days.
