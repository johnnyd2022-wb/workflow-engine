# Sites page design

Sites (`/core/sites`, Settings › Sites) switches multiple sites on and keeps the list of places: name, kind, address, the default, and archived sites.

**What the page is for, in one sentence:** *where do we work, and which place is the default?*

Part of the settings pages done together (plan 2.5). It sits under the Settings tab row from !562.

## What is wrong today

Observed in `00-before`, on main `bf069927`:

- **Styling:** inline `<style>`, an old "Settings" back button, and the older green primary button.
- **Every site is a full edit form**: name, address and kind inputs, plus Save, Make default and Archive as three equal buttons. With four sites, the page is four forms.
- **"Add site" is a fifth form** at the bottom.
- **The status text** always says recording at other sites "will become available", even after it has been switched on for the organisation. *(Bug, fixed.)*
- **A refused change** (a duplicate name, say) shows at the top of the page, away from the form.
- **A failed load** left the switch disabled, with no way to retry. *(Fixed.)*

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| [Katana, locations](https://support.katanamrp.com/en/collections/3335394-settings) and [MRPeasy, sites](https://www.mrpeasy.com/resources/user-manual/settings/) (comparable) | Locations are a Settings list: name, address and type, edited from the list | Rows of name, kind and address; Edit opens the fields |
| [Shopify, locations](https://help.shopify.com/en/manual/locations) (craft) | A list of locations with a default, plus "Add location"; deactivating a location keeps its history | "Default" and "Archived" tags; Archive and Restore, never delete |
| [Linear, members](https://linear.app/docs/members-roles) and [Stripe, team](https://docs.stripe.com/dashboard/teams) (craft) | Short rows with quiet actions in the row | Edit, Make default and Archive as text actions; Archive in red |
| [GitLab settings study](https://gitlab.com/gitlab-org/ux-research/-/issues/1215) (pattern) | Add and edit in a modal; show less to begin with | The add and edit dialog in Style 1; edit in the row in Style 3 |

**Looked for but not found:** Shopify's own docs were not opened (the help-centre link is from memory of the product), so treat that row as a judgement rather than a finding.

## Three directions to choose from

| | Style 1: List | Style 2: Tiles | Style 3: Edit in place |
|---|---|---|---|
| Idea | One row per site; Edit and Add open a dialog | A tile per site, plus a tile to add another | The same rows; Edit opens the fields in the row itself |
| Taken from | Katana and MRPeasy locations, GitLab's modal finding | Shopify locations | GOV.UK summary list, edit in place |
| Best at | Looks like the other Settings pages | A few sites, at a glance | Quick changes without a dialog |
| Gives up | A dialog for every change | Long addresses wrap; more space per site | Rows jump in height while editing |

**Shared by all three:**
- A "Multiple sites" card that says plainly what on and off mean, and whether other sites can record work yet.
- **Add a site** in the header once multiple sites is on.
- A summary line ("3 active sites · 1 archived").
- A refused save keeps its reason in the dialog or the row.
- A failed load hides the switch and offers Try again.

## Not in this change

- **APIs and the rules for switching off:** unchanged.

## Checks

- `tests/e2e/test_sites_page.py`, routed into the Flask test client: switching on, a refused site, the status text, a failed load; CONCEPT ONLY: edit in place, and each layout fits at phone, laptop and wall widths.
- Shots: off, on with four sites (one archived), editing, a refused add, dark, a failed load, arriving by the Settings tab.

## Approved implementation — 25 Oct 2026

Style 1 (List) is the approved design for !566. The experimental layout selector and the discarded layouts have been removed.

Validation: 7 browser cases passed, covering the page actions and responsive layouts. Security scan of the changed app files passed.
