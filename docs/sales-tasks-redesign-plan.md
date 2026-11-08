# Sales Tasks redesign plan

**The page answers:** what do I need to do for customers today, and what comes after it?

## What is wrong today

Observed in the `00-before` screenshots: a seeded team of two, 17 open follow-ups, a custom
"Waiting on customer" lane, and four finished.

- **Three bands of controls before any task.** First a scrolling date strip (most of it past
  days with no tasks), then a full-width "All operators" select, then two toggle switches and
  "Add lane". The first card starts 510 px down.
- **Five equal lanes.** Done and Cancelled take as much room as To do. The custom lane's
  header wraps to three lines between its four icon buttons.
- **Every card shows everything.** Priority badge, an upper-case customer tag, the person,
  the due date, the description ("No description" when there is none), and a red Delete.
- **Doesn't match its siblings.** The title "Tasks" sits outside the house header, and
  "New Task" is a small button inside the strip's card.
- **Two bugs:**
  - **Dates on the wrong day:** the date strip used `toISOString()` on local midnight. In
    New Zealand that is the previous UTC day, so a task due Saturday put its dot on Sunday,
    and choosing a day filtered to the day before.
  - **Everything loaded twice:** the template called `x-init="init()"` and Alpine also calls
    `init()` itself. The two lane loads interleaved, so the custom lane appeared twice in
    state; duplicate `x-for` keys then dropped it from the phone lane picker.

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| HubSpot tasks (comparable) | Default views are Due today, Overdue and Upcoming; the sales workspace starts from tasks due today, overdue or due tomorrow | Style 2 groups by when it's due; the summary line counts overdue and due today |
| Pipedrive activities (comparable) | A list with an Overdue filter, and a calendar by day, week or month; activities sit on their scheduled date | Style 3's week, with a tray for overdue tasks from before this week |
| Trello / the board this page already had (comparable) | Lanes by stage, drag between them | Style 1 keeps lanes and drag, and folds finished work into a rail |
| Linear (craft) | List or board layouts over the same issues; completed and cancelled issues sort to the end | One data set, three layouts; finished work always last and folded |
| Todoist Upcoming (craft) | List, board (a column per day) or calendar; add a task at the bottom of a day | Style 3's "+ Add" on each day opens a new task due that day |
| Kanban UX write-ups (pattern) | A board answers "where is everything, what is stuck"; badly built boards become walls of near-identical cards | Cards cut to title, customer and person, and due words; one tag (High) |

**Looked for but not found:** Nielsen Norman research comparing boards and lists; the
results were vendor posts, cited as such. Things 3's own documentation didn't come up.

## Three directions to choose from

| | Style 1: Board | Style 2: Due list | Style 3: Week |
|---|---|---|---|
| Idea | Lanes of open work (To do, In progress, your lanes); finished folds into a rail | One list grouped Overdue, Today, Tomorrow, This week, Later and No date; tick to finish | Monday to Sunday side by side, overdue from earlier above, undated below |
| Taken from | Trello, Linear board | HubSpot's due views, Todoist Today, Linear list | Pipedrive calendar, Todoist Upcoming board |
| Best at | Seeing what stage each follow-up is at, and moving it on | Starting the day: what's late, what's today | Planning the week and spotting empty days |
| Gives up | Dates are words on each card, not an order | Lanes become a word on the row; no dragging | Long titles wrap in narrow days; no lanes |

**All three share:**
- the house header, with the open count, overdue and due today in words, and one primary
  action, **New task**;
- one row of controls: search tasks or customers, whose tasks (Everyone, Mine, Unassigned,
  each person) and Show finished;
- due dates in words ("3 days overdue", "Today", "Wednesday");
- the drawer in sentence case, with fields reordered (title, due and who, customer, priority
  and status, notes) and Delete moved into it;
- finished tasks limited to the archive window in Sales settings.

## Not in this change

- **APIs:** task and lane APIs are unchanged.
- **The Sales overview's task board:** not touched.
- **The drawer's shared CSS:** `.crm-task-sheet` is shared with Customers and stays as it is.
- **Follow-up:** the same double `x-init="init()"` is on Configuration, Analytics, Batch
  matching, Customer detail and Excise.

## Checks

- **New browser tests** in `tests/e2e/test_sales_tasks_page.py`:
  - a task due today is under Today on a New Zealand clock;
  - the page asks for tasks and lanes once;
  - a custom lane shows once with its tasks;
  - ticking a task done moves it to finished;
  - New task from the header and from `?new=1`;
  - CONCEPT ONLY: each style at phone, laptop and wall widths with no sideways scroll.
- **Changed test:** `test_sales_design.py` expects "New task", in sentence case.
- **Screenshots:** every style at laptop (first screen and full page), phone, wall and dark;
  search; one person with finished shown; filtered to nothing; the drawer for an edit and a
  new task; next week; a custom lane on a phone; arriving by the tab; and a task ticked done.

## Approved implementation — 25 Oct 2026

Board, List and Week as permanent user-selectable views is the approved design for !559. All three views stay available through a permanent View toggle. The choice is remembered in the browser; changing views preserves filters and edits.

Validation: 39 Sales Tasks and Sales design browser cases passed, including switching views, remembering the selection, preserving filters, New Zealand due dates, custom lanes and completing tasks.

The selected view also updates `?view=board|list|week` without navigating, so reloading or sharing the page keeps that view. Legacy `?style=1|2|3` links still open their corresponding view.

View-link follow-up validation: 2 focused browser cases passed, JavaScript syntax and Semgrep auto scan passed.
