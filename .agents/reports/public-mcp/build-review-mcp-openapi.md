# Build review: public MCP 8.2f (OpenAPI for the whole API)

Reviewer: Claude (subagent, high effort) on `git diff origin/main...HEAD`; Codex was not tried. Brief: the
document must not reveal operations a caller cannot reach; no secrets or internal hostnames; the generator must be
deterministic; overlay loader safety; schema accuracy for the `x-bize.mcp` operations.

Clean on the brief's three headline items: `token_access` is behaviour-identical after the `token_scope_includes`
refactor; `narrow()` prunes operations, `related_operations`, schemas and tags correctly; no secrets, hostnames or
checkout paths; output is hash-seed independent and sorted.

| # | Finding | Verdict | What was done |
|---|---|---|---|
| 1 | `costing_get_stock_value` lines: `inventory_item_id` and `unit` are null for an in-production batch | Fixed | Both nullable; `unit` no longer required |
| 2 | To-sale graph: sale nodes have non-UUID ids; `traced_item` can be null | Fixed | `all_items` is an open object with a string `id`; `traced_item` is `oneOf` TraceItem or null |
| 3 | `excise position` `this_period.estimate` is null while the entry is incomplete | Fixed | Nullable |
| 4 | Excise period `period` parameter documented as YYYY-MM; the handler needs a full date and defaults to the previous period | Fixed | Documented as a date, default corrected |
| 5 | `costing_get_execution_cost.known_input_cost` is null when a batch is too large to cost | Fixed | Nullable |
| 6 | `core_list_inventory?view=compact` undocumented, and its items lack `created_at`; trace ops also 400 on a bad id | Fixed | `view` parameter documented, `created_at` no longer required, 400 added to the trace operations |
| 7a | `costing_margins_report` is shown to a `costs.view`-only caller although the route also needs `sales.view` | Accepted | The policy table (which this phase must not change) says `costs.view`; the description states the extra requirement and the route answers 403. Recorded as an assumption in the MR |
| 7b | `narrow()` ignores per-organisation availability (CRM, Compliant, costing, the MCP switch) | Accepted, by design | The document says what a person's role may call. Each operation carries `x-bize.feature` so the MCP server filters by what the organisation has (spec: "its feature is enabled for the org") |
| 8a | Internal tracking ids in summaries (`GL-P01b:`, `8.1f-2:`, `(GL-P07 B5)`) | Fixed | Stripped from docstring-derived summaries; `tests/openapi/test_overlay.py` pins it |
| 8b | Overlay loader raised `TypeError` on an empty `x-bize`, a non-mapping `response` or `parameters` | Fixed | Now `OverlayError`, with tests |
| 8c | Two rules normalising to the same path and method would silently overwrite each other | Fixed | `build` raises |
| 8d | `prune` does not follow a `$ref` with a sub-pointer | Rejected | No such ref exists, and the overlay convention is `#/components/schemas/<Name>` only |
| 8e | A broken overlay would 500 on the first request | Rejected | CI builds the document on every MR (`openapi_current` and the tests), so it cannot ship broken |
| 8f | `stocktake_get_stock_position?format=csv` declares only a JSON 200 | Rejected | The CSV form is for people downloading; the parameter description says so, and assistants use JSON |

Found while fixing, not by the review: PyYAML silently cuts an unquoted flow-mapping description at a comma and
reads a bare `on`/`no` key as a boolean. Both publish a wrong document without an error, so the loader now refuses
them (`tests/openapi/test_overlay.py`).
