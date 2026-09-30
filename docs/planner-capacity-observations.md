# Rough resource capacity on the production board

This is a bounded part of source-to-sale item 7.3e. A producer names up to 20
resource groups at each site (for example, still, bottling line, tanks), gives
each group 1–1,440 available minutes per calendar day, and assigns up to 200
workflow steps to one group at that site. Settings are tenant scoped, audited
and revision checked. A group is a planning label, not a machine reservation.

The board reads each planned batch's frozen workflow timing snapshot. It places
each step at its earliest start after its predecessor steps, splits that step's
duration over calendar days, and totals minutes for each site and group. A day
whose observed load exceeds the configured minutes is marked overloaded. The
board suggests a lower-priority unpinned affected batch to review; it does not
move it automatically. Pinned batches still count toward the load.

Missing site settings, unassigned steps, unknown readiness, invalid timing and
more than 1,000 potentially relevant batches are explicit unresolved states.
Views are limited to 31 calendar days. There is no shift or weekend calendar,
finite workstation scheduling, material reservation, resource hold, automatic
replan or reliable customer promise in this slice. `forecast_ready_date`
remains null and the existing start guard does not consult this observation.

The migration `planner_capacity_001` follows `planner_material_forecasts_001`.
On integration, preserve the deployed planner/contract migration lineage and
restack this child after its parent rather than changing an already-applied
revision.
