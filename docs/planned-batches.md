# Persisted production board

This slice of roadmap 7.3b/c/f turns an explicit manual production demand into
individual physical batches, with frozen workflow timing and editable proposed
dates. Open the Production demand workspace, then **Production board**. Staff
with `production.view` can read the board; `production.record` is required to
save settings, plan batches or change them. Mutations retain Flask-WTF CSRF.

## Quantities and timing

Choose a stable workflow output, its usual batch quantity and explicit duration
and waiting time for every step. Units come from the workflow, not the request.
Counted quantities must be whole numbers. The output must map to exactly one
workflow in the current organisation. Missing, draft or ambiguous mappings and
stale settings cannot create batches.

Manual demand is a quantity the producer has chosen to make. This adapter rounds
the entire quantity to the configured batch size; it does **not** deduct inventory,
WIP or existing order allocations. The net-requirements engine is available for
future stock/order adapters, but is not connected to this persistence path.
Each request creates at most 500 physical batches. A repeat request returns the
same live generation; only cancelling all of its batches permits a new generation.
Planning at a different site requires reviewing and cancelling the prior plan.

The critical path follows step dependencies, including waits. Enabled valid fixed
output-ready durations use Core's duration conversion, and overlapping output
waits on one step use the longest duration. Dates round partial days upward and
start no earlier than today. A batch freezes its quantity, unit, workflow digest,
step durations/waits, readiness rules' timing contribution, demand reference,
due date, selected site, settings revision and latest process version
ID/number/snapshot digest. Missing or inconsistent versions prevent a start.
Later settings changes leave
existing snapshots intact. Changed workflow definitions require review before
execution starts.

`proposed_start_date` is editable. `theoretical_ready_date` is a timing estimate,
and remains null when an output's readiness cannot be predicted. For a valid
`set_at_execution` ready-date rule, production can supply the actual date later;
malformed rules require review before starting. `forecast_ready_date` remains
null until current material, capacity and compliance stages are integrated.
No timing estimate is published as a delivery promise or portal forecast.

## Board and changes

The board supports week, month and day views and a single column on phones.
Batches sort by proposed start, descending priority and physical batch number
within each demand. Staff can change priority, pin/unpin a date, manually move an
unpinned batch to today or later, or cancel it. These actions require the current
revision and commit an audit entry in the same transaction. Cancelling a demand
cancels all unstarted batches atomically; a demand with a started batch requires
review instead. Started batches are immutable through planning controls.

An organisation row lock serialises planning changes; composite foreign keys
enforce same-organisation demand, workflow, setting, site and execution references.
Output and unit identities are revalidated by the service. The board returns at
most 1,000 batches over at most 91 days, with an explicit truncation notice.
There is no drag interaction, automatic replan, capacity calendar or dashboard
projection in this slice.

## Execution start seam

The start route exists, but its production check adapter always reports that
materials, capacity and site compliance have not been checked. The button remains
disabled and a direct request cannot bypass this by changing stored blockers or
sending clearance flags. Future adapters must recalculate trusted checks within
the start transaction, including stock scope, ownership, readiness/expiry,
commitments, resource capacity and module constraints.

When that trusted boundary clears a batch, the service checks the open demand,
proposed date and revision, locks and compares the workflow definition, and calls
the existing `ExecutionRepository.create_execution(commit=False)`. It verifies
the execution's organisation, planned site and step set before linking it.
The selected output's native workflow quantity must exactly equal the planned
physical quantity. The repository cannot apply a multiplier, so missing or
mismatched quantities cannot start. The pinned process version must still be the
current version, even if a later version has identical recipe fields, and its
snapshot must match the locked live definition. Execution creation, planning
status, idempotency response and audit commit together.
The required `Idempotency-Key` is organisation-scoped and binds the batch and
revision; retries cannot create another execution. Physical output quantities
are still recorded through the existing execution flow; expected yield is not
a guaranteed output or a new stock allocation.

Sites' `app.core.db.site_operations.resolve_site` and repository site argument are
used when that prerequisite is installed. The resolver owns its operations gate.
The site foundation permits only the validated default site without this seam.
The planner never switches on multiple-site operations. Additional registered
sites may receive proposed work while execution remains unavailable there.

## Integration and migration order

This branch includes read-only prerequisite code from !423 (timing/net engine),
!428 (material engine), !425 (manual demand) and !427 (site foundation). Parent
branches remain untouched. On this integration branch the migration chain is:

`custom_roles_001 → multiple_sites_001 → planner_demands_001 → planned_batches_001`.

The copy of !425's demand migration is sequenced after !427; it does not add
`depends_on` or another Alembic head. When restacking sibling contract and site
operation migrations, retain one linear chain. The source MR !426 already follows
`planner_demands_001`; the merge train must sequence sibling descendants explicitly.

Remaining work: authenticated sales/contract/target adapters, inventory netting,
expected supplier delivery records, material/recipe and capacity adapters,
compliance clearance, automatic replanning, drag interactions, dashboard work and
versioned order/portal forecasts. The full 7.3b/c/f checklist items remain open.
