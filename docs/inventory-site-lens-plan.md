# Where stock is: site picker and Inventory site lens (GL-P07 A3)

**What it is for, in one sentence:** *stock is recorded where it actually is without anyone thinking about it, and Inventory shows what is where.*

A1 (!597) put multiple sites behind three gates; A2 (!598) made Settings → Sites show what is at each site. Nothing that adds stock asked where it was going, so everything still landed on the default site, and Inventory couldn't say where a line was.

## What is wrong today

- **No add flow asks where.** Manual, barcode, CSV, opening stock, customer materials and starting a batch all put stock on the default site. The API accepted `site_id`; no page sent it.
- **Inventory can't say where a line is.** No site, no area, and no way to see one site's stock.
- **Two sites can't both have a "Dry store".** Area names were unique across the business (deferred from A2).

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| [Cin7 Core, Product Availability](https://help.core.cin7.com/hc/en-us/articles/9034522979343-Product-Availability-Report) (comparable) | Stock by location, consolidated into one figure when the location column is hidden | A "Where" column only with several sites; grouped rows split by site |
| [Shopify, inventory at multiple locations](https://help.shopify.com/en/manual/products/inventory/setup/multi-managed-inventory) (craft) | Per-location quantities with an aggregated total | "All sites" as the default view, each site one step away |
| [Katana, basics of locations](https://support.katanamrp.com/en/articles/5966920-basics-of-locations) (comparable) | Stock tracked per location on the Stock screen; default location per kind of work | A default site, and the picker opens on it |
| [SaaS workspace switcher patterns](https://www.saasui.design/blog/saas-workspace-organization-switcher-ux-patterns) (pattern) | Always show the current scope; don't make people open the switcher to find out where they are | The count line says "at Seaview bond store"; Style 3's choice is remembered |

**Looked for, not found:** documentation of a location filter control on Katana's Stock screen, or of an "All locations" selector on Shopify's Inventory page; the sources describe per-location figures, not the control.

**Our 10x:** nobody normally chooses a site. Every add form opens on where *you* last worked (else the default), and a single-site business sees nothing new at all.

## Three directions for the Inventory lens

| | Style 1: Site tabs | Style 2: Site filter | Style 3: Site cards |
|---|---|---|---|
| Idea | A tab per site, with counts, above the stock list | Site is one more filter beside Supplier and Process, with a chip | A card per site in "At a glance" (lines, expired, expiring); the choice is remembered |
| Taken from | Shopify location views | Cin7 availability columns, the existing filter bar | Workspace switchers |
| Best at | Two to five sites; one click | Many sites; combining with other filters | Comparing sites before choosing; people who work at one site |
| Gives up | Long names crowd at many sites | Less visible; a filter is easy to forget | More height above the list |

**All three share:** a "Where" column (site · area; just the area once a site is chosen), grouped rows split by place, "Where" in the detail panel, the site in the URL, and no change at all for a single-site business.

## The site control on add flows

One shared control (`app/ui/shared/site-picker.js`) on manual add, barcode scan, CSV import (one site for the file; a **Site** column overrides it per row), opening stock ("Counting at"), customer material receipts ("Received at") and starting a batch ("Made at"). It opens on the site you last used, otherwise the default, and is never shown while multiple sites are off. The step modal that starts a batch uses the remembered site.

## Data changes

- `GET /api/core/sites/choices` (new, any member who reads stock or batches): active sites with their areas, the default, and whether anything can be chosen.
- `GET /api/core/inventory`: each line gains `site_id`, `location_id`, `location_name`; `?site_id=` narrows the list.
- CSV validate/commit: optional `Site` column; commit takes a file `site_id`.
- `POST /api/core/opening-stock` and `POST /api/core/inventory/csv-commit` accept `site_id` (validated like every other site hint).
- Migration `site_area_names_001`: area names unique within a site (`NULLS NOT DISTINCT`, so unsited areas still share one name space). Downgrade refuses, without renaming, while two sites share a name.

## Not in this change

- A site lens on Production, Planner and Home (the planner work, B1–B5, scopes by site).
- Moving stock between sites from the detail panel (A4).
- Licensed status from the Customs register instead of each area's flag (A5).

## Checks

- Unit: choices and their gates; where each line is and the site filter; CSV file site, row site, unknown site, site column while off; opening stock site; per-site area names; the migration round trip in an isolated schema.
- Browser: a single-site business sees nothing new; where each line is and narrowing by tab (kept in the URL); the add form opens on the site last used; CONCEPT ONLY fit for each style at phone, laptop and wall.
