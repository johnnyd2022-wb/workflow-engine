# The MCP server (public MCP 8.2c)

`bize_mcp/` is the server an AI assistant connects to (`https://mcp.biz-e.app/mcp`). It is a protocol
adapter: the app stays the only place that knows who someone is and what they may read. The server holds no
database credentials and no app secrets, and imports nothing from `app/`. Spec
`.agents/specs/public-mcp.md`; sign-in walkthrough `docs/public-mcp-oauth.md`.

## Three tools over three layers

| Tool | What it does |
|---|---|
| `discover` | Searches business knowledge (`docs/knowledge/*.md`) and the operations this person may run. An empty query returns the overview and the topic list. |
| `docs` | One concept's full Markdown, or one operation's full contract (parameters, response schema, related operations, example). |
| `execute` | Runs 1–5 allowlisted `GET` operations. A later call may use an earlier result (`{"$from": "a", "path": "inventory_items[0].id"}`); `select` trims a result (fields, `[n]`, `[*]`, `{name: path}`). No code is run. |

The model works as discover → docs → execute → explain. Operations come from the app's OpenAPI document
(`GET /api/openapi.json?audience=mcp`, fetched with the caller's own token and cached 5 minutes per
organisation and permission set). Operations marked `x-bize.kind: calculation` are Biz-E's own figures; the
tool descriptions tell the model to use them rather than do arithmetic.

## What `execute` enforces, outside the model

* An operation runs only if it is a `GET`, has `x-bize.mcp: true`, names a read permission the caller holds,
  and its feature is on for the organisation. Anything else is "Not found" and **no request is made**.
* Params are validated against the operation's schema; undeclared names are refused; path values are
  encoded; only declared query parameters are sent. `limit` is always sent, at most 50.
* The token goes only in the outbound `Authorization` header. No cookies are kept between callers and
  redirects are never followed. Output is also scrubbed of anything shaped like a token.
* Limits: 5 calls, 10 s in total (5 s per call), 50 rows per list, 256 KB of output, 30 `execute` calls a
  minute per caller (the app adds 120 requests a minute per grant).
* Each run writes one `mcp.execute` log event (user, org, client, grant, operation ids, statuses, duration,
  parameter *names* only).

## Running it

```bash
uv sync --extra dev --extra mcp          # the SDK lives in its own optional group
export BIZE_API_BASE_URL=https://dev.biz-e.app   # the app, from where this runs
export MCP_PUBLIC_URL=http://localhost:8030/mcp
export BIZE_ISSUER_URL=http://localhost:8005
uv run uvicorn bize_mcp.server:app --port 8030
curl -s localhost:8030/.well-known/oauth-protected-resource
curl -s -i -X POST localhost:8030/mcp          # 401 with resource_metadata
```

`BIZE_KNOWLEDGE_DIR` (default `docs/knowledge`) points at the Markdown. The app is called over HTTP inside
the container network, so every call carries `X-Forwarded-Proto: https`.

## Testing

`tests/mcp_server/` drives the server in-process (httpx2 ASGI transport) against the real Flask app through
a transport adapter, with tokens minted by 8.2b's helpers. `uv sync --extra dev --extra mcp` first; without
the extra those files skip with that reason.
