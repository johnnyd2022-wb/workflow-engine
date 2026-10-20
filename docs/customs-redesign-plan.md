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
