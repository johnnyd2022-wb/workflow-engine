---
topic: "inventory.sites_and_locations"
title: "Sites and stock locations"
domain: "inventory"
summary: "A site is a physical place of work; a stock location is an area where lots sit, and it matters for excise because it can be inside the licensed area."
related_topics:
  - inventory.stocktakes
  - inventory.availability
  - compliance.excise_periods
  - compliance.cca_movements
related_operations:
  - stocktake_get_stock_position
features: []
---
# Sites and stock locations

## What it means

- A **site** is a physical place the business works at. Every organisation has a default site behind the scenes. Extra sites exist only when multiple sites are switched on, which needs the organisation's plan and its own switch.
- A **stock location** is an area where lots sit, such as the main licensed area, a store or a sales rep's car. A lot with no location is in the **main licensed (Customs-controlled) area**, where everything was before locations existed.
- Each location says whether it is `inside_licensed_area`. Moving stock from inside to outside is a removal for excise. A site's locations have unique names within the site.

## How the records relate

- Lots, batches and locations carry a site. A lot's location must belong to the lot's site.
- Production uses the batch's own site. Sales matching uses the shipping site, which is the default site unless one is given.
- A transfer moves part of a lot to another place as a new lot with the same lineage.
- With several sites, each CCA licence lodges its own excise entry. A removal belongs to the licence that covered the stock's place on the day it left.
- Planning is per site, and cover figures take a `site_id`.

## Authoritative operations

`stocktake_get_stock_position` gives finished and in-progress stock by place and batch, with each place's `inside_licensed_area` flag and, for an installed compliance module, its measure such as litres of alcohol.

## Do not assume

- **No location does not mean unknown.** It means the main licensed area.
- **Outside the licensed area is not "sold".** Stock moved outside has left for excise purposes and may still be in the organisation's hands.
- **Extra sites need the plan.** Working at an additional site needs the plan's multi-site entitlement as well as the organisation's own switch. Without both, stock and batches are refused there.
- **A site is not a CCA licence.** A licence can cover several sites, and a site can have none.
- **The stock position excludes raw material.** It lists finished and in-progress lots only.
