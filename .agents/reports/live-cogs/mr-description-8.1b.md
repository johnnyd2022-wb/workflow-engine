## Summary

Roadmap **8.1b — Xero purchases in** (spec `.agents/specs/live-cogs.md`, "8.1b build contract"). Stacked on !689 (8.1a); targets `feat/live-cogs` and retargets to `main` when !689 merges.

Biz-E now pulls the org's spending from Xero and classifies every line, ready for 8.1c to record it into stock. Nothing is shown to users yet and nothing is linked to stock.

- **Chart of accounts** cached in `xero_accounts` with a default treatment per account (`stock`, `not_stock`, `duty`, `overhead`, by type and exact name keywords) and a person-set `treatment_override` that sync never touches.
- **Spend and receive money** (`BankTransactions` of type `SPEND` / `RECEIVE`) stored as `purchase_documents` / `purchase_lines`: ex-GST, base currency, refunds negative. Only expense-account lines are stored. Missing amounts stay null, never $0.
- **Line identity**: lines with a Xero `LineItemID` update in place; lines without one are keyed by position plus a canonical content fingerprint, so a reordered or inserted line is superseded rather than silently becoming another line. Lines are tied to their account by Xero `AccountID`, so renaming a code doesn't lose them.
- **Currency**: base currency comes from Xero's Organisation. Foreign-currency purchases are stored as `needs_rate` with no base amount until the conversion direction is verified (ASSUMPTION A11). Whistlebird is NZD only.
- **Sync**: the purchases phase runs after sales, in one savepoint, with its own cursor and a start date anchored on the first costing sync. Incremental runs fetch by modified-since only, so a transaction later edited to an earlier date is still updated. Not entitled, or not consented (missing scopes), is a status, not an error; a purchases failure never loses or blocks sales work. Voided transactions keep their stored lines.
- **One seam** (`classify_line`) decides a line's treatment; 8.1c adds rules there.
- **API**: `GET /api/core/costing/accounts` (`costs.view`), `PUT /api/core/costing/accounts/<xero_account_id>` (`costs.manage`).
- **Scopes**: `accounting.banktransactions.read` and `accounting.settings.read` added. **Every connected org must reconnect Xero once** (not in production yet).

## Acceptance criteria (8.1b)

All in `tests/test_costing_purchases.py`, using real `xero_python` model objects:

| AC | Tests |
| --- | --- |
| AC1–AC4 storage, treatments, upsert, refunds | `test_ac1_*` … `test_ac4_*` |
| AC64 account defaults and what is stored | `test_ac64_*`, `test_r1_each_keyword_alone` |
| AC65 line amount types, discounts | `test_ac65_*`, `test_r1_notax_*` |
| AC66 base currency, foreign held | `test_ac66_*`, `test_r1_foreign_*` |
| AC67 positional identity and fingerprint | `test_ac67_*`, `test_r1_inserted_line_*` |
| AC68 LineItemID in place | `test_ac68_*`, `test_r1_line_item_id_*` |
| AC69 voids | `test_ac69_*`, `test_r1_voided_*` |
| AC70 account overrides | `test_ac70_*`, `test_r1_cross_org_put_*`, `test_r2_override_*` |
| AC71 gating and failure | `test_ac71_*`, `test_r1_*`, `test_r2_token_expiry_*`, `test_r3_*` |
| AC72 start date and cursor | `test_ac72_*`, `test_r1_cursor_*` |
| AC73 tenancy | `test_ac73_*` |

## Verification

| Stage | Verdict | Report |
| --- | --- | --- |
| spec-critic (Codex) | gaps-found (7 high, 7 medium) → contract v2 | `.agents/reports/live-cogs/spec-critic-8.1b.md` |
| tests written first | real SDK models; all pass | `tests/test_costing_purchases.py` |
| build-review (Codex) round 1 | fail (4 high, 4 medium, weak tests) → fixed | `.agents/reports/live-cogs/review-8.1b-r1.md` |
| round 2 | fail (1 high, 2 medium) → fixed | `.agents/reports/live-cogs/review-8.1b-r2.md` |
| round 3 (final) | 1 medium → fixed; nothing else above low | `.agents/reports/live-cogs/review-8.1b-r3.md` |
| full suite (after rebase on !689) | 4321 passed, 31 skipped, 0 failed | `.agents/reports/live-cogs/full-suite-8.1b.txt` |
| migration | `costing_purchases_001` additive; up/down/up on a private DB | |

## Known limitations

- No automated test of the downgrade refusal while an account override exists (Codex R3, low).
- Foreign-currency purchases are stored unpriced until A11 is verified against a real multi-currency Xero transaction.
- The CRM sync's `partial` rule gains one case: sales phases that completed with no record errors, plus a failed purchases phase. Sales-only behaviour is unchanged.

## Next

8.1c-1 records these lines into stock (allocations, record / link / not-stock / skip / refund / review, and what happens when Xero changes a recorded line).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012K4jB79TxztZobCHJU3cVj
