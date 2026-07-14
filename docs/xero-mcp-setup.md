# Xero access for Claude Code — status and options

**Status (July 2026): the self-hosted Xero MCP server route is parked.** The repo no
longer ships an `.mcp.json` for it. What works today is the **claude.ai Xero connector**;
what it can't do (invoice line items) has known options below, none currently worth the
plumbing.

## What works: the claude.ai Xero connector

The claude.ai Xero connector is authorised against Whistlebird Limited via the standard
OAuth browser flow (`/mcp` in a Claude Code session → "claude.ai Xero" → approve in
browser). No Xero developer app, subscription, or repo config needed.

It exposes **summary reports only**: organisation info, P&L, top customers by revenue,
receivables snapshot, cash position, financial position, financial year. That covers
sales-by-customer and P&L questions. It does **not** expose invoice line items, so
by-product breakdowns and customer × product matrices are not possible through it —
Whistlebird's chart of accounts books all revenue to a single "Sales" account, so the
P&L carries no product split either.

## Why the self-hosted MCP server route is parked

The official `@xeroapi/xero-mcp-server` (which does expose line-item access) supports
exactly two auth modes, and both are blocked or not worth it right now:

1. **Client credentials (`XERO_CLIENT_ID`/`XERO_CLIENT_SECRET`)** — requires a Xero
   **Custom Connection**, which needs a paid per-org subscription purchased through the
   org's billing account. Whistlebird's Xero is managed through the accountant's
   account, so this isn't available to us.
2. **Bearer token (`XERO_CLIENT_BEARER_TOKEN`)** — you run the OAuth flow yourself
   (a free Web or PKCE app works) and hand the server an access token. Xero access
   tokens last 30 minutes and refresh tokens are single-use rolling, so this needs a
   wrapper script that refreshes and persists tokens on every startup. Workable locally,
   fragile on Claude Code web (static env vars can't hold a rotating refresh token).
   Decided not worth building for now.

## Hard-won facts, so nobody relearns them

- **The developer portal is the source of truth for scope names.** Xero is mid-transition
  between old broad scopes (`accounting.transactions`, `accounting.reports.read`) and new
  granular ones (`accounting.invoices`, `accounting.payments.read`, per-report scopes).
  Published cutover timelines did not match observed behaviour — a Web app created in
  July 2026 still offered old-style scopes. Configure whatever the portal shows for
  *your* app; the official MCP server itself "tries V1 scopes first and falls back to V2".
- **A token exchange can "succeed" while granting no accounting scopes.** Requesting
  scopes the app/connection isn't authorised for yields a token with no accounting
  scopes, and every API call then fails with "no valid accounting scopes" — which looks
  like a network/proxy failure but isn't.
- **Scope changes require re-authorising the connection.** An already-issued token keeps
  its original scopes; editing config only changes what is *requested* next time.
- **Client credentials is custom-connection-only.** Pasting a Web app's client ID/secret
  into a client-credentials integration fails regardless of scopes — Web apps aren't
  allowed that grant type.

## If line-item reporting becomes worth it later

In rough order of fit:

1. **Extend the app's own CRM/Xero integration** (`crm_enabled` feature) with a report
   endpoint — the codebase already holds working Xero credentials for invoicing.
2. **Bearer-token wrapper + PKCE app** for local sessions, as sketched above (no client
   secret to store; redirect to `http://localhost:<port>/callback`).
3. **One-off**: Xero web UI → Sales reports, group by item, export.

As always: secret values live in KeePassXC (`workflow-engine` group) or environment
settings — never in a committed file, commit message, or MR description.
