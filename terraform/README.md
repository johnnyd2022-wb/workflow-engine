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

## Cloudflare tunnel and sites

`cloudflare/main.tf` is one call to `modules/cloudflare-tunnel`: the tunnel's name and a
map of hostname => origin. The module does the rest, the same way for every site.

### Adding a site

Add a line to `routes` and apply:

```hcl
"new-site.biz-e.app" = "https://host.docker.internal:8030"
```

```bash
./terraform/tf.py plan -out=review.tfplan
./terraform/tf.py apply review.tfplan
```

For a hostname in the `biz-e.app` zone the module creates, in this order, a Cloudflare
Access application, the tunnel route, and the DNS record, so a hostname is never reachable
before Access is in front of it. There is no setting to publish a site without Access.

### What every site gets

All of this lives in the module's `locals`; change it there and it changes everywhere.

| | Setting |
| --- | --- |
| Who gets in | The "Founder access" policy: the founders Access group (the group itself is managed in the Cloudflare dashboard). |
| How they sign in | One identity provider, with the provider chooser skipped. |
| Access session | 730 hours. |
| Origin | No TLS verification (origins use a self-signed certificate), HTTP/2 to origin, connect timeout 1800s, TLS timeout 600s, keep-alive 1800s, TCP keep-alive 600s, 600 keep-alive connections. |

Each timeout is the longest any route had before they were made the same. Non-HTTP origins
(`rdp://`) take none of the origin settings.

### Hostnames in other zones

The tunnel also serves `inventory.whistlebird.co.nz`, `test-inventory.whistlebird.co.nz`
and `access.whistlebird.co.nz`. They are in `routes` so their tunnel routes are kept, with
the same origin settings as everything else, but their DNS records and Access applications
are managed outside this root. Tunnel configuration is managed as a whole: a hostname
removed from `routes` stops being served. `www.biz-e.app` has an old parked-page `A` record
that is not managed here.

### State

The tunnel, its configuration, the DNS records, the Access applications and the Founder
access policy were created in the dashboard and imported; no import blocks are kept in the
configuration. Keep the backend volume backed up. On an empty backend, import them again
with `./terraform/tf.py import` before applying.

The API token needs Cloudflare Tunnel Write, DNS Write and **Access: Apps and Policies
Write**. Origin addresses resolve from the cloudflared connector on this machine.

## GitLab CI on the local runner

Terraform changes targeting `main` get a `terraform_cloudflare_plan` job. Its
GitLab MR report shows create/update/delete counts. The full plan is also posted
as an unresolved review thread in the MR discussion. Read the plan, discuss any
questions, then **Resolve thread** using GitLab's normal review controls. There
is no manual CI review job. CI can finish green, while GitLab blocks merge until
all threads are resolved. The project must enable **All threads must be resolved**;
planning fails if that check is disabled. Each new plan opens a fresh thread and
supersedes older automated plan threads without replies from the same bot identity.
Threads containing conversations stay open for their reviewers. `plan.txt` remains available in artifacts,
which expire after 14 days.
Only same-project, detached MR pipelines are supported.

After the final plan and explicit review succeed, Johnny must approve the MR and merge it. The
protected `terraform_cloudflare_apply` runner then checks the merged MR, final
successful pipeline and approval timestamp using GitLab's API. It also verifies
that the exact plan thread is intact and was resolved by the configured approver
before merge. Missing, edited, reopened or incorrectly resolved threads stop
apply. It makes a fresh
plan against the shared PostgreSQL state and applies only if the configuration
and planned changes match the reviewed MR plan. Direct pushes, expired/missing
artifacts, superseded main commits, missing approvals and differing plans fail
closed. Replan and approve a new MR if those checks fail. Other MRs do not trigger
Terraform jobs unless they change the Terraform configuration or CI integration.

Both jobs share a GitLab resource group, and the backend also takes PostgreSQL
advisory locks. Avoid simultaneous manual applies while reviewing an MR.

### Credentials and runner setup

Run locally, with the existing runner manager and state database running:

```bash
./terraform/tf.py db-up
./terraform/setup_runner.py
# To refresh only the plan runner:
./terraform/setup_runner.py --plan-only
```

The setup script reads the existing Cloudflare token for both runners, as well
as the account and zone IDs. It creates separate database credentials in
KeePassXC: `workflow-engine/terraform-state-db-plan` (read-only state access)
and `workflow-engine/terraform-state-db-apply` (state writes). Runner registration
tokens are saved at `workflow-engine/terraform-runner-plan` and
`workflow-engine/terraform-runner-apply`.

Save a GitLab personal access token with `api` scope in the Password field
of `workflow-engine/terraform-gitlab-ci-review`. Its owner must be able to read
this project's MR approvals and developer-access job artifacts. The plan runner uses it to create plan threads and supersede older automated
threads; apply uses it for GET requests. The runner environment retains the historical
`TERRAFORM_GITLAB_READ_TOKEN` variable name. The configured approver is the GitLab user running
the setup script. GitLab currently allows MRs with no required approvals; the
apply job still requires that user's approval after the final plan completes.

Secrets are injected into job environments from the runner manager's private
`/etc/gitlab-runner/config.toml`, backed by the existing persistent host directory
`/home/johnny/.config/gitlab-runner`. The file is mode 0600 and is outside Git.
No Terraform credentials are GitLab CI variables or Docker image layers. Neither
Terraform runner mounts the host Docker socket or KeePass database into jobs.
The database is reachable as `state-db:5432` on the existing
`workflow-engine-terraform_default` Docker network, without exposing its host
port externally. The plan runner is tagged `terraform-plan`; the apply runner
is tagged `terraform-apply` and accepts protected refs only.

Rerun setup after rotating secrets, changing tenant IDs or replacing the runner
configuration. Credentials are loaded at setup time, not fetched from KeePassXC
on every job. Treat the local runner host and same-project MR authors as trusted:
both jobs receive the existing Cloudflare token with write permissions.
