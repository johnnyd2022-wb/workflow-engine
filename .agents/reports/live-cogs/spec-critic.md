# spec-critic — live-cogs, round 1 (Codex gpt-5.6-sol, 2026-11-10)

Captured from the Codex session transcript (read-only sandbox could not write this file).

The spec is not build-ready: 15 gaps found (10 high, 5 medium). The requested report could not be written because the workspace is read-only; `.agents/reports/live-cogs/spec-critic.md` was not created and the worktree remains clean.

Key blockers:

- Produced-lot identity is unreliable: no `source_output_id` reaches created lots, no production movements are written, and fully reconciled outputs create no output lot.
- The roll-up uses `allocated_cost` and `status` fields absent from `cost_step_flows`.
- Quantity additions lack durable cost-inflow facts; manual costs plus later purchase allocations can double-count.
- The claimed recompute queue does not exist; Xero sync is synchronous, and failed non-blocking hooks have no durable retry.
- Purchase lines lack a stable uniqueness/upsert contract; `ignore` versus `not_stock` is inconsistent.
- Changed amounts, partial allocations, refunds, and future supplier credits lack defined arithmetic.
- Permissions reference nonexistent `OWNER` and `sales.revenue` roles/permissions, with no route-method matrix.
- “Same material” normalization and cost-readiness scope are undefined.
- Numerous Phase 1 promises lack ACs, including feature gating, Home card, bulk/review actions, Add Inventory cost, and repeated-receipt averaging.
- The spec remains draft with unresolved founder decisions.
- AC18, AC21g, AC21h, and AC22 are not fully falsifiable.
- The required External Surfaces section is missing.
- No generic durable notification service exists.
- Historical runs have no persistence/resume model.
- Phase 1 does not preserve sufficient immutable valued movements for Phase 3 snapshots/bridge; supplier-credit and Phase 4 labour contracts also conflict.

V1–V9 findings:

- V1: quantities exist in `actual_outputs`, but output identity/backfill is incomplete.
- V2: no completed-step reopen path exists.
- V3: reconciliation explicitly does not create/update an output lot.
- V4: destination cost can follow `transfer_receipt_id → transfer → source_item_id`.
- V5: permissions live in `access_policy.py`; the stated roles do not match it.
- V6: Xero jobs are synchronous bookkeeping, not a queue.
- V7: current scopes are `accounting.banktransactions.read` and `accounting.settings.read`; Phase 3 P&L uses `accounting.reports.profitandloss.read`. Xero documents bank LineItemIDs but not stability after UI line replacement. [Xero scope table](https://developer.xero.com/documentation/guides/remote-mcp/overview)
- V8: excise joins FIFO allocations to invoices, while tasting sales are deliberately excluded and handled as earlier removals; no per-sale-line lodged-duty API exists.
- V9: notifications are derived system findings, not durable per-sync notifications.

F1 is resolved: the roadmap already defines 8.1a–h, with this build scoped to 8.1a–e.

VERDICT: gaps-found