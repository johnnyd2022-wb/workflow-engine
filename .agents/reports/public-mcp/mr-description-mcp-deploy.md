## Public MCP 8.2d: its own container

Spec `.agents/specs/public-mcp.md` "Deploy (8.2d)". 8.2c (!725) has merged.

### What it delivers
- `Dockerfile.multi` target `mcp`: `FROM base`, the only stage with `uv sync --extra mcp`, port 8030, `HEALTHCHECK /healthz`, uvicorn. `.dockerignore` re-includes `docs/knowledge/`.
- `scripts/run_mcp.sh [test|prod]`: candidate, deep health check, swap; previous container kept or put back on failure. Loopback-only publish (`127.0.0.1:8030` test, `:8031` prod), on the app's Docker network, no secrets (three addresses from the app's `[mcp]` config plus one TLS switch).
- `deploy_test_simple.sh <app-image> <mcp-image>` and `run_prod.sh` call it once the app is healthy. An MCP failure exits 4 / non-zero and never rolls the app back.
- CI: `docker_build_publish` pushes `mcp:test-<sha>` and `mcp:prod-<sha>`; `deploy_test` runs the test container; `cd_e2e` runs `tests/e2e/test_mcp_smoke.py`.
- `terraform/cloudflare`: routes `mcp-test.biz-e.app` and `mcp.biz-e.app`.
- `bize_mcp`: `BIZE_API_VERIFY_TLS` (default strict). Needed: the app serves a self-signed cert, and with strict verification the deep health check returned 503 (reproduced).

### AC to test
| AC | Proof |
|---|---|
| AC30 | Real `docker build --target mcp` succeeded; a container answered `/healthz` and `/healthz?deep=1` (200); `tests/test_mcp_deploy_wiring.py` |
| AC31 | `tests/test_run_mcp.py` (25, fake daemon); real `run_mcp.sh` run: first deploy, swap, failed candidate kept the running container; `tests/test_prod_deploy.py`, `tests/test_deploy_test_mcp.py` |
| AC32 | CI wiring in `tests/test_mcp_deploy_wiring.py`; `tests/e2e/test_mcp_smoke.py` passed 5/5 against a real container and the live test app, and fails 3/5 when TLS verification is left strict |

### Terraform plan
CI's `terraform_cloudflare_plan` posts the plan on this MR (thread). I did not run it locally and never ran apply. Expected from the module: per new hostname one Access application and one DNS CNAME, plus an in-place update of the tunnel config. Nothing else changes.

### Assumptions
- Tunnel origins are `http://host.docker.internal:<port>` like every other route (uvicorn is plain HTTP), not a literal `127.0.0.1`.
- Smoke test asserts the real tools `discover`, `docs`, `execute` (spec text still says `search_inventory`).
- `mcp:test-<sha>` and `mcp:prod-<sha>` are the same bytes; no `mcp:test-stable`; the `:test-stable` rollback leaves the MCP container alone.
- An MCP image build failure fails `docker_build_publish`, as the spec places the build there.

### Review
`.agents/reports/public-mcp/build-review-mcp-deploy.md`. Open items: the tracked TLS key is in every image including this one (not new); shellcheck not run.

### Founder, after merge
1. Approve the Terraform plan thread; apply runs after merge.
2. **Decide Cloudflare Access for the MCP hosts (and the app's `/oauth/*`, `/.well-known/*`).** The module puts founders-only Access on every `biz-e.app` host; hosted assistants cannot pass it.
3. First prod run: `scripts/run_prod.sh` starts `workflow-engine-mcp`; if it fails, the app stays up, fix and run `scripts/run_mcp.sh prod`.
4. Enable an org: `uv run workflow mcp enable --org-id <id> --roles admin,member`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
