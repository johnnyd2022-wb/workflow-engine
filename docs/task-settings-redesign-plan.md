# Task settings page design

Task settings (`/core/tasks/configuration`, Settings › Tasks) decides when Production tasks appear in Notifications before they are due, and how long finished tasks stay on the board.

**What the page is for, in one sentence:** *when do I hear about tasks, and when do finished ones get out of the way?*

## What is wrong today

Observed in `00-before`, on main `bf069927`:

- **Layout:** one card with a horizontal rule between two subjects, one Save for both, and a "Back to tasks" button.
- **Fields stretch** across the card.
- **No sign a save worked.**
- **Loads twice:** `x-init="init()"` on top of Alpine's own call. *(Bug, fixed.)*
- **A failed load keeps the defaults on screen**, and saving them overwrites the real settings. *(Bug, fixed.)*

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

The same three as Sales settings (!563) and Compliance settings (!564), so the settings pages can match: **Cards** (a Save per section), **Side by side** (one save bar), and **Read first** (Change opens a section).

## Not in this change

- **API:** unchanged.
- **Follow-up:** Sales tasks' own archive setting is in Sales settings (days only). Two task boards, two settings; merging them is a product decision.

## Checks

- `tests/e2e/test_task_settings_page.py`: one load; a section saves only itself; a failed load can't be saved over; CONCEPT ONLY: Read first changes in place, and each layout fits at phone, laptop and wall widths.

## Approved implementation — 25 Oct 2026

Style 1 (Cards) is the approved design for !568. The experimental layout selector and the discarded layouts have been removed.

Validation: 6 browser cases passed, covering the page actions and responsive layouts. Security scan of the changed app files passed.
