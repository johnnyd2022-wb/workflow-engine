# Public MCP server for Biz-E — plan

Status: **approved by the founder, 15 Nov 2026** (work board `MCP-PUBLIC`). Decisions in §10.
Founder brief (14 Nov 2026): a public MCP for the app that wraps the user's existing Biz-E
credentials, with access levels *read* and *read and write*; MVP is read only. It lives in this
repo but has its own directory and entrypoint outside the main app, and the deploy scripts run
it as its own container.

## 1. What it is, in one paragraph

A producer connects Claude (or ChatGPT, Cursor, any MCP client) to Biz-E by pasting
`https://mcp.biz-e.app/mcp`. The client sends them to the normal Biz-E sign-in page (password +
2FA, or Google), they pick an access level on a consent screen ("Read only" now; "Read and write"
shown as coming later), and from then on the assistant can answer "what's my stock of orris
root", "trace lot 2026-041", "what did batch 88 cost", "which compliance checks are overdue",
seeing exactly what that person can see in the app and nothing more. Every connection is listed
under Settings → Connected apps and can be revoked there.

## 2. Scope

**MVP (this plan's build):**
- OAuth 2.1 sign-in on existing Biz-E accounts (no new passwords, no API keys to copy).
- One access level live: **Read only**. "Read and write" exists in the data model and consent
  screen as disabled, so adding it later is a policy change, not a redesign.
- ~12 read tools over data people already ask about (§6).
- Standalone `mcp` container, deployed to test and prod by the deploy scripts, behind the
  Cloudflare tunnel.
- Connected apps page: list, revoke.

**Not in the MVP:** write tools; MCP resources/prompts (tools only); per-tool permission
picking on consent; org-wide service accounts / API keys for scripts; webhooks; billing gates.

## 3. Architecture

```
MCP client (Claude, ChatGPT…)
   │  Streamable HTTP, Authorization: Bearer <access token>
   ▼
mcp.biz-e.app  ── bize_mcp container (new; stateless; no DB credentials)
   │  /.well-known/oauth-protected-resource → points at the app as authorization server
   │  each tool = one call to an existing Biz-E JSON API route, same bearer token
   ▼
app.biz-e.app  ── existing app container
      /oauth/*            new: authorization server (authlib), consent screen, token endpoint
      /api/core/* etc.    existing routes, unchanged; accept the bearer token as a second way in
      access_policy       unchanged table + one extra rule: a read token only reaches *.view
```

### Decision A: the MCP server calls the app's API; it does not touch the database

| | **Through the API (recommended)** | Direct DB access from the MCP container |
|---|---|---|
| Tenant isolation | The app's tenant filter, as today | Re-implemented; one bug leaks another org's data |
| Permissions | `access_policy.POLICY`, as today | Re-implemented |
| Secrets in the MCP container | None (no DB password, no session key) | DB password |
| Audit / observability | Existing request logs and traces | New |
| Cost | One internal HTTP hop per tool call; the app needs a bearer-token path | Faster; duplicate business logic |

The MCP server is a protocol adapter: tool schemas, argument checks, result shaping, size
limits. All authority stays in the app, so the security surface added is the OAuth server and
the bearer path, both in one place.

### Decision B: the app is the authorization server; the MCP server is only a resource server

"Wrap the existing user credentials" = the person signs in on the real Biz-E login (password +
TOTP, Google sign-in, trusted devices, rate limits, the 2FA policy all apply unchanged) and the
app issues a token bound to that user, their org and the chosen access level. `authlib` is
already a dependency (Google sign-in) and has a Flask OAuth 2.0 server.

Per the MCP authorization spec (verify against the current revision when building; 2025-06-18
and 2025-11-25 differ on client registration):
- MCP server: `GET /.well-known/oauth-protected-resource` (RFC 9728) naming the app as
  authorization server; `401` with `WWW-Authenticate: Bearer resource_metadata=…` when the
  token is missing or bad.
- App: `GET /.well-known/oauth-authorization-server` (RFC 8414), `/oauth/authorize`
  (authorization code + **PKCE S256 required**), `/oauth/token` (code exchange, refresh with
  rotation), `/oauth/revoke` (RFC 7009), and client registration: **Client ID Metadata
  Documents** (the newer spec's default) and **Dynamic Client Registration** (RFC 7591, what
  most clients still use).
- Tokens are **audience-bound** (RFC 8707 `resource` = the MCP URL). The app accepts a bearer
  token only if its audience is the MCP server, so a token can't be replayed somewhere else.

### Decision C: what a token may do = the user's role ∩ the access level

- Access level **Read only** (`bize.read`): the user's own permissions, filtered to the view
  ones (`production.view`, `inventory.view`, `sales.view`, `compliance.view`, `costs.view`…), and
  only `GET`/`HEAD`. An auditor with time-limited access keeps their expiry.
- Access level **Read and write** (`bize.write`, later): the user's full permissions.
  `users.manage` and `settings.manage` stay excluded even then.
- Enforced in the existing `setup_access_policy` hook: when a request came in on a bearer token,
  it checks the same `POLICY` table plus the access level. A `POST` with a read token is a
  `403` even if the user's role could do it. The UI's permission model stays the only source of
  truth.
- Bearer requests carry no cookies, so they are CSRF-exempt by construction. The exemption
  applies only when there is no session cookie *and* a valid bearer token, never on cookie
  requests.

## 4. Data model (app database; migrations in the app)

| Table | Tenant | Purpose |
|---|---|---|
| `oauth_clients` | **global** (a registered client like "Claude" serves every org) | client_id, name, redirect URIs, registration type (DCR / metadata URL), created_at, disabled_at |
| `oauth_grants` | `org_id` | One row per "user connected client X": user_id, client_id, access level, created_at, last_used_at, revoked_at. This is what Connected apps lists. |
| `oauth_authorization_codes` | `org_id` | Hashed code, grant_id, PKCE challenge, redirect URI, resource, expires (60 s), used_at (single use) |
| `oauth_tokens` | `org_id` | SHA-256 of the access token (1 h) and refresh token (30 d, rotated, reuse ⇒ revoke the grant), grant_id, audience, expires_at, revoked_at |

- Tokens are opaque random strings; only their hashes are stored and they are never logged.
- Composite `(org_id, …)` foreign keys, as everywhere else. `oauth_clients` is the one global
  table, and that's deliberate: it holds no tenant data.
- Revoking a grant revokes every token under it. Deactivating a user or changing their password
  kills their grants (same rule as sessions today: GL-A02).
- Org setting `mcp_enabled` (default **off**; an admin turns it on in Settings). Open question
  Q2 below.

## 5. Directory and entrypoint

```
bize_mcp/                     new top-level package (not `mcp/`: that name is the SDK's)
  server.py                   ASGI app: MCP Streamable HTTP at /mcp, /healthz, protected-resource metadata
  config.py                   env only: BIZE_API_BASE_URL, MCP_PUBLIC_URL, BIZE_ISSUER_URL
  client.py                   thin httpx client to the app API, passes the caller's bearer through
  tools/                      one module per area: inventory.py, production.py, trace.py,
                              compliance.py, sales.py, costs.py
  shaping.py                  result trimming (row caps, field selection, cursor pagination)
tests/mcp/                    tool tests against the app's test client; OAuth flow tests
Dockerfile.multi              new target `mcp`
scripts/run_mcp.sh            build + run the container, test|prod (modelled on run_admin.sh)
```

- Built on the official Python MCP SDK (`mcp`, pinned exact version), served by uvicorn.
  Stateless: no sessions held server-side, so it can restart freely.
- It imports nothing from `app/`. Its own small dependency group in `pyproject.toml`, so the
  main app image doesn't grow (or a separate `bize_mcp/pyproject.toml`; build-time choice).

## 6. MVP tools: three layers, three tools (revised 16 Nov 2026, founder)

Replaced the per-route tool list with the founder's design: business knowledge (layer 1), an
OpenAPI catalogue with `x-bize` metadata (layer 2) and Biz-E's own calculations exposed as
operations (layer 3). The model gets three tools, `discover`, `docs` and `execute`, and works as
discover → docs → execute → explain. `execute` is a declarative list of up to five
allowlisted GET calls with references and projections, not model-written code (Code Mode's
sandbox is a larger surface; it stays a later option behind the same gate). Full contract:
spec §"Three layers, three tools", §8.2f OpenAPI, §8.2g Business knowledge, §8.2h OAuth
security check.

## 7. Security and operations

- **Rate limits:** per token on the app's bearer path (Flask-Limiter, e.g. 120/min) and on
  `/oauth/token`; the MCP server also caps concurrent calls per token.
- **Audit:** `audit_logs` row for each grant created or revoked; tool calls are logged with
  user, client and tool name (not arguments), as structured events (`mcp.tool_called`) with
  traces across the hop.
- **Consent screen** shows the client's name *and* its redirect host, the org, and the access
  level. Clients outside the reviewed list are labelled "Unverified app".
- **Kill switches:** org `mcp_enabled` off; `oauth_clients.disabled_at` per client; revoke per
  grant.
- **Tests that must exist:**
  - PKCE wrong verifier; code reuse; expired code.
  - Refresh-token reuse revokes the grant.
  - Wrong audience is rejected.
  - Read token + POST → 403.
  - Read token on an endpoint the role lacks → 403.
  - Token from org A can't see org B (404).
  - Password change ends grants.
  - `mcp_enabled` off → 403.
  - The access-policy coverage test includes the `/oauth/*` endpoints.
- `security-tenant-audit` and `security-audit` run on this feature: it is a new public way in.

## 8. Deployment

- `Dockerfile.multi`: target `mcp` (`ENVIRONMENT`-free, port 8030, `HEALTHCHECK /healthz`).
- `scripts/run_mcp.sh [test|prod]`: like `run_admin.sh`. Container `workflow-engine-mcp-test`
  on loopback 8030 / `workflow-engine-mcp` on 8031, on the app's Docker network so
  `BIZE_API_BASE_URL` is the app container's internal address. No secrets: it holds no DB
  password or session key.
- `scripts/deploy_test_simple.sh` and `scripts/run_prod.sh` start or replace the MCP container
  after the app is healthy. A failed MCP health check fails that deploy step but never rolls back
  the app.
- CI `docker_build_publish` also builds `$CI_REGISTRY_IMAGE/mcp:test-<sha>` / `:prod-<sha>`;
  `deploy_test` runs it; `cd_e2e` adds an MCP smoke: the protected-resource metadata responds,
  the unauthenticated 401 carries the header, and a `tools/list` with a test token works.
- Cloudflare (`terraform/cloudflare`): tunnel ingress `mcp-test.biz-e.app` → 8030,
  `mcp.biz-e.app` → 8031.

## 9. Phases (each an MR to main)

| # | MR | Delivers |
|---|---|---|
| 0 | Spec | `.agents/specs/public-mcp.md` via spec-first, graded by spec-critic: ACs with concrete numbers, the tool list checked against real routes |
| 1 | OAuth in the app | tables + migration, `/oauth/*`, consent screen, bearer path in tenant context, access-level rule in access_policy, all §7 tests. No MCP server yet; testable with curl. |
| 2 | `bize_mcp` | server, read tools, filtering, shaping, tests (in-process app + MCP client) |
| 3 | Deploy | Dockerfile target, `run_mcp.sh`, deploy-script and CI wiring, tunnel hostnames, cd_e2e smoke |
| 4 | Connected apps | Settings page: list grants, revoke, org `mcp_enabled` toggle (Style 1, bottom-sheet dialogs, 375 px) |
| later | Read and write | `bize.write`, write tools with idempotency keys (existing `ApiIdempotencyKey`), confirmations |

## 10. Founder decisions (15 Nov 2026)

1. **Hostnames:** `mcp.biz-e.app` (prod) and `mcp-test.biz-e.app` (test). Authorization server
   on the app: `https://biz-e.app` (prod), `https://test.biz-e.app` (test).
2. **Off by default per org.** An org admin turns it on in Settings **and chooses which roles
   may use it**. Data model: org setting `mcp_enabled` plus `mcp_roles` (built-in roles and
   custom `org_roles`). A user whose role isn't ticked can't complete consent (clear message),
   and their existing grants stop working the moment their role is unticked or changed (checked
   on every request, not only at issue).
3. **Client registration:** open (CIMD + DCR). Clients outside the reviewed list are labelled unverified
   on consent; admins can disable a client.
4. **Who may connect:** the roles ticked in 2.
5. **First tools:** §6 as written.
6. **Plans:** in every plan. Users bring their own AI subscription, so it costs us nothing
   beyond API load, which the rate limits cover.

Phase 4's Settings page therefore carries the on/off switch, the role picker and Connected apps.
The role check is enforced in the bearer path from phase 1, so phase 1 ships the two settings
columns. Until phase 4 they're set by the CLI or tests.

## 11. Risks

- **The MCP auth spec is still moving** (client registration changed between revisions).
  Mitigation: support both CIMD and DCR, and test against Claude and MCP Inspector before
  calling phase 3 done.
- **A new public way in.** Mitigation: all authority in the existing policy table; read-only
  by construction (method + permission filter); audience-bound short-lived tokens; per-org off
  switch.
- **Shared quota on the app:** an assistant can loop on tools. Mitigation: per-token rate
  limits and row caps.
- **Endpoint drift:** tools depend on JSON API shapes. Mitigation: tool tests run against the
  real routes in CI, so a route change that breaks a tool goes red in the same MR.
