## Summary

Roadmap **8.1a — Cost engine** (spec `.agents/specs/live-cogs.md` v4). The first slice of live batch and bottle cost: every lot and batch output gets a real cost, computed on read from facts, with no mandatory setup.

- `cost_flows`: every quantity into or out of a lot that cost cares about, written by Core's own stock writes (lot create, add quantity, step consumption, output reconciliation, site transfer) in the same transaction. Keys are shared with an idempotent backfill (`uv run workflow costing backfill-flows --org-id <id> | --all`).
- Output identity by step output definition id (client `output_id`, else a unique stripped name), so a configured `cost_share` follows the definition.
- `lot_cost_entries`: manual or free prices on a lot (whole-lot or per receipt); customer-owned stock is always $0.
- The roll-up (`app/features/costing/engine.py`): an iterative walk over lot and batch-step nodes. Price-fact precedence without double counting, partial costs carried as floors through WIP, split rules (configured %, byproduct, quantity, primary output), Library stock takes no share (A9), last known price from directly priced lots of the same material, transfers, cycles, a lots+executions node budget. A cost is never a silent $0: `actual | estimated | partial | unknown` plus the missing inputs.
- API under `/api/core/costing`: `GET/PUT /lots/<id>/cost`, `DELETE /lots/<id>/cost/<entry_id>`, `GET /executions/<id>/cost`, `GET/PUT /settings`. New permissions `costs.view` / `costs.manage` (Admin + Staff by default, grantable), per-org feature `costing` (`grant-feature --feature costing`, admin site).
- No UI in this MR (8.1d/e) and no Xero purchases yet (8.1b/c).

## Acceptance criteria (8.1a)

| AC | Test |
| --- | --- |
| AC22 last known price / unknown / never from production | `tests/test_costing_engine.py::test_ac22_*` |
| AC23 free, customer-owned | `test_costing_engine.py::test_ac23_free_and_customer_owned`, `tests/test_costing_customer_owned.py` |
| AC24 weighted pool over inflows | `test_ac24_weighted_pool_over_two_inflows` |
| AC25–AC26 batch cost live then absorbed, unit conversion | `test_ac25_ac26_*`, `test_ac25_input_in_a_different_unit` |
| AC27 split rules (a–h, type precedence, percent + free, scaling) | `test_ac27_*`, `test_ac27c_*`, `test_ac27h_*` |
| AC28 partial until priced | `test_ac28_*` |
| AC29 WIP counted once, partial floor propagates | `test_ac29_*` |
| AC31 reconciled output carries cost | `test_ac31_*` |
| AC32 transfer destination | `tests/test_costing_transfer.py` |
| AC36 hooks, same transaction, rollback | `tests/test_costing_flows.py::test_ac36_*` |
| AC37 backfill, idempotent, org-scoped, legacy lot | `test_costing_flows.py::test_ac37_*` |
| AC40 permissions | `tests/test_costing_routes.py::test_ac40_*` |
| AC41 feature gate; flows written with it off | `test_costing_routes.py::test_ac41_*`, `test_costing_flows.py::test_ac41_*` |
| AC42 tenant isolation | `test_costing_routes.py::test_ac42_*`, `test_costing_engine.py::test_ac42_*` |
| AC52 output identity | `test_costing_flows.py::test_ac52_*`, `test_costing_engine.py::test_ac52_*` |
| AC53 Library stock | `test_ac53_*` |
| AC54–AC57 price facts, one active slot, editable lots | `test_ac54_*` … `test_ac57_*` |
| AC58–AC59 last-known choice, no chaining | `test_ac58_*`, `test_ac59_*` |
| AC60 cycle | `test_ac60_*` |
| AC61 no flow history then backfill | `test_ac61_*` |
| AC62 settings | `test_costing_routes.py::test_ac62_settings` |
| AC63 delete entry | `test_ac63_*` |
| A10 reads write nothing, no cache tables | `test_reads_write_nothing` |

## Verification

| Stage | Verdict | Report |
| --- | --- | --- |
| spec-critic (Codex) | rounds 1–2 gaps resolved in v4; later-MR gaps listed in the spec | `.agents/reports/live-cogs/spec-critic.md` |
| tests written first; test-evaluator (Codex) | weakened → all findings addressed | `.agents/reports/live-cogs/test-evaluator-8.1a.md` |
| unit/integration | 4217 passed, 31 skipped, 0 failed (full suite, private DB) | `.agents/reports/live-cogs/full-suite.txt` |
| build-review (Codex) round 1 | fail, 10 findings → 9 fixed, 1 disputed and accepted | `.agents/reports/live-cogs/build-review-r1.md` |
| build-review round 2 | fail, 3 medium → fixed | `.agents/reports/live-cogs/build-review-r2.md` |
| build-review round 3 | **pass** | `.agents/reports/live-cogs/build-review-r3.md` |
| migration | `costing_engine_001` additive; upgrade/downgrade round-tripped on a private DB | — |
| security-tenant-audit + migration-safety (Codex) | findings-open → all fixed (downgrade refuses any costing row; 16 KiB body limit; estimate candidates on the node budget; tenant indexes; org-bound creator FK) | `.agents/reports/live-cogs/audit-8.1a.md` |

## Not yet run (why this is a draft)

- `ci-gate` was not run as a separate stage; CI runs lint and the relevant tests on this MR. Codex ran the security/tenant and migration audits (above).
- No e2e: this MR has no UI.

## Decisions to review

- **Downgrade refuses while any costing row exists** (typed prices, settings, and reconciliation flows the backfill can't rebuild), matching `planning_replan_001`.
- **A9**: Library stock remainders take no share of a batch's cost in Phase 1 (bottle volume isn't recorded yet).
- **A10**: no cost cache tables; every figure is computed on read.
- New `UNIQUE (org_id, execution_id, id)` on `execution_steps` (target of the composite FK).

## Out of scope / next

8.1b Xero purchases in, 8.1c rules and actions, 8.1d Purchases page, 8.1e cost where people look. The spec's "Open for 8.1b–e" lists the review gaps each must close first.

After merge: drop the private test DB `workflow-engine-test_cogs`; run `costing backfill-flows --all` where costing is switched on.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012K4jB79TxztZobCHJU3cVj
