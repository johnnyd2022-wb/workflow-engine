## live-cogs 8.1b — Xero purchases in

Roadmap 8.1b of the live-cogs feature (`.agents/specs/live-cogs.md` v5). Draft: the whole feature is reviewed at the end, so the full verification chain (security audit, e2e, observability, test-author) has **not** been run. **Stacked on feat/live-cogs (8.1a).**

### What it delivers
- **Scopes**: `accounting.banktransactions.read` and `accounting.settings.read` added to `XERO_SCOPES` (names re-checked against Xero's scope table). Existing connections reconnect once.
- **Xero client**: `XeroAPIClient.get_accounts()` and `get_bank_transactions(modified_after, date_from, date_to)` — `SPEND` and `RECEIVE` as two filtered queries, paginated, `DELETED` kept, existing retry / rate limiter.
- **Tables** (migration `costing_purchases_001`, reversible, one head): `xero_accounts` (with `default_treatment`), `purchase_documents`, `purchase_lines` (composite `(org_id, …)` keys, check constraints, upsert keys `(org_id, source, external_id)` and `(org_id, document_id, line_key)`), and `xero_sync_jobs.purchases_synced`.
- **Sync** (`XeroSyncService`): `_sync_accounts` and `_sync_purchases` run inside the existing synchronous `full` / `incremental` jobs (only for orgs holding `costing`); new `purchases_sync()` (`sync_type=purchases`) and `purchases_history_sync()` (`sync_type=purchases_history`, inclusive date range, by transaction date). A purchases failure marks the job `partial`; neither new job moves the shared resume point.
- **`purchase_sources` module** (costing slice, mirror of `sales_sources.py`): normalises to ex-GST, base-currency documents and lines (refund sign, `LineAmountTypes`, foreign currency), applies account-default treatments, and applies the line side of "When Xero changes later" (amount change, recode, delete/void, vanished / returning keys), calling `purchase_sources.hooks.{amount_changed, recoded, deleted, reinstated}` — no-ops that 8.1c fills with the allocation side.
- **`GET /api/core/costing/purchases`** (`costs.view`, 404 without `costing`): the Xero side of each card, four tabs, per-tab counts, `from`/`to`, `limit`/`offset`. Needed to observe AC1–AC4; pre-fill, `historical` and the actions are 8.1c.
- Data-export allowlist entry for `purchase_lines.line_key`.

### Spec gaps resolved (written into the spec as ASSUMPTION B1–B9)
| Gap | Decision |
| --- | --- |
| 9 — positional keys | `pos:<n>:<fp>`: position among all lines + 8-hex SHA-256 of normalised description and item code. Amount/tax/account edits keep the key; reorder / insert / new description supersede the old key and create a new card; a returning key is reinstated (B1, AC64) |
| minor — foreign currency | Xero `CurrencyRate` is foreign per one base unit → base = foreign ÷ rate; per-line ex-tax and tax rounded half-up to 4 dp; base currency NZD; a foreign document without a rate is a sync error, never guessed (B2, AC65) |
| — | what is fetched / stored / how account defaults are matched (word-start keywords), sync-job semantics, review-reason precedence, tab placement stopgap (B3–B8, AC66–AC73) |

### AC → test
| AC | Test |
| --- | --- |
| AC1 | `test_costing_purchases_sync.py::test_ac1_stock_spend_appears_in_to_record_ex_gst` |
| AC2 | `…::test_ac2_duty_overhead_and_office_spend_is_stored_but_never_shown` |
| AC3 | `…::test_ac3_syncing_the_same_transaction_twice_leaves_one_document_and_one_line` |
| AC4 | `…::test_ac4_receive_on_a_stock_account_is_a_negative_refund_card` |
| AC34/35 (line side) | `…::test_ac72_*` (amount change, rescaled not-stock part, recode, delete, vanished line, reinstated, precedence, hook calls) |
| AC64 positional keys | `…::test_ac64_*` |
| AC65 currency | `…::test_ac65_*` |
| AC66 amount types | `…::test_ac66_line_amount_types_give_ex_gst_amounts` |
| AC67 entries kept | `…::test_ac67_*` |
| AC68 account defaults | `…::test_ac68_*` |
| AC69 scopes | `test_xero_purchases_client.py::test_ac69_*` |
| AC70 client | `test_xero_purchases_client.py::test_ac70_*` |
| AC71 sync jobs | `test_costing_purchases_jobs.py::test_ac71_*` |
| AC73 list route / access | `test_costing_purchases_sync.py::test_ac73_*`, `test_costing_purchases_access.py::test_ac73_*` |
| AC74 isolation / schema | `test_costing_purchases_access.py::test_ac74_*` |

Results (private migrated DB): 114 new tests pass; with the costing, CRM, Xero, sales and access-policy suites 480 + 159 pass. Three mutation spot-checks (currency direction, reclassification on chart change, reason precedence) each made the intended tests fail. Migration: down → up verified, one head, no model/migration drift on the new tables. `ruff check app/ tests/` clean.

### Known / for review
- `tests/test_data_export.py::test_every_secret_looking_column_is_dropped_or_declared_safe` fails on **`cost_flows.source_key`** — an 8.1a column already on the base branch, not this MR. It needs an allowlist entry in the 8.1a MR.
- The local `feat/live-cogs` branch carries one commit (`f085e7df`, Codex round-1 fixes to the cost engine) that is not on `origin/feat/live-cogs`; this MR is built on the pushed base and touches none of the files that commit changes, so it should rebase cleanly once 8.1a is pushed. `costing_engine_001` keeps its revision id.
- A purchases failure keeps the shared resume point back (so the next sales sync re-fetches from the same point). Accepted and written up in B6.
- Stock coded to an asset (balance-sheet) account is not a purchase under the spec and never appears (B4).

### Codex review (advisory)
CODEX_SECTION

🤖 Generated with [Claude Code](https://claude.com/claude-code)
