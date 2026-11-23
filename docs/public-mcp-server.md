# The MCP server (public MCP 8.2c)

`bize_mcp/` is the server an AI assistant connects to (`https://mcp.biz-e.app/mcp`). It is a protocol
adapter: the app stays the only place that knows who someone is and what they may read. The server holds no
database credentials and no app secrets (its one secret is the shared rate-limit store's password), and imports nothing from `app/`. Spec
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
* List results include `total_count`, and inventory and invoice lists provide server-calculated totals
  for the whole filtered set. The totals are outside the row data and survive a `select` projection.
  Inventory totals describe on-hand quantities by stored unit. Invoice revenue covers authorised and
  paid invoices before credits, in the organisation's base currency and excluding GST. Use these totals
  when reporting across pages.
* Trace, excise and stocktake reconciliation results are complete-or-fail. If a result exceeds the row
  or output limit, `execute` returns `incomplete`, collection counts where available, and a link to
  the relevant Biz-E page.
* **Text from outside the organisation is marked, never rewritten** (design review S6). Customer and
  supplier names and invoice text come from Xero's contacts and bills, so anyone who can put text in Xero
  can put words in front of the assistant. Each operation lists such fields in `x-bize.outside_text`
  (`[{path, origin}]`, `origin` is `xero`; `[]` says there are none; `app/api/openapi/overlay/*.yaml`).
  `execute` copies the list into each result as `outside_text`, `docs` shows it before the call, and an
  operation that does not declare it gets a note saying to treat every text value as someone else's. The
  list is checked against responses built from seeded data: `tests/openapi/test_outside_text.py` plants a marker in the
  Xero-sourced columns it lists (contact, invoice and line text, a bill's payee and reference, a lot's
  supplier, a sale line's product), calls every operation a token can reach, and fails if a marker shows up at
  a path the operation does not declare, or if a declared path was never seen. The excise period needs its own
  org, so a second test seeds it at the service level; its two CCA-transfer paths are declared from reading
  the code and named `UNSEEDED` in that file: that part of the list nothing yet exercises. Columns the tests
  do not plant are not checked, so the list is a best effort, not a proof, and the tool sentence does not
  vouch for fields outside it. Text written by
  contract-customer portal users (messages, approval notes, reorder notes) is not shared with assistants at
  all: no operation can declare it, and a test fails if any module outside `contract_manufacturing` names the
  models or tables it is stored in (it does not follow calls into that feature's services).
  The paths are the operation's own response fields: a `select` that renames a field (`{n: name}`) no longer
  matches them. Marking is not a filter: a prompt-injection can still be read, so the tool descriptions
  say results are data, never instructions, and the Settings page says the same beside the switch.
* Each run writes one `mcp.execute` log event (user, org, client, grant, operation ids, statuses, duration,
  parameter *names* only).

Knowledge topics can define optional `aliases` in their frontmatter for phrases producers use. A
matched alias helps rank the topic and its available operations. The seeded business-question suite
in `tests/mcp_server/test_business_questions.py` checks discovery and real tool results through the
shipped catalogue. It runs without an external language model.

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

`BIZE_KNOWLEDGE_DIR` (default `docs/knowledge`) points at the Markdown. Every call to the app carries
`X-Forwarded-Proto: https`, so the app's HTTPS redirect never bounces a hop that is not TLS.

## Deploying it (8.2d)

The `mcp` target in `Dockerfile.multi` is the only image that carries the SDK (`uv sync --extra mcp`). It
listens on 8030 and its health check is `/healthz`. `scripts/run_mcp.sh [test|prod]` starts it:

| | test | prod |
|---|---|---|
| Container | `workflow-engine-mcp-test` | `workflow-engine-mcp` |
| Published on | `127.0.0.1:8030` | `127.0.0.1:8031` |
| Docker network | `workflow-observability` (the test app's) | `workflow-engine-prod` (the production app's) |
| `BIZE_API_BASE_URL` | `https://workflow-engine-test:8001` | `https://workflow-engine-prod:8000` |
| Public address (`https://…/mcp`) | `mcp-test.biz-e.app` | `mcp.biz-e.app` |

* **One secret.** The container is told three addresses, one TLS switch and, for its rate-limit windows,
  the shared Valkey: `BIZE_RATELIMIT_URI=redis://valkey-<target>:6379/0` (no password in it) and
  `VALKEY_PASSWORD`, passed by name so the value is never on a command line. That password is its only
  secret (design review S4). Production requires it; on test, without it the windows are per process. The addresses
  come from the app's own `[mcp]` section (`app/config/<target>.ini`), never from the operator's shell, so
  the resource the server advertises is the one the app binds tokens to.
* **`BIZE_API_VERIFY_TLS=false`.** The app serves a self-signed certificate under a name that is not its
  container's, so the call from this container to the app is not verified. That hop never leaves the private
  Docker network between two containers on one host (the tunnel and the app's health checks skip
  verification for the same reason). Everywhere else the default verifies.
* **Candidate, health check, swap.** A candidate with no host port starts beside the running container and
  must answer `/healthz?deep=1` (which also calls the app's `/healthcheck`, so a wrong address or TLS setting
  fails the deploy). Then the running container is renamed and stopped, the new one takes the name and the
  port and is checked again. A failure at either step leaves, or puts back, the previous container, and the
  script exits non-zero.
* **Deploy scripts.** `scripts/deploy_test_simple.sh` (CD: `<app-image> <mcp-image>`) and `scripts/run_prod.sh`
  call it once the app is healthy. A failure exits 4 from the first and non-zero from the second, and never
  rolls the app back.
* **CI.** `docker_build_publish` pushes `mcp:test-<sha>` and `mcp:prod-<sha>` (the same bytes under two tags);
  `deploy_test` runs the test container from the first; `cd_e2e` runs `tests/e2e/test_mcp_smoke.py` against it.
* **Tunnel.** `terraform/cloudflare/main.tf` routes `mcp-test.biz-e.app` and `mcp.biz-e.app` to the two
  loopback ports. The tunnel module puts the founders' Cloudflare Access application in front of every
  `biz-e.app` hostname, so these two are founders-only until Access is changed for them.

## Testing

`tests/mcp_server/` drives the server in-process (httpx2 ASGI transport) against the real Flask app through
a transport adapter, with tokens minted by 8.2b's helpers. `uv sync --extra dev --extra mcp` first; without
the extra those files skip with that reason.
