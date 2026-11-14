# Build review: live-cogs 8.1g, stock value and the Xero bridge

You are an advisory, read-only reviewer. Review `git diff origin/main...HEAD` (run it; this
worktree is your cwd) against the contract in `.agents/specs/live-cogs.md`, section
"8.1g build contract — stock value and the Xero bridge (Phase 3)", ACs AC129–AC147.

Founder rules that bind every costing change: costing works with no Xero connected; unknown cost
is never shown as $0; dialogs are bottom sheets; pages work at 375px without sideways scroll;
tenant isolation (`org_id` on every query, composite FKs); closed-month figures never change.

Please hunt for real bugs, not style:

1. **Identity.** `stock_value.compute_movements` / `take_snapshot`: do the stored movements sum
   exactly to closing minus opening? Which inputs could make `rounding` large (lots deleted,
   units that don't convert, batches in progress at one end only, `reconstructed` cost flows)?
2. **As-at reconstruction** (`_quantities_as_of`, `_in_progress`, `_Pricer.pool`): is reversing
   events/wastage out of today's quantity sound? Double counts between `quantity_adjusted`,
   `consumed`, `updated` and wastage movements? Edge: lot created and consumed after the cutoff.
3. **Month-end automation** (`ensure_month_end_snapshots`, the sync hook in
   `xero_sync_service._take_month_end_snapshots`, the read trigger in `routes._auto_month_ends`):
   idempotency under concurrent requests, out-of-order cutoffs, savepoint/transaction handling,
   anything that could fail a sync or a GET.
4. **Bridge** (`bridge.py`): tie-out arithmetic (A − B = listed + other entries), P&L parsing,
   scope handling, error states never echoing internals, permissions on routes.
5. **Security/tenancy:** every query org-scoped, CSV formula injection, snapshot ids from other
   orgs, the daily cap, idempotency on the POST.
6. **UI** (`stock.js`, `costs.html`): XSS (all text via textContent?), unknown shown as $0 anywhere.

Report findings ranked by severity, each with file:line, a concrete failing scenario, and a
suggested fix. Say plainly if an AC is not covered by a test. Do not modify files.
