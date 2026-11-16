# Build review: public MCP 8.2d (its own container)

Advisory. The delegated `/code-review` subagent died on a rate limit, so this is the builder's own pass
over `git diff origin/main...HEAD` against the brief (secrets, loopback, rollback, app never rolled back,
terraform scope). Each point was checked by reading the code, and the behaviours by running them:
a real `docker build --target mcp`, and `run_mcp.sh` run for real (first deploy, swap, failed candidate)
on a spare port, plus the fake-daemon tests.

| # | Finding | Verdict |
|---|---|---|
| F1 | The `mcp` image is `FROM base`, so `COPY . .` brings in the tracked `app/tls/app_cert.key` (a Cloudflare Origin key). | **Not new** (every app image already has it) and the spec fixes `FROM base`. Follow-up: untrack the key or give `mcp` a lean stage. No env secret is passed (tested with canary values). |
| F2 | The container-to-app hop is HTTPS with a self-signed cert under a name it does not cover; strict verification made `/healthz?deep=1` return 503 (reproduced). | **Fixed**: `BIZE_API_VERIFY_TLS=false`, set only by `run_mcp.sh`; default and typos stay strict (tested with a real TLS server). |
| F3 | Ambient `BIZE_API_BASE_URL` / `MCP_PUBLIC_URL` / `BIZE_ISSUER_URL` (documented for local runs) could leak into a deploy. | **Fixed**: addresses come from `app/config/<target>.ini`; tested. |
| F4 | An MCP failure must not trigger the CI app rollback (exit 3). | **Verified**: MCP failures exit 4 (script) / non-zero (`run_prod.sh`, after `deploy_app` has committed); rollback invokes the app image only. Tested. |
| F5 | Rollback paths in `run_mcp.sh`: bad candidate, rename/stop failure, new container failing to start or to be healthy, first deploy, signals. | **Verified** by tests and by running a failed candidate for real: the running container kept serving. |
| F6 | Publish is `127.0.0.1:<port>:8030` only; `--cap-drop ALL`, `no-new-privileges`. | **Verified**. |
| F7 | The tunnel module puts a founders-only Cloudflare Access application in front of every `biz-e.app` host, including the two new ones. Hosted assistants cannot pass it. | **Not changed** (out of scope; no bypass setting exists). Founder decision before the first real connection. |
| F8 | Spec says the smoke test expects `search_inventory`; 8.2c ships `discover`, `docs`, `execute`. | Test asserts the three real tools. |
| F9 | Origins use `http://host.docker.internal:<port>` (uvicorn is plain HTTP), not the spec's literal `127.0.0.1`, matching every other route. | Assumption, stated in the MR. |
| F10 | `shellcheck` is not installed and was not run; `bash -n` is in the tests. Local `terraform plan` was not run (the wrapper needs approval here); CI's `terraform_cloudflare_plan` posts it. | Noted in the MR. |
