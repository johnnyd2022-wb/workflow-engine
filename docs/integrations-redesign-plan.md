# Integrations page design

Integrations (`/core/integrations`, Settings › Integrations) is where Xero is connected, synced and disconnected. Until !562, it redirected to Sales settings whenever Sales was on.

**What the page is for, in one sentence:** *is our accounting software connected, and is it up to date?*

## What is wrong today

Observed in `00-before`, on main `bf069927`:

- **Nobody saw it:** with Sales on, it redirected to Sales settings (fixed in !562).
- **Styling:** inline styles throughout, a hard-coded white logo tile (white in dark mode), and Title Case ("Sync Now").
- **Disconnect** used `window.confirm`.
- **Loads twice:** `x-init="init()"` on top of Alpine's own call loads the status twice. *(Bug, fixed.)*
- **Failed connections are silent:** every Xero OAuth failure redirected to `/crm/configuration?error=…`, and nothing reads `?error=`, so the failure was never explained. *(Bug, fixed: the redirects come here, and the page says why in words.)*

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

| | Style 1: Cards | Style 2: Side by side | Style 3: Connected and available |
|---|---|---|---|
| Idea | A card per integration: who it is, its status rows, its actions | Who it is on the left, the connection on the right | "Connected" first with its details; "Available" below as short rows |
| Taken from | Customs settings (!549) | Annotated settings layouts, GitLab's study | Katana's Integrations Marketplace |
| Best at | Plain and matches the other cards | Matches Sales and Compliance settings Style 2 | Scales when more integrations arrive |
| Gives up | Repeats a lot of card for "coming soon" | A wide screen | A heading change when the state changes |

**Shared by all three:**
- Status in words (Connected, Not connected, Needs reconnecting).
- The organisation, the last sync, and contacts and invoices in Biz-E.
- **Sync now**, **Sales settings**, and **Disconnect**, which asks in the page.
- A failed connection explained in words.

## Not in this change

APIs. The OAuth routes change only where they redirect on failure.

## Checks

- `tests/e2e/test_integrations_page.py`: one status load; a failed connection says why, and the redirect comes here; Disconnect asks in the page; CONCEPT ONLY: each layout fits at phone, laptop and wall widths.
