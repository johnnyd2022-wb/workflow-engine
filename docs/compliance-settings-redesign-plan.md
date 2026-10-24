# Compliance settings page design

Compliance settings (`/compliant/nz-alcohol/configuration`) decides which obligations apply: NZ Alcohol on or off, what leaves the site, the food safety programme (NP1, NP2 or NP3) and its review and evidence rules, the next verification visit, the liquor licence, trade waste, evidence records, and which products need an ABV.

**What the page is for, in one sentence:** *which obligations has this organisation switched on, and how do I change one without touching the others?*

One of the settings pages done together (plan 2.5). Sales settings is !563, the Settings tab row !562.

## What is wrong today

Observed in `00-before`, on main `bf069927`:

- **A marketing headline for a title** ("Switch on only the obligations that belong to your operation.") under a small-caps eyebrow, instead of the house header.
- **One long form with one Save** at the bottom, mixing seven subjects: products, programme, verification visit, licence, review reminder, evidence capture, trade waste.
- **The ABV rules are a second form below**, with their own Save, in a bordered table.
- **Fields are full width** and paired in a grid, so a date sits beside a free-text name at the same width.
- **A failed load leaves the form on screen**, with Compliance unticked and the defaults showing. One Save then switches Compliance off. *(Bug, fixed.)*
- **The Licensing tab** didn't follow a change to the licence until the next page load. *(Fixed: it now shows or hides on save, as the food safety tab already did.)*

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
| Idea | One card per subject, each with its own Save | Title and explanation on the left, fields on the right; one save bar appears when anything changes | Each subject shows what is set; **Change** opens its fields in place |
| Taken from | Customs settings (!549), Primer's explicit save | Polaris save bar, GitLab settings study | GOV.UK summary list |
| Best at | Changing one thing; matches Customs settings | First set-up, changing several things at once | Checking what's switched on before an audit; hard to change by accident |
| Gives up | Every input on show; the longest page | Needs a wide screen; the bar can be missed | A click before any change |

**Shared by all three:**
- Eight sections, in this order: NZ Alcohol compliance, What leaves your site, Food safety programme, Next verification visit, Liquor licence, Trade waste, Evidence records, ABV on alcohol products.
- **Each section saves only itself.** It sends the saved profile with that section's fields on top, so keys set elsewhere (a check's own review interval, Customs and stocktake settings, the ABV rules) are kept.
- Products and licence kinds are chips; the evidence mode is three described choices.
- The review interval, evidence mode and step preview only show for a national programme, and the visit section is hidden when there is none.
- ABV: one row per workflow's final product, with phrases below; a product covered by a phrase is ticked and locked, and says which phrase.
- A failed load hides the settings and offers **Try again**.

## Not in this change

- **APIs:** `PUT /api/compliant/profile` still replaces `settings` wholesale; the page sends the saved settings plus one section. `PUT /abv-rules` unchanged.
- **Follow-up:** the server could merge settings itself, so a client that forgets a key can't drop it.

## Checks

- `tests/e2e/test_compliance_settings_page.py`, routed into the Flask test client: a section saves only itself and keeps a check's review interval; choosing a licence shows the Licensing tab; a failed load can't be saved over; the visit section follows the programme; CONCEPT ONLY: Style 3 changes in place, Style 2's bar saves every changed section, each layout fits at phone, laptop and wall widths.
- Shots: laptop, phone, wall and dark, busy (visit booked, licence, council) and quiet; editing; no national programme; saved; the save bar; arriving from the Compliance overview; a failed load.
