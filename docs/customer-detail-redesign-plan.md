# Customer page redesign plan

**The page answers:** who is this customer, what have they bought, and what do I need to do for them next?

## What is wrong today

Observed in the `00-before` screenshots (a seeded customer with three invoices, five notes and five tasks):

- **Two titles:** "Customer Profile" with a subtitle, then the customer's name in a hero with an avatar.
- **Off-palette tabs:** the segmented tabs are bright blue (`#007bff`), unlike every other house page.
- **Twelve detail fields, many saying nothing:** "Customer: Yes", "Supplier: No", and "—" for tax number, account number and last synced. "Last contact" reads "24 Oct 2026 (task)".
- **Nothing up front:** nothing on the first screen says when they last ordered or what's due for them. The open tasks are a tab away.
- **Tasks:**
  - a full-width status select;
  - ISO dates ("2026-10-23");
  - "No description" on every card;
  - finished tasks mixed in with open ones.
- **Notes:** an upper-case "ADD NOTE" label and a title-case "Add Note" button.
- **Charts:** in the dark theme their labels are drawn in a fixed dark colour, so the values and months vanish.
- **Double load:** the template calls `x-init="init()"` and Alpine also calls `init()`, so the customer, people and sales figures are fetched twice on every visit.

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| HubSpot record page (comparable) | About-this-record on the left, activity in the middle, associations on the right | Style 2: work on the left, who they are and sales on the right |
| Pipedrive person and organisation (comparable) | A details sidebar beside one chronological history of activities, notes and deals, with an "upcoming" focus area above the history | Style 3: Coming up, then Before now, beside the details |
| Xero contact (comparable) | Money first: what they owe and what they've bought, then the contact details | The four facts lead: sales in the period, last order, open tasks, last contact |
| Linear issue (craft) | A properties sidebar and an activity stream with the composer on top | Style 3's note box at the head of the feed |
| GOV.UK summary list (pattern) | Only rows with a value; a list of tasks is a list | Details hide empty fields; open tasks are sorted first |

**Looked for but not found:** Pipedrive's own help page for the person view layout; the description above is from the product as widely documented, not a page read here.

## Three directions to choose from

| | Style 1: Tabs | Style 2: Record page | Style 3: Activity |
|---|---|---|---|
| Idea | Four facts, then Overview, Invoices, Notes and Tasks as tabs | No tabs: tasks, invoices and notes on the left, details and sales on the right | No tabs: a note box, what's coming up, then everything that happened, beside the details |
| Taken from | Today's page, in the house style | HubSpot record page | Pipedrive history, Linear activity |
| Best at | A calm first screen | Seeing everything about a customer at once | "What's been going on with them?" before a call |
| Gives up | A click to see invoices or tasks | A long page on a phone | Invoices and tasks lose their own lists and filters |

**All three share:**
- the house header: the customer's name; the contact person, email and phone (linked); New task and one primary action, New invoice;
- four facts: sales in the period, last order, open tasks with the next one, and last contact;
- details showing only the fields that hold something;
- open tasks first, with due dates in words;
- chart colours from the page's tokens;
- one load instead of two.

## Not in this change

- **Unchanged:** the API, the edit form, the Xero warning, the invoice and task dialogs, and the analytics date range.
- **Not a tile:** an "owed now" figure would need every invoice, but the customer payload carries the five latest, so it isn't shown.
- **Follow-up:** the same double `x-init="init()"` on Configuration, Analytics, Batch matching and Excise.

## Checks

- **New browser tests** in `tests/e2e/test_customer_detail_page.py`, through the test client with Xero faked:
  - the customer loads once;
  - the header and facts;
  - New task from the header on any tab;
  - the activity groups;
  - CONCEPT ONLY: each style at phone, laptop and wall widths.
- **Screenshots:**
  - every style at laptop (first screen and full page), phone and wall, and dark after a reload;
  - each tab, editing details, a new task, the feed filtered to tasks, and arriving from Customers;
  - a note added from the feed.
