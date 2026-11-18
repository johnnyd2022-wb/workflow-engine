# Concept ids used in the OpenAPI overlay (8.2f)

`x-bize.concepts` entries are topic ids of the form `<domain>.<topic>`, following the first-set list in
`.agents/specs/public-mcp.md` §"Business knowledge". 8.2g (`docs/knowledge/`) needs a topic for each id below
(its test: every `x-bize.concepts` entry in the overlay has a topic). The test
`tests/openapi/test_coverage.py::test_ac37_the_concept_ids_used_are_recorded_for_the_knowledge_docs` fails if an
overlay uses an id that is not listed here.

| Concept id | Spec first-set item | Used by (operationId) |
|---|---|---|
| `inventory.lots` | lots | core_list_inventory |
| `inventory.units_and_packs` | units and packs | core_list_inventory |
| `inventory.availability` | availability vs on-hand | core_list_inventory, core_list_output_ready_date, lot_holds_get_lot_holds, lot_holds_list_open_holds, planning_get_stock_cover, stocktake_get_stock_position |
| `inventory.ready_dates` | ready dates | core_list_output_ready_date |
| `inventory.expiry` | expiry | core_list_expired_materials |
| `inventory.holds` | holds | lot_holds_get_lot_holds, lot_holds_list_open_holds |
| `inventory.sites_and_locations` | sites and locations | stocktake_get_stock_position |
| `inventory.stocktakes` | stocktakes | stocktake_get_stocktake_reconciliation |
| `production.workflows` | workflows | core_get_process, core_list_processes |
| `production.steps` | steps | core_get_process, core_list_executions, core_list_processes |
| `production.batches` | batches/executions | core_get_execution, core_list_executions, planning_get_planning_batches |
| `production.inputs_and_outputs` | inputs and outputs | core_get_execution, core_get_process |
| `production.intermediates` | intermediates | core_get_execution |
| `traceability.back` | back | core_trace_inventory_backward, core_trace_inventory_to_sale_graph |
| `traceability.forward` | forward | core_list_expired_materials, core_trace_inventory_to_sale_graph, core_trace_raw_material |
| `traceability.to_sale` | to-sale | core_trace_inventory_to_sale_graph |
| `compliance.nz_alcohol_records` | NZ alcohol records | compliant_compliant_api_list_records |
| `compliance.excise_periods` | excise periods | compliant_compliant_api_get_excise_period, compliant_compliant_api_get_excise_position, compliant_compliant_api_list_excise_periods |
| `compliance.excise_position` | excise position | compliant_compliant_api_get_excise_position, stocktake_get_stock_position, stocktake_get_stocktake_reconciliation |
| `compliance.cca_movements` | CCA movements | compliant_compliant_api_get_excise_period |
| `sales.xero_invoices` | Xero invoices | crm_crm_api_get_org_invoices, crm_crm_api_monthly_sales |
| `sales.fifo_matching` | FIFO stock matching | costing_margins_report, crm_crm_api_get_org_invoices |
| `costing.cost_status` | cost status actual/estimated/unknown | costing_get_execution_cost, costing_get_lot_cost, costing_get_stock_value, costing_margins_report, costing_readiness_list |
| `costing.readiness` | readiness | costing_readiness_detail, costing_readiness_list |
| `costing.last_known_price` | last known price | costing_get_lot_cost, costing_readiness_detail |
| `costing.joint_outputs` | joint outputs | costing_get_execution_cost, costing_margins_report |
| `costing.stock_value` | stock value | costing_get_stock_value |
| `costing.xero_bridge` | the Xero bridge | costing_get_stock_value |
| `planning.stock_cover` | **not in the spec's first set** | planning_get_stock_cover |
| `planning.planned_batches` | **not in the spec's first set** | planning_get_planning_batches |

## For 8.2g

- The first-set items `inventory.untracked_items` and `costing.overheads` are not used by any operation yet,
  so no overlay entry needs them. Write them anyway: the spec lists them.
- `planning.stock_cover` and `planning.planned_batches` are the two ids outside the spec's first-set list. The
  planner's cover and batches are layer-3 operations the spec names, so they need a concept. Either add a
  `planning` domain to the knowledge set (preferred: the planner has its own rules for what counts as
  available) or tell 8.2f to map them to `inventory.availability` and `production.batches`.
- Each operation's `related_operations` use the operationId (the endpoint name, dots to underscores), as in
  `docs/openapi.json`.
