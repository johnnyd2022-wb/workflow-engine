# Xero MCP setup (Claude Code on the web)

This repo ships a committed `.mcp.json` at the repo root that wires the **official Xero
MCP server** (`@xeroapi/xero-mcp-server`) into Claude Code sessions. Once the two secrets
below are set in the Claude Code web environment, any session in this repo can query Xero
data (invoices, contacts, sales, reports) within the scopes configured in `.mcp.json`.

Because Claude Code on the web runs in a **headless container**, we cannot use Xero's
interactive OAuth browser login. Instead we use a Xero **Custom Connection**
(machine-to-machine `client_credentials` grant), which authenticates with just a client ID
and secret — no browser step. A custom connection binds to **one Xero organisation**.

## What the repo already provides

`.mcp.json` (repo root):

```json
{
  "mcpServers": {
    "xero": {
      "command": "npx",
      "args": ["-y", "@xeroapi/xero-mcp-server@latest"],
      "env": {
        "XERO_CLIENT_ID": "${XERO_CLIENT_ID}",
        "XERO_CLIENT_SECRET": "${XERO_CLIENT_SECRET}",
        "XERO_SCOPES": "accounting.transactions.read accounting.contacts.read accounting.settings.read"
      }
    }
  }
}
```

The `${...}` placeholders are resolved from environment variables at MCP server startup.
**No secret value is ever committed to this file or to git history** — only the two
variable names are checked in.

### Scopes

`XERO_SCOPES` uses Xero's actual OAuth2 accounting scopes (see the
[Xero scopes reference](https://developer.xero.com/documentation/guides/oauth2/scopes)) —
there is no per-report or per-object scope like "invoices" or "payments"; invoices,
payments, credit notes, and other sales/purchase documents are all covered by the single
`accounting.transactions` scope:

| Scope | Access | Purpose |
|---|---|---|
| `accounting.transactions.read` | read-only | Invoices, payments, sales/purchase data |
| `accounting.contacts.read` | read-only | Look up customers/suppliers |
| `accounting.settings.read` | read-only | Org/tax settings, items/products |

This is currently **read-only** — no scope here allows Claude to create, update, or
delete anything in Xero. The Xero Custom Connection itself must also be configured with
at least these same scopes in the Xero Developer portal; the connection's granted scopes
are the hard ceiling — `XERO_SCOPES` cannot request more than the connection allows.

> **Note on prior scope names:** an earlier version of this config used
> `accounting.invoices`, `accounting.payments.read`,
> `accounting.reports.profitandloss.read`, and `accounting.reports.aged.read`. None of
> these are valid Xero scopes — Xero's OAuth token exchange silently granted **no**
> accounting scopes at all when they were requested, which surfaced later as "no valid
> accounting scopes" errors on every API call. If write access to contacts/transactions
> is needed again, use the real scope names (`accounting.contacts`,
> `accounting.transactions`, no `.read` suffix), not invented ones — and reconnect the
> Custom Connection afterward (see below).

## Setting the real secret values

1. Create (or reuse) a Xero **Custom Connection** for the target organisation in the Xero
   Developer portal, and note its client ID and client secret.
2. Store those two values in the **Claude Code web environment's secrets/environment
   variable settings**, under the names `XERO_CLIENT_ID` and `XERO_CLIENT_SECRET`. This is
   the same mechanism used for other CI/CD secrets in this repo (see the "Secrets" section
   of `CLAUDE.md` — local dev uses KeePassXC, CI/CD and hosted environments use env vars).
3. Do **not** paste the raw values into `.mcp.json`, a commit, an MR description, or any
   other file that gets checked into git — git history is effectively permanent, and an MR
   diff is visible to every reviewer.

For local CLI use (outside the web environment), pull the values from the
`workflow-engine` KeePassXC group the same way other local secrets are handled
(`scripts/local_secrets.py`), and export them as `XERO_CLIENT_ID` / `XERO_CLIENT_SECRET`
in your shell before launching Claude Code — never write them to a file inside the repo.

## Verifying the connection

Once the environment variables are set, start a new Claude Code session in this repo and
ask it to list Xero contacts or invoices. The `xero` MCP server should start automatically
(via `npx`) and authenticate using the client-credentials grant — no browser prompt should
appear.

## Reconnecting after a scope change

Whenever `XERO_SCOPES` changes in `.mcp.json`, the Xero **Custom Connection** must be
re-authorised in the Xero Developer portal with the matching scopes — a previously issued
token keeps whatever scopes it was originally granted, so editing `.mcp.json` alone does
not retroactively add or remove permissions on an existing connection. Symptoms of a
stale/mismatched connection show up as `invalid_scope` or "no valid accounting scopes"
errors from Xero's token exchange, not as a proxy or network failure.
