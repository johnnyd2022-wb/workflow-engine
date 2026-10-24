# Sales settings page design

Sales settings (`/crm/configuration`) is where an admin decides:
- how Xero invoices are matched to batches;
- which Xero lines are which products;
- whether customers created in Biz-E go to Xero;
- what the Sales overview shows.

**What the page is for, in one sentence:** *what is Sales set to, and how do I change one thing without disturbing the rest?*

This is one of the settings pages redone together (plan 2.5: "reduce each form to its own card with one save button"). The Settings tab row itself is !562.

## What is wrong today

Observed in `00-before`, on main `bf069927`:

- **The title** says "Configuration" under a "Sales settings" breadcrumb. The section headings are in small capitals ("SALES TRACEABILITY"), and labels are in Title Case ("Manual Review Window (days)").
- **Every field runs the full width of the page.** A one-number field such as "archive after 7 days" stretches across 1,000 pixels.
- **Three Save buttons send the same form.**
  - "Save Traceability Settings", "Save Task Settings" and "Save Revenue Settings" all call one function that sends every value.
  - So saving Tasks also saves a half-typed revenue target. *(Bug, fixed.)*
- **One checkbox saves the moment it is ticked.**
  - "Send customers created in Biz-E to Xero" saves as soon as it is ticked, and doing so sends waiting customers to Xero.
  - It is the only setting on the page that does that.
- **The Xero card repeats Settings › Integrations.** Integrations redirected here whenever Sales was on, so Xero had no single home (fixed in !562).
- **The mapping form takes the bottom third of the page**, open all the time, above the mappings it creates. The list itself is a row of badges with raw words such as "exact" and "active".
- **Everything loads twice.** `x-init="init()"` runs on top of Alpine's own `init()` call. *(Bug, fixed.)*
- **A failed load shows the defaults** (FIFO, 7 days, nothing hidden) as if they were the settings, and saving them would overwrite the real ones. *(Bug, fixed.)*
- **The Xero warnings** read a second copy of the connection status, so they could contradict the card above.

## What other products do

Read 25 October 2026. The research decides the structure only. The house style decides how it looks.

| Source | Pattern | What it changes here |
|---|---|---|
| [Primer, saving](https://primer.style/ui-patterns/saving) (pattern, GitHub) | Start with explicit saving. Don't mix explicit and automatic saving in one form. Its rule of one Save per page is taken from Style 2 only. Confirm a save inline when the page doesn't redirect | Every section saves with a button (the old automatic checkbox now has a Save). Style 1 keeps a Save in each section; Style 2 has one bar. "Saved." appears inline |
| [Polaris contextual save bar](https://polaris-react.shopify.com/components/deprecated/contextual-save-bar) (pattern, Shopify) | One bar appears when anything is unsaved and saves or discards the whole page. For sections edited independently, an Edit button opens that section | Style 2's bar; Style 3's Change per section |
| [GitLab settings research](https://gitlab.com/gitlab-org/ux-research/-/issues/1215) (pattern, a usability study) | Participants found side-by-side content made everything look in place. The add or edit form in a modal was preferred. The recommendation: show less content at first | Style 2 side by side; "Add a mapping" in a dialog; Style 3 shows values first |
| [GOV.UK summary list](https://design-system.service.gov.uk/components/summary-list/) (pattern) | Key and value rows, with a Change link per row that names what it changes | Style 3's rows and its labelled Change buttons |
| [Linear, members](https://linear.app/docs/members-roles) and [Stripe, team](https://docs.stripe.com/dashboard/teams) (craft) | Settings is a list of short, named sections. Rare actions sit behind a row's menu | Fewer, plainly named sections; Delete is a quiet link on the row |
| [Katana, connecting Xero](https://support.katanamrp.com/en/articles/5968153-connecting-xero) (comparable, MRP) | Xero is connected from Settings › Integrations, not from a module's own settings | Sales settings shows the Xero connection and links to Integrations (plan 2.5) |
| [Breww, duty settings](https://breww.com/docs/duty-settings/) (comparable, brewery software) | One settings page per regime, reachable from the main settings and from the dashboard it configures | Sales settings stays in Sales, beside the work it configures, rather than moving under Settings |

**Looked for but not found:**
- Vercel's docs don't say whether each settings card has its own Save. The only claim found was a third-party tutorial, which isn't used here.
- I found no comparison of the three approaches for manufacturing-software settings. Which works better here is a judgement, not a finding.

## Three directions to choose from

| | Style 1: Cards | Style 2: Side by side | Style 3: Read first |
|---|---|---|---|
| Idea | One card per section: title, a line on what it's for, its fields, its own Save | The title and its explanation on the left, the fields in a card on the right. One save bar appears when anything has changed | Each section shows what's set as rows. **Change** opens that section's fields in place, with Save and Cancel |
| Taken from | Customs settings (!549), Primer's explicit save | Polaris's save bar, GitLab's side-by-side finding, annotated settings layouts | GOV.UK summary list, Polaris's Edit per section |
| Best at | Changing one thing; looks like Customs settings | Changing several things at once and saving them together | Checking what's set without a page of inputs; hard to change something by accident |
| Gives up | Every input on show, so the page is long | A wide screen to work well; the bar can be missed on a phone | A click before any change |

**What all three share:**
- **The sections**, in this order: Xero, Product mappings, Matching sales to batches, Customers created in Biz-E, Revenue on the overview, Sales tasks.
- **Plain words:**
  - "Automatically, oldest batch first", not "FIFO Auto-Match";
  - "Not seen lately", not "stale".
- **Matching strategy** is three described choices instead of a dropdown with a hint that changes. The review window only appears for the strategy that uses it.
- **Fields sized to what goes in them.**
- **Xero** shows the connection, the last sync, Sync now, and **Manage connection** (Settings › Integrations).
- **Product mappings:**
  - the mappings are a list;
  - **Add a mapping** opens a dialog that keeps "Add another" and the list to save;
  - the overview's "Map" link opens that dialog with the line already chosen;
  - Delete asks first.
- **Saving:**
  - each section saves only itself, and a failed save shows its error inside that section;
  - the "send customers to Xero" setting saves with a button like everything else.
- **A failed load** hides the settings and offers **Try again**.

Try them with `?style=1`, `?style=2` or `?style=3`, or the dashed Concept switch under the header.

## Not in this change

- **APIs:** `PUT /api/crm/traceability-config` still takes every field. The page sends the saved values plus one section's draft.
- **Calculations and exports:** unchanged.
- **Follow-ups:**
  - Sales tasks' archive setting (days, here) and Production's Task settings (days, weeks or months) are two separate settings for two task boards. Merging them is a product decision.
  - The double `x-init` on Analytics, Batch matching and Excise.

## Checks

- `tests/e2e/test_sales_settings_page.py`, routed into the Flask test client:
  - one load;
  - a section saves only itself;
  - a failed load can't be saved over;
  - the Map link opens the dialog;
  - CONCEPT ONLY: Style 3 changes in place, Style 2's bar saves every changed section, and each layout fits at phone, laptop and wall widths.
- `tests/js/crm-configuration.test.js`: per-section saving and discard.
- `test_crm_contact_sync_ui.py`: the Sales-wide default now needs Save.
- Shots: laptop, phone, wall and dark, for a busy org (Xero connected, four mappings) and a quiet one. Also editing, saved, both dialogs, the save bar, arriving by a boosted link and by the Map link, and a failed load.
