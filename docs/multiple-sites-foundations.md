# Multiple sites: first implementation slice

This delivers the configuration and tagging foundations for plan 7.1a/b. It does not
complete either the multi-site operations or staff-site restrictions in 7.1.

## Available now

- Organisation setting `multiple_sites_enabled`, default false.
- An admin's Sites page from Settings: switch on/off, add and edit sites, select the
  default before operational data exists, and archive/restore additional sites.
- Existing stock, executions and stock locations are tagged to a structural default
  site. An org created later gets the same structural default, even while the opt-in
  is off. The setting controls visibility; internal tags preserve stock continuity.
- The migration backfills existing rows. Enabling also fills any legacy null tags.
- New stock, executions and locations inherit the default tag. Same-org composite
  foreign keys protect their references; stock/location and stock/execution site
  agreement is validated on ORM writes. Existing tags cannot be edited as a move.
- `GET /api/core/sites/<id>/position` gives stock totals grouped by type and unit.
  Repository inventory/execution lists accept an optional `site_id` filter.

Existing production, stock, FIFO, stocktake and excise behavior continues. Existing
outside stock locations keep their licensed-area flag; this slice creates no licence
or regulatory registration.

## Staged operations

Additional sites can be configured but cannot receive stock or start executions yet.
Requests naming them are rejected before older operational routes can ignore the site
hint. The flush guard also rejects direct repository/ORM writes at additional sites.
The default cannot change once stock, locations or executions exist. Switching the
setting off hides the register and retains its tags and history.

This is intentional: additional-site operations become available only when production
input selection, FIFO/manual allocation, stocktakes, transfers and module enforcement
all enforce their scope. This slice does not provide a transfer or retagging shortcut.
Per-site UI filters, whole-business reports and role site restrictions remain pending.

## Interfaces and ownership

- Core: `Site`, `Organisation.multiple_sites_enabled`, optional `site_id` on
  `InventoryItem`, `Execution` and `StockLocation`; generic flush validation.
- Sites feature: register/settings routes and UI. Viewing needs stock or production
  access; management needs `settings.manage`. Position totals need `inventory.view`.
- Inventory/execution repositories: optional `site_id` at creation and listing.
- Compliant modules will own registration mappings and stock-movement requirements.
  A CCA may cover several sites; a site may have no CCA. No Core code imports an
  industry module or decides duty from a site kind.
- Contract orders and the planner may read execution tags. They must not use their
  associations to retag existing executions or bypass staged site operations.

`multiple_sites_001` is initially based on `custom_roles_001`. The parallel Google,
contract-order and planner migrations must be restacked into one Alembic chain before
merging. Downgrade refuses enabled or additional-site configuration rather than losing
it silently.

## Customs question before the movement slice

The plan's blanket prior-approval wording needs reconciling with [Customs' published
movement guidance](https://www.customs.govt.nz/business/excise/alcohol-and-excise/moving-products-excise-unpaid),
which lists permitted categories and requires prior approval for others, including
off-site storage. The founder/Customs policy review must settle this before 7.1e.
This foundation changes no duty rule or approval requirement.

## Validation

Tests cover default-off behavior, compatibility backfill, quantity preservation,
tenant isolation, admin permissions, strict field validation, default/archiving rules,
explicit site hints, direct ORM/repository bypasses, database foreign keys, per-site
position, concurrent first-stock/default switching and a populated-schema migration
upgrade/downgrade/upgrade. The selected stock, execution, stocktake, excise, sales
traceability, reconciliation and permission regressions pass (129 tests).

Chromium checks Settings navigation, opt-in, creation/editing/archiving, reload and
opt-out at 1280px and 390px, with no horizontal overflow or JavaScript errors. JSON
forms and the Settings entry opt out of the shell's HTMX navigation boost.
