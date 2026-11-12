# spec-critic — live-cogs 8.1b (Xero purchases in), single scoped round

Read-only. Worktree /home/johnny/wt-live-cogs-xero (branch feat/live-cogs-xero, stacked on the
8.1a branch). Grade ONLY the section "## 8.1b build contract — Xero purchases in" of
`.agents/specs/live-cogs.md` (plus the tables it references) for build-readiness, against the
real code: `app/features/crm/services/xero_sync_service.py`, `xero_api_client.py`,
`xero_oauth_service.py`, `app/features/crm/models/*`, `app/features/costing/*` (8.1a, merged
into this branch), and the installed xero_python SDK models (BankTransaction, LineItem,
Account) under the uv venv's site-packages.

Hunt: ACs that are untestable or contradict the rules; rules two implementers would code
differently (especially line identity/fingerprints, sign of refunds, FX, cursor/start date,
gating that might break sales sync, transaction/savepoint boundaries); SDK field names or enum
values the spec gets wrong; tenant-scoping holes; anything that would make 8.1c (rules and
allocations on these lines) hard. Be thorough in this one pass and rank by impact. Each gap:
spec line, what's wrong, concrete fix. End with `VERDICT: sound` or `VERDICT: gaps-found`.
