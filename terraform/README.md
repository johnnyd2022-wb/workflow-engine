# Terraform infrastructure

Each immediate subdirectory is an independent Terraform root. `cloudflare/` has
its own provider lockfile, `.terraform/` directory and `cloudflare` PostgreSQL
schema. Shared modules live in `modules/`. The state itself is stored in
PostgreSQL, rather than a local statefile. Future roots must use a distinct
backend schema and can be selected with `--stack NAME` before the subcommand.

The repository's tracked `.dockerignore` excludes all of `terraform/` from the
Docker build context, including the test, admin and production images.

## Requirements and secrets

Install Terraform >= 1.5 and < 2.0, Python 3, KeePassXC CLI, Docker and Docker
Compose v2 with `up --wait` support. The Cloudflare provider is pinned to 5.27.0,
the latest registry release when this directory was created. Commit
`cloudflare/.terraform.lock.hcl` when changing the provider version.

The wrapper reads these KeePassXC entries:

| Entry | Attribute | Purpose |
| --- | --- | --- |
| `workflow-engine/terraform-state-db` | `Password` | PostgreSQL password |
| `workflow-engine/terraform-cloudflare` | `Password` | Cloudflare API token |
| `workflow-engine/terraform-cloudflare` | `Account ID` | Custom attribute: Cloudflare account ID |
| `workflow-engine/terraform-cloudflare` | `Zone ID` | Custom attribute: biz-e.app zone ID |

The state database entry has been created with username `terraform`. The
Cloudflare entry is a **placeholder contract**; add it with real values before
planning or applying. Account and zone IDs are required 32-character IDs.
Use an API token scoped to the relevant account/zone with **Cloudflare Tunnel
Write** and **DNS Write** permissions (and any corresponding read permissions
required by your token configuration).

The database path defaults to the application's existing local path,
`/mnt/c/Users/OEM/Documents/workflow-engine/Passwords.kdbx`. Override it with
`KEEPASS_KDBX_PATH`. `KEEPASS_PASSWORD` is supported; otherwise the wrapper
prompts once without echoing. Entry paths can be overridden with
`TERRAFORM_STATE_DB_ENTRY` and `TERRAFORM_CLOUDFLARE_ENTRY`.
Secrets are read directly by the wrapper without printing them, supplied to
child processes through environment variables, and never written to `.tfvars`
or backend config files. The KeePassXC master password is removed from child
process environments. Terraform state and saved plans may contain sensitive
resource data; generated files are ignored by Git.

## Usage

Run from anywhere; the wrapper changes to the selected Terraform root and
forwards the positional subcommand and its arguments unchanged:

```bash
./terraform/tf.py db-up
./terraform/tf.py init
./terraform/tf.py fmt
./terraform/tf.py validate
./terraform/tf.py plan -out=review.tfplan
./terraform/tf.py apply review.tfplan
./terraform/tf.py console
./terraform/tf.py output
./terraform/tf.py db-status
./terraform/tf.py db-stop
# A future root:
./terraform/tf.py --stack another-root init
```

`init` starts the backend and installs providers without requiring Cloudflare
credentials. Terraform commands that need the backend automatically start and
wait for PostgreSQL. `fmt`, `validate` and `version` run without loading secrets
or starting Docker; `validate` expects providers to have been installed by
`init`. Other commands do not run `init` implicitly.

## State database

`compose.yml` runs a dedicated `postgres:18-bookworm` container in Compose
project `workflow-engine-terraform`, database `terraform_state`, user
`terraform`, exposed only at `127.0.0.1:8402`. To choose another port, set
`TERRAFORM_STATE_DB_PORT` consistently on wrapper invocations.
The Docker named volume `workflow-engine-terraform_state-db-pg18` retains state
across container restarts and `db-stop`. PostgreSQL 18 stores its data in
`/var/lib/postgresql/18/docker`, with the volume mounted at `/var/lib/postgresql`.
The `18-bookworm` tag follows stable PostgreSQL 18 patch releases (currently 18.6).
Back up that volume or use `pg_dump`
with the KeePassXC credentials before moving/removing it. PostgreSQL only uses
`POSTGRES_PASSWORD` to initialize a new volume: changing the KeePassXC password
later also requires rotating the database role password.

Major version upgrades require a dump/restore or `pg_upgrade`; changing the image
tag alone does not migrate data. The initial PostgreSQL 17 backend was dumped
and restored into the new PostgreSQL 18 volume. The original
`workflow-engine-terraform_state-db` volume is retained for rollback.

The `pg` backend uses PostgreSQL advisory locks for concurrent operations;
locks release when the database connection closes. `force-unlock` is not
supported by this backend. Each root uses its own schema; Terraform CLI
workspaces, if used, are separate rows within that schema. Normal use is the
`default` CLI workspace within the `cloudflare/` root. The loopback database
is local to this Docker host; remote runners need a separately configured,
reachable backend before they can share this state.

## Existing shared Cloudflare tunnel

`cloudflare/main.tf` models the existing remotely managed tunnel
`wb_inventory_maungaraki` (Terraform key `maungaraki`). The local cloudflared
container already connects to this tunnel; no new connector or tunnel token is
needed to adopt its resources in Terraform.

| Managed DNS hostname | Origin | No TLS verify |
| --- | --- | --- |
| `test.biz-e.app` | `https://host.docker.internal:8001` | true |
| `admin-test.biz-e.app` | `https://host.docker.internal:8020` | true |
| `dev.biz-e.app` | `https://172.26.121.16:8005` | true |

The same tunnel carries `inventory.whistlebird.co.nz`,
`test-inventory.whistlebird.co.nz` and `access.whistlebird.co.nz`. The complete
route map retains those origins, origin settings, existing ingress order and
final 404 rule. Only the three biz-e.app DNS records are managed here;
Whistlebird DNS records are outside this root's scope.

The reusable module accepts a complete route map, an optional ingress order,
and an optional subset of hostnames to manage in DNS. Shared tunnel
configuration is managed as a whole: keep every route that needs to remain
active in the map, including routes outside the managed DNS zone. The module
validates that the explicit ingress order includes every route exactly once
and that managed DNS hostnames are present in the route map.

`cloudflare/imports.tf` records the existing tunnel, tunnel configuration and
three DNS record IDs using the account/zone IDs loaded from KeePassXC. On an
empty backend, `plan` proposes importing those existing resources instead of
creating duplicates. After adoption the import blocks are no-ops. Review the
plan before applying: resource imports do not themselves change live routing,
but differences in the configuration can still propose updates.

Origin addresses resolve from the **cloudflared connector**. The existing
origins and connector are retained. Access applications/policies are not
managed by this root.
