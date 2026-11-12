# Switching live cost on for an organisation

Roadmap 8.1. First used for Whistlebird (`whistlebird_test`, which becomes the live org once
its records are accurate).

1. **Xero has the purchases permissions.** Settings › Integrations › reconnect Xero once, so
   Biz-E can read bank transactions and the chart of accounts (read-only). Without this the
   rest still works; only loading purchases from Xero waits.
2. **Switch it on** (safe to run again):

   ```bash
   uv run workflow costing enable --org-id <org uuid> --history-from 2026-01-01
   ```

   This grants the `costing` feature, counts new purchases from today, rebuilds stock-movement
   history for lots made before the cost engine, and loads purchases from Xero back to
   `--history-from` (at most 3 years). It ends with what's costed: products with a full cost,
   the ones still waiting and on what, and how many purchases wait to be recorded. Exit code 2
   means everything but the Xero load worked (reconnect, then run again).
3. **Work through Production › Purchases** (new, then "Load earlier purchases" view) and
   record what's still in stock. Without Xero: enter "Total paid" on Add Inventory or a lot's
   cost panel.
4. **Check Production › Costs**: every product reads "Full cost" or names what it's waiting on.
