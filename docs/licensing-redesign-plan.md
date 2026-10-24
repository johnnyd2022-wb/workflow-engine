# Licensing redesign plan

**The page answers:** can we sell alcohol today, what is due next, and can I show an inspector
the proof?

## What is wrong today

Observed in the `00-before` screenshots (a seeded off-licence due for renewal, a special
licence, three managers, eight checks and a log):

- **It doesn't look like its siblings.** A dark hero banner with a capitalised eyebrow
  ("SALE AND SUPPLY OF ALCOHOL ACT 2012") where Customs and NP3 have the house header, and
  four panels each with its own eyebrow. Nothing on the first screen says whether anything is
  due.
- **Every fact on every licence, always.** Each card lists premises, DLC, endorsements, sale
  and delivery hours and the full conditions, then a site picker and four or five pill
  buttons. Ended licences sit beside current ones at the same weight.
- **Browser prompts for dates.** "Renewal lodged", "Renewal granted" and "Name the manager"
  open `window.prompt` and ask you to type `YYYY-MM-DD`.
- **The log form is always open.** Seven fields sit above the log on every visit, so the log
  itself starts below the fold.
- **Tables clip at phone width.** The managers' table and the log are cut off at the right
  edge; the phone page is 5,690 px tall.
- **The checks use the catalogue's regulatory sentence as their name** ("Keep training and
  incident evidence for age, intoxication and responsible-service controls.").

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| Sovos ShipCompliant licence management (comparable) | A register of licences with renewal deadlines tracked and alerts sent 90 days before expiry | Every licence shows its next date in words ("in 20 days"); renewal dates lead |
| RenewAlert, Expiration Reminder (comparable) | One dashboard of every expiring licence and permit, colour-coded by how soon | Style 2's "Coming up": one dated list across licences, certificates, fees and check reviews |
| Vanta documents (comparable) | Each document has a renewal cadence; the next due date counts from the evidence's effective date; reminders before it falls due | Checks show "review by", and overdue reviews are named, not just coloured |
| HPA Licensed Premises Toolkit (domain) | The registers an inspector asks for, in order: licence, certified managers, host responsibility policy, training, incident log | Style 3 orders the page that way, numbered, as one file |
| Todoist Upcoming (craft) | Everything scheduled, by date, with overdue at the top and the date as the row's first column | The dated rows in Style 2: date first, then what, then state and one action |
| Stripe dashboard activity lists (craft) | A log row is the action, who and when; detail on request | Log rows lead with the type and what happened; where, who and reference are secondary |
| GOV.UK summary list and summary card (pattern) | Key and value rows inside a card per item; a list of tasks is a list, not a table | Licences are summary cards with four key facts; managers, checks and log are lists, so nothing clips on a phone |

**Looked for but not found:** a licence-management product's own screens for duty manager
certificates (Sovos covers state licences, not people). Linear's display-options docs were
read for grouping, but it has no licensing analogue.

## Three directions to choose from

| | Style 1: Register | Style 2: Coming up | Style 3: Inspector file |
|---|---|---|---|
| Idea | Four answers across the top, then the four registers as cards | Every date that matters in one list, soonest first, then the registers two-up | One numbered document in the order an inspector asks, with a contents rail |
| Taken from | Customs and NP3 summaries, GOV.UK summary cards, Sovos register | RenewAlert / Expiration Reminder, Todoist Upcoming | HPA toolkit order, NP3's verifier pack, GOV.UK check answers |
| Best at | Seeing the whole position at a glance | Knowing what to do next, and doing it from the row | Sitting with an inspector, or before a visit |
| Gives up | Dates are spread across sections | No headline tiles; the registers sit lower | The longest page; tiles are replaced by a verdict per section |

**All three share:**
- the house header (title, caption, Inspector pack, and one primary action: Log a refusal or
  incident);
- plain names for the checks;
- status in words;
- licence cards cut to four key facts, with site, conditions and hours folded under "Site,
  conditions and hours";
- ended licences and managers who have left folded away;
- dialogs for every form;
- an in-page date or name dialog in place of the browser prompts;
- the log showing the latest five, with "Show all".

## Not in this change

- **APIs, calculations and the PDF:** `/api/compliant/licensing*` and the inspector pack are
  unchanged.
- **The training register:** stays where it is, linked from the checks.
- **Follow-up:** the old `licensing-*` rules in `compliant.css` are deleted, since only this
  page used them.

## Checks

- **New browser tests** in `tests/e2e/test_licensing_page_browser.py`, run through the test
  client so no live server is needed:
  - the four answers;
  - "Renewal lodged" asks in the page and raises no browser prompt;
  - logging from the header;
  - the log's "latest five";
  - CONCEPT ONLY: each style at phone, laptop and wall widths, with no sideways scroll and
    every region present.
- **Changed test:** `test_site_licensing_browser.py` opens "Site, conditions and hours"
  before choosing a site, because the picker now lives there.
- **Screenshots:** every style at laptop (first screen and full page), phone, wall and dark;
  the dialogs; the details opened; arriving by the tab; and a saved log entry.
