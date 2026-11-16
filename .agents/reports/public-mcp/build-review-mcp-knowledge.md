# Build review: 8.2g business knowledge (MCP-KNOWLEDGE)

Reviewer: Claude subagent (Codex not used), brief: factual accuracy (ten spot-checks), no tenant or recipe data, nothing that bypasses permissions.

| Finding | Verdict | Action |
|---|---|---|
| Stock cover ignores ready dates (`planning/stock.py:106`) | OK | none |
| Cover filters: output, site, owner, expiry, hold flags | OK | none |
| FIFO order: label batch number, no expiry check | OK | none |
| Hold blocks five uses (`lot_holds.py:31-37`) | OK | none |
| Stocktake scope, 14-day window, 0.5% tolerance | OK | none |
| `unit_cost` null unless actual/estimated (`engine.py:999,1052`) | OK | none |
| FIFO tie-break purchase date then created time | reviewer did not see it | rejected: `inventory_repo.py:466-469` orders by batch number, purchase_date, created_at |
| Hold permissions (inventory.adjust / compliance.manage) | reviewer did not find it | rejected: `access_policy.py` lot_holds rules |
| Made lots' `expiry_date` not filled by step completion | not traced | rejected: `execution_routes.py` output_creations has no expiry_date |
| Months ~30 days | unmarked inference | rejected: read in `expiry_rules.py` |
| Tenant names / recipes / bypass language | none found | test also forbids them |

## Cross-builder findings (for 8.2f / 8.2c)
- 8.2f's description of `planning_get_stock_cover` says stock "not yet ready or committed to a planned batch is not counted". The code does not do that (`stock.py` on_hand, `forecast_service.py:164-182`). The knowledge docs follow the code; the OpenAPI description should be corrected.
- `crm_crm_api_monthly_sales` is summarised as "net revenue" but sums invoice `total`, which includes GST.
- `stocktake_get_stocktake_reconciliation` needs a stocktake id and no MCP operation lists stocktakes.
