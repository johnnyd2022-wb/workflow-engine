# Xero MCP setup (Claude Code on the web)

This repo ships a committed `.mcp.json` at the repo root that wires the **official Xero
MCP server** (`@xeroapi/xero-mcp-server`) into Claude Code sessions. Once the two secrets
below are set in the Claude Code web environment, any session in this repo can query Xero
(invoices, contacts, sales, reports).

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
        "XERO_CLIENT_SECRET": "${XERO_CLIENT_SECRET}"
      }
    }
  }
}
```

The `${...}` placeholders are resolved from environment variables at MCP server startup.
**No secret value is ever committed to this file or to git history** — only the two
variable names are checked in.

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
