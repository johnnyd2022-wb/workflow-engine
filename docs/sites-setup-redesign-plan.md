# Sites: from a settings list to the multi-site home (GL-P07 A2)

**What the page is for, in one sentence:** *where we work, what is at each place, and what is left to set up.*

Settings → Sites (`/core/sites`). The Sites list from !566 (Style 1, "List") was a register of names and addresses: right for a settings page, but with multiple sites now usable (A1, !597) the page is where a business sets up and checks its places, so it has to show what is *at* each site and walk the first setup.

## What is wrong today (00-before)

- **It says nothing about what is at a site.** Name, kind and address only: no stock, no batches, no areas. You can't tell the bond store from an empty record.
- **Stock areas live nowhere.** Areas (tank bay, dry store) can only be made through an API; the page has no way to add or see them, so stock can't be placed inside a site.
- **No setup path.** Switching on drops you at a one-row list with no sense of what to do next (add sites, choose the default, name areas, check licences).
- **Compliance is invisible.** Whether a site is inside a Customs-licensed area (duty suspended) or duty-paid is only on the Customs licences page, two sections away.
- **The plan gate is invisible.** A business without the multi-site plan saw a switch that then refused.

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| [Katana, locations and default locations](https://support.katanamrp.com/en/articles/5966915-choosing-default-locations-for-sales-manufacturing-and-purchasing) (comparable) | Each location says whether it sells, makes and/or buys; one default per kind of work; the main location is the default until changed | Each site has a kind; one default, stated plainly as "where anything recorded without a site goes" |
| [Shopify, locations](https://help.shopify.com/manual/locations/setting-up-your-location-fulfillments) (craft) | A Default tag; the default is changeable at any time; fulfilment follows a priority list | "Default" tag; Make default on any active site, explained in the confirmation |
| [InnoVint, bond-to-bond transfers](https://support.innovint.us/hc/en-us/articles/360018542692-bond-to-bond-transfers) (comparable) | Bonds are first-class places inside the winery account | The site card says which bond it is under, from the Customs register |
| [Ekos case studies: multi-location breweries](https://www.goekos.com/success_story/wiseacre-brewing-co/) (comparable) | "Know exactly where each product is" across locations | Stock lines and batches under way on every site card |
| [GOV.UK task list](https://design-system.service.gov.uk/patterns/complete-multiple-tasks/) (pattern) | A numbered list of tasks with status, completed ones staying listed | The "Setting up" steps (Styles 1 and 2) and Style 3's rail |

**Looked for, not found:** a competitor that shows Customs/bond status on its location list. InnoVint treats bonds as places but documents the transfer, not a location overview. That is the 10x: the site card says, from the register, whether stock there is under bond.

## Three directions

| | Style 1: Site cards | Style 2: Register and panel | Style 3: Guided setup |
|---|---|---|---|
| Idea | A card per site: figures, areas, Customs status and actions; "Setting up" above until done | A compact table of sites with figures; the chosen site's detail and actions beside it | The setup steps are the page: a rail of steps, each showing the sites through that lens (areas, licences) |
| Taken from | Shopify locations, Ekos | Katana locations, Linear lists with detail | GOV.UK task list |
| Best at | Two to six sites at a glance | Many sites; comparing figures | The first setup, and checking one thing across every site |
| Gives up | Long lists scroll | A click to see a site's areas | Less at a glance once set up |

**All three share:** the plan and off states as one plain card (what turning on does, or that it isn't in the plan); Add a site in the header; add an area to any site; Make default with what it means; Customs status from the compliance module (core never names it); the summary and a quiet "Switch multiple sites off" in the footer.

## Not in this change

- **APIs:** `GET /api/core/sites` gains each site's stock lines, batches under way, areas, and notes from the compliance module (`app/features/compliant/platform/site_notes.py`). Nothing else changes.
- **Area names stay unique across the business** (`uq_stock_locations_org_name`). Two sites can't both have a "Dry store" yet; the page names the site that already has it and suggests a name. Per-site names need every location shown by name elsewhere (Inventory, moves, stocktake) to show its site too, which is A3's site lens, so the constraint changes there.
- **Follow-ups:** the site picker on add-stock screens and the site lens (A3); moving stock (A4); per-CCA excise (A5).

## Checks

- Browser: off/not-in-plan, switch on, add a site, add an area, make default, figures and Customs status per site, a failed load; CONCEPT ONLY layout checks for the three styles at phone, laptop and wall.
- Shots: busy multi-site org, a plain org without the plan, phone, wall, dark, the dialogs, arriving by the Settings tab.
