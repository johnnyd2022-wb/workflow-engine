# Contract order foundation (7.2a)

Staff manage customers and orders at **Contract orders** in the navigation. A customer
can exist without Xero; an optional CRM link points to a contact in the same organisation.
Orders have one or more product lines, a due date, and a commercial status. Confirm an
order before production staff link batches to its lines. Each batch belongs to at most
one line; a line can have several batches. Shared production across several lines needs
a later explicit allocation model.

Materials are declared per line (producer, customer or mixed). Duty responsibility is
declared per order (producer licensee, customer licensee or underbond to the customer's
CCA); either customer option needs a CCA reference. These declarations do not change
inventory ownership, availability, removals or excise calculations. Those behaviours
remain 7.2b/c and depend on the site/movement compliance seam.

Sales staff manage commercial demand and CRM links. Production staff see order demand
and link batches, but cannot list CRM contacts or change commercial orders. Specification
and recipe references are available only with production.view, including on writes.
Auditors may read. Existing permission sets and custom roles apply; no external user
identity or customer portal is introduced.

Once a batch is linked, its line's product/material/specification declaration and the
order's duty declaration cannot be edited. A batch whose work has started cannot be
unlinked after a completed step. Completed and cancelled orders retain their history.
Only an order with completed linked batches can be marked completed.

## Scheduling interface

`app.features.contract_manufacturing.services.demand.contract_demand(db, org_id)`
returns confirmed order lines. `demand_id` is the stable line UUID. Each row has order
and customer IDs, quantity/unit, due date, material source, workflow/version references
and linked execution IDs. `product_key` is the selected workflow output UUID, or null
when the order is not mapped. Never match an unmapped product by name.

Demand is gross quantity: the planner must reconcile trusted allocation, stock and WIP
snapshots without counting a linked batch twice. Planned and forecast ready dates are
null until the planner supplies them; the due date is not a forecast.

The additive migration `contract_orders_001` follows `custom_roles_001`. Existing
customers, stock and executions are not inferred or backfilled into contract orders.
The portal, record sharing, progress milestones and cross-org links remain separate
deliveries. Rollout follows the second-producer pilot.
