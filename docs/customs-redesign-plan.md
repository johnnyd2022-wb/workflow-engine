# Customs page redesign

`/compliant/nz-alcohol/customs`. The page is for one job each month: **see what to type into
the Customs excise entry, lodge it, and record that it's lodged**, then keep the records
Customs can ask to see.

## What is wrong today

Observed in `00-before` (laptop, phone, dark):

- The answer is below the fold. A dark hero banner ("Customs alcohol reconciliation."), a
  stray underlined link, then **Movements by licensed area**, a multi-site tool with an empty
  licence picker and a paragraph of caveats, all come before the excise entry.
- The draft doesn't match what Customs asks for. It shows LAL and duty only: no alcohol levy,
  no GST on the levy, no total to pay. Its columns (Tariff item, Product, Units, Litres, LAL,
  Rate, Duty) aren't in Trade Single Window's order, so copying across means re-reading.
- Overdue periods aren't flagged. July and August, unlodged and past due, read "Due 21 Aug",
  the same as a period that isn't due yet. A year of untracked months reads the same way.
- The evidence form takes half the page: twelve fields, always open, then an empty
  "Recent records".
- The lodging frequency and reminder controls compete with the period in the header.
- At phone width the entry table is clipped and the movements tool comes first.

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| Breww, NZ excise duty report (comparable) | One row per excise item **in Trade Single Window's column order**: excise item, supplementary quantity (L), statistical quantity (LAL), rate and basis, duty, levy, GST on levy, total. A breakdown below with "View entries". A report can't span a rate change. | The entry table follows TSW order, with a "Where these figures come from" breakdown. Rates are taken at the period start, never mixed. |
| NZ Customs excisable goods entry rules (comparable / authority) | Statistical and supplementary quantities to three decimal places; numbered detail lines. | Quantities shown to 3 dp; lines numbered. |
| Ekos, TTB report generation (comparable) | Pre-filled returns from recorded production and sales; the period is the unit of work. | The period is the page's spine. Nothing is typed that the app already knows. |
| Xero GST return (comparable) | Review, then file, then a confirmation that shows when it was filed. | "Record as lodged" sits under the figures and the period shows "Lodged 16 Jul" after. |
| Stripe Tax / TaxJar Filings tab (craft) | The current month's filing summary with the estimated payment up front, then a detailed report. | The four figures to pay lead, with the table under them. |
| Linear cycles (craft) | Current, upcoming and past cycles in one list, with status and progress per cycle. | Periods as one list with status in words: In progress, Due 21 Oct, Overdue, Lodged 16 Jul. |
| GOV.UK task list; Scottish Government "Check answers" (pattern) | Tasks in order with their state; a summary list of answers before the submit button, with the declaration before the primary action. | Style 2 is a four-step task list, and its figures are a summary list. |

Searched and didn't find: a screen-level description of Ekos's or Gusto's filing pages (vendor
pages only describe outcomes).

## Three directions, and the pick

**Chosen (21 Oct 2026): Style 1 (Entry) on a laptop or wider, Style 3's phone layout below 720px.** On a phone the four figures read as a list in entry order rather than a 2×2 grid of tiles with no reading order, and lodged periods show their LAL in the period chips. Style 2 lost because the period dropdown hides the backlog; Style 3's rail lost at desktop width to the entry sheet, which is quicker to copy from.

### The three as presented

| | Style 1: Entry | Style 2: Steps | Style 3: Timeline |
|---|---|---|---|
| Idea | A row of periods, then the selected period as an entry sheet: four figures to copy, the TSW lines, Record as lodged | The selected period as a four-step task list: check setup, check figures, lodge in TSW, record it | Periods as a rail down the left; the selected period beside it as a summary list |
| Taken from | Breww's report; Stripe's filing summary | GOV.UK task list and check answers; Xero's review, file and confirm | Linear cycles; TaxJar's Filings tab |
| Best at | Copying into TSW in one sitting | A first lodgement, or someone who lodges rarely | Seeing the backlog and history at a glance |
| Gives up | History beyond the chips is a scroll; the setup is quieter | Takes more height; the period is a dropdown, so the backlog isn't visible | Needs width: on a phone the rail becomes chips |

All three share:
- the header ("Customs", a one-line purpose, Licences link);
- statuses in words, with months before reminders folded into "N earlier months · Not tracked";
- landing on the oldest unlodged period since reminders began;
- the TSW entry lines and the four figures;
- Copy buttons on each figure;
- links to Trade Single Window and to the period's sales (Sales → Excise);
- the setup folded into four disclosures (Products and rates, Stock outside the licensed area, Lodging and reminders, Movements by licensed area);
- "Records for Customs", with the form behind "Add a record".

## Changes to data (stated, not hidden in the redesign)

- **The draft gains an `entry`**: one line per product under its excise item, with litres
  and LAL to 3 dp, rate, basis, duty, levy and GST on the levy, then the totals.
  - Each line is rounded on its own. Whistlebird's lodged September 2026 entry (duty 2244.10,
    levy 18.21, GST 2.73, total 2265.04) is reproduced exactly; merging the two gins into one
    line would give a levy of 18.20.
  - The entry is saved in the lodged snapshot. Periods lodged before this change show their
    saved per-product lines, labelled as such.
- **Reminders are on by default** from the month the NZ Alcohol module was switched on, or from
  "Remind me from" when set. Before, nothing was raised until someone set that date.
  - The reminder's title carries the estimate ("…: est. $1,769.00 (24.696 LAL)").
  - Its one action, "See the figures", opens Sales → Excise for that month, or this page on
    that period when lodging isn't monthly or Sales is off.
  - Sales → Excise links back with "Lodged it? Record it in Customs →".
- The periods API adds `period_end` and `settings.reminders_from`.

## Not in this change

- The CCA movement review's logic and the per-CCA multi-site path (only moved into a disclosure).
- The evidence record API and compliant.js.
- Credit notes and duty credits; the entry has no duty-credit line yet (Breww keeps it separate
  because TSW has its own field).

## Checks

- `tests/test_excise.py`:
  - entry lines in TSW order reproduce the lodged entry;
  - a lodged period keeps its entry;
  - reminders default on and link to the figures;
  - the periods API says when reminders start.
- `tests/e2e/compliant-platform/test_customs_page.py`:
  - lands on the oldest unlodged period with the entry;
  - recording as lodged locks the period;
  - a `?period=` link opens that period;
  - at phone, laptop and wall width: no sideways scroll, every region present, tiles when wide and the figures list on a phone.
- Screenshots, every pass for all three styles (then pass 10 on the chosen layout):
  - laptop, full page, phone, wall (1920×1080) and dark;
  - a lodged period, setup open, the breakdown open;
  - arriving by the sub-nav, and after recording as lodged.

---

# Customs v2: the entry page alone, with Stock and Settings beside it

October 2026, after !544. The founder asked for:
- the entry page to be the entry and nothing else, with three months in the selector by default;
- units sold in the entry;
- the real Trade Single Window link;
- Records for Customs folded at the bottom as cards;
- setup moved to a Customs settings page and a stock page that explains what a stocktake found.

## What was wrong (`00-before`)

- Four setup disclosures and a data-heavy Records table (Framework · Control · Record ·
  Status · Evidence, showing catalogue ids such as `customs-alcohol` and `period-lodgement`)
  took more of the page than the entry did.
- Seven period chips plus an "earlier months" chip, all at once.
- The entry lines had litres and LAL but not the units sold that people count by.
- Nothing on the page said what the business owes over the year, whether the stocktake was
  due, or what to claim back.
- "Add a place" submitted as a page load: the shell's boosted navigation took the form.

## What the research changes

NZ rules, from the Customs and Excise Act 2018, the Regulations 1996 and customs.govt.nz:

| Rule | What it changes here |
|---|---|
| Duty is owed on goods used inside the CCA (tastings, samples) and on goods destroyed, lost or stolen, not only on sales (Act Sch 3 cl 3; Customs "excise entries") | The Stock page sorts each stocktake difference into **On the excise entry**, **Claim a remission** or **No duty** |
| No allowance for evaporation or wastage; relief only by remission (NZCS 277); damaged goods can be self-remitted if authorised | Breakages show as remissions to claim, on Stock and in the Desk rail |
| Goods that can't be accounted for are charged as removed (s 138); Customs stocktakes have led to prosecution | The stocktake card leads Stock: last count, next due, open differences and the duty they would carry |
| Nil returns are mandatory (Nil Returns Rules 2024) | An empty month says so and offers "Record nil return as lodged" |
| Late payment: 1% the day after it's due, 4% more after 7 days (s 159) | An overdue period states it |
| Six-monthly lodging is allowed up to $100k duty a year and twelve-monthly up to $50k, after 6 months of monthly lodging | Settings and the Desk rail show the last 12 months' duty against those limits |
| TSW has a separate Duty credit field | Returned stock points to it |
| Library or reference stock is duty-unpaid while it is inside the CCA | Stock lists library stock with that note |

Comparable products and patterns:
- **Breww's NZ excise report** keeps duty credit separate.
- **InnoVint** maps loss reasons to report lines.
- **Katana and Lightspeed** stock counts: count, review, a reason per line.
- **Stripe Tax filings** give a period overview.
- **Linear cycles** show periods as rows.
- **GOV.UK summary list and summary card** set out the settings and check cards.

Searched and didn't find:
- a Customs rule on stocktake frequency (the licence-holder guide PDF returned 404);
- a TSW amendment procedure;
- any rule on library stock beyond the CCA's general rules.

## The pages

- **Excise entry** (`/compliant/nz-alcohol/customs`):
  - three period boxes, then Earlier;
  - the entry sheet with Units sold;
  - Record as lodged;
  - TSW sign-in and the month's sales;
  - the breakdown;
  - "where things stand" (to lodge, this period so far, 12-month duty, stocktake);
  - Records for Customs, folded, as one card per check plus the latest records.
- **Stock** (`/customs/stock`):
  - the stocktake and what it found;
  - where stock sits inside or outside the licensed area;
  - library stock;
  - moving stock and adding places;
  - the per-CCA review for multi-site orgs.
  - It reuses the existing stocktake (`/core/stocktake` counts) and the stock-location model; no new tables.
- **Settings** (`/customs/settings`):
  - products, unfinished first, with problems on the entry linking to the row;
  - the built-in rates in force, with their source;
  - lodging frequency and eligibility;
  - stocktake frequency (the stocktake system check).

## The pick

**Chosen (21 Oct 2026): Style 1, Entry sheet.** Four facts above the period boxes and the entry sheet; on a phone the figures read as a list.
- Desk lost because its rail narrows the entry table, the thing people copy from.
- Ledger lost because the entry opened inside a row has less room, and history is less often needed than this month's entry.
- What only Desk showed (lodging eligibility, remissions to claim) is on Settings and Stock.

## Three directions for the entry page (as presented)

| | Style 1: Entry sheet | Style 2: Desk | Style 3: Ledger |
|---|---|---|---|
| Idea | A strip of four facts, the three period boxes, then the entry sheet full width | The entry on the left; a "where things stand" rail with the year's duty, stocktake, lodging eligibility and remissions | Periods as rows (month, status, LAL, total); the selected row opens in place |
| Taken from | Breww NZ entry, Stripe Tax overview | Stripe Tax overview, Linear's side panels | Linear cycles, InnoVint per-period report |
| Best at | Copying one month into TSW | Seeing the whole Customs position while lodging | History at a glance |
| Gives up | Lodging eligibility and remissions are on other pages | A narrower entry table; on a phone the rail goes below | Less room for the entry inside a row |

## Changes to data (stated, not hidden in the redesign)

- Entry lines carry `units` and `unit`. Periods lodged before this show "—".
- Recording a period as lodged also files a `period-lodgement` record (the period, the entry
  reference or "Nil return", the totals in `details`, no due date).
- New `GET /api/compliant/nz-alcohol/excise/position`. The periods API adds each lodged period's total.

## Bugs fixed on the way

- A stocktake "broken" reason committed its wastage record mid-resolution, so a later
  invalid reason left the breakage saved and the line open.
- Stocktake breakage and surplus wrote quantities without a movement or event, so the
  nightly stock check flagged every lot a stocktake had adjusted.
- "Add a place", and every other scripted form on the Customs page, submitted as a boosted page load.
