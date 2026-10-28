# Step timing in the workflow editor

## What the page must answer

For each production step, the maker needs to say how long hands-on work takes and how long the batch waits before the next step. These values feed the planner without a second entry. Timing is optional for workflows that are not yet being planned, and an explicit zero is different from leaving a value unset.

## What other products do

| Source | Pattern | Decision here |
|---|---|---|
| [MRPeasy routing](https://www.mrpeasy.com/resources/user-manual/stock/items/details/routings/) | Keeps operation time on the routing and separates active work from passive waiting or drying. | Put work and wait on the workflow step, side by side. |
| [Katana production operations](https://support.katanamrp.com/en/articles/5967108-how-to-create-production-operations) | Stores operation time on the product's production operations. | Let the planner inherit the workflow values and keep a setting snapshot for existing plans. |
| [Odoo work centres](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/advanced_configuration/using_work_centers.html) | Plans from operation durations attached to manufacturing routing. | Keep time near the step definition rather than adding another planner-only form. |
| [Linear issue properties](https://linear.app/docs/issue-properties) | Secondary fields can be edited in context without dominating the primary task. | Keep timing subordinate to the step name and description. |
| [Shopify variant editing](https://help.shopify.com/en/manual/products/variants/edit-variants) | An item-specific edit surface carries details without a separate workflow. | Use a compact per-step editor. |
| [GOV.UK text inputs](https://design-system.service.gov.uk/components/text-input/) | Give the value a visible label and make the unit explicit. | Each time has its own label and adjacent unit selector; validation names the allowed range. |

No comparable product documentation found a compelling reason to require timing for every workflow; this remains optional until a workflow is configured for planning.

## Three directions to choose from

| | Style 1: Fields | Style 2: Sentence | Style 3: Timeline |
|---|---|---|---|
| Idea | Two aligned labelled inputs | A readable work-then-wait sentence | A small proportional work/wait bar leading the inputs |
| Taken from | MRPeasy, GOV.UK | Linear, Shopify | Odoo planning, MRPeasy |
| Best at | Quick, precise entry | Explaining the sequence to first-time users | Seeing work and idle time at a glance |
| Gives up | Less visual storytelling | Less compact on narrow screens | Relative widths are illustrative, not a schedule |

All three store the same whole-minute values, support minutes through weeks, distinguish blank from zero, display a total, and inherit the app's colour tokens. The concept switch exists only for review.

## Behavior and follow-ups

Changing a step's timing makes an existing planning setting stale. The planner should show the new workflow values when the timing itself changed, while retaining valid planning overrides when the workflow has not changed. Fixed shelf life on an output gives planned batches a use-by date; surplus cannot cover a later order after expiry. Expiry set at execution remains unknown at planning time.

This change does not alter actual execution durations, equipment capacity, or production calendars. Those are separate planning stages.

## Checks

Validate API writes and clears, snapshots and stale detection, planning defaults, shelf-life allocation, browser save/revisit, and the three concepts at desktop, phone and dark theme widths.
