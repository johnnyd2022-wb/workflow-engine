#!/usr/bin/env python3
"""Refresh dedicated local Terraform runners from KeePassXC (never run in CI)."""

import argparse
import json
import os
import secrets as random
import subprocess
import sys
import tomllib

from tf import Secrets

PROJECT = 76311154
MANAGER = "gitlab-runner"
NETWORK = "workflow-engine-terraform_default"
IMAGE = "hashicorp/terraform:1.16.5"
CONFIG = "/etc/gitlab-runner/config.toml"


def command(args, *, data=None):
    env = os.environ.copy()
    env.pop("KEEPASS_PASSWORD", None)
    result = subprocess.run(args, input=data, text=True, capture_output=True, env=env)
    if result.returncode:
        # Inputs and server responses can contain passwords/tokens.
        raise RuntimeError(f"{args[0]} operation failed (exit {result.returncode}); no secret output displayed")
    return result.stdout


def api(path, payload=None):
    args = ["glab", "api", path]
    if payload is not None:
        args += ["--method", "POST", "--header", "Content-Type: application/json", "--input", "-"]
    return json.loads(command(args, data=json.dumps(payload) if payload is not None else None))


def stored_or_create(vault, entry, username, url, value=None):
    try:
        return vault.read(entry, "Password")
    except RuntimeError:
        password = value or random.token_hex(24)
        command(
            ["keepassxc-cli", "add", "-q", "-p", "-u", username, "--url", url, vault.database, entry],
            data=vault.password + "\n" + password + "\n",
        )
        return password


def database_role(role, password, writable):
    escaped = password.replace("'", "''")
    sql = f"""
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
  CREATE ROLE {role} LOGIN;
 END IF;
END $$;
ALTER ROLE {role} PASSWORD '{escaped}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE terraform_state TO {role};
GRANT USAGE ON SCHEMA cloudflare TO {role};
REVOKE ALL ON cloudflare.states FROM {role};
GRANT {"SELECT, INSERT, UPDATE, DELETE" if writable else "SELECT"} ON cloudflare.states TO {role};
ALTER ROLE {role} SET default_transaction_read_only = {"off" if writable else "on"};
"""
    if writable:
        sql += f"GRANT USAGE, SELECT ON SEQUENCE public.global_states_id_seq TO {role};\n"
    command(
        [
            "docker",
            "exec",
            "-i",
            "workflow-engine-terraform-state-db-1",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "terraform",
            "-d",
            "terraform_state",
        ],
        data=sql,
    )


def runner_block(name, runner_id, token, env):
    # JSON string escaping is also valid for these TOML basic strings.
    quoted = json.dumps
    return f"""[[runners]]
  name = {quoted(name)}
  url = "https://gitlab.com"
  id = {runner_id}
  token = {quoted(token)}
  executor = "docker"
  limit = 1
  request_concurrency = 1
  environment = {quoted([f"{key}={value}" for key, value in env.items()])}
  [runners.docker]
    image = {quoted(IMAGE)}
    privileged = false
    network_mode = {quoted(NETWORK)}
    volumes = ["/cache"]
    allowed_images = [{quoted(IMAGE)}]
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-only", action="store_true", help="Provision the plan runner while the review PAT is pending"
    )
    args = parser.parse_args()
    vault = Secrets()
    cf = "workflow-engine/terraform-cloudflare"
    shared = {
        "CLOUDFLARE_API_TOKEN": vault.read(cf, "Password"),
        "TF_VAR_account_id": vault.read(cf, "Account ID"),
        "TF_VAR_zone_id": vault.read(cf, "Zone ID"),
    }
    review_token = None if args.plan_only else vault.read("workflow-engine/terraform-gitlab-ci-review", "Password")
    user = api("user")
    if review_token:
        # Verify the supplied credential can read the approval endpoint before configuring apply.
        from urllib.request import Request, urlopen

        req = Request(
            f"https://gitlab.com/api/v4/projects/{PROJECT}/merge_requests/500/approvals",
            headers={"PRIVATE-TOKEN": review_token},
        )
        with urlopen(req, timeout=30) as response:
            json.load(response)
    config = command(["docker", "exec", MANAGER, "cat", CONFIG])
    blocks = config.split("[[runners]]")
    managed = {"terraform-plan", "terraform-apply"} if not args.plan_only else {"terraform-plan"}
    existing = {}
    retained = [blocks[0]]
    for block in blocks[1:]:
        parsed = tomllib.loads("[[runners]]" + block)["runners"][0]
        if parsed.get("name") in managed:
            existing[parsed["name"]] = parsed
        else:
            retained.append("[[runners]]" + block)
    for kind in ("plan",) if args.plan_only else ("plan", "apply"):
        name = f"terraform-{kind}"
        role = f"terraform_{kind}"
        password = stored_or_create(
            vault,
            f"workflow-engine/terraform-state-db-{kind}",
            role,
            f"postgres://{role}@state-db:5432/terraform_state",
        )
        database_role(role, password, writable=kind == "apply")
        old = existing.get(name)
        if old:
            runner_id, token = old["id"], old["token"]
        else:
            runner = api(
                "user/runners",
                {
                    "runner_type": "project_type",
                    "project_id": PROJECT,
                    "description": name,
                    "tag_list": [name],
                    "run_untagged": False,
                    "locked": True,
                    "access_level": "ref_protected" if kind == "apply" else "not_protected",
                },
            )
            runner_id, token = runner["id"], runner["token"]
            stored_or_create(
                vault, f"workflow-engine/terraform-runner-{kind}", str(runner_id), "https://gitlab.com", token
            )
        env = shared | {
            "PG_CONN_STR": f"postgres://{role}@state-db:5432/terraform_state?sslmode=disable",
            "PGPASSWORD": password,
        }
        if kind == "apply":
            env |= {"TERRAFORM_GITLAB_READ_TOKEN": review_token, "TERRAFORM_APPROVER_ID": str(user["id"])}
        retained.append(runner_block(name, runner_id, token, env))
        print(f"Prepared {name}: runner {runner_id}, database role {role}")
    updated = "\n".join(retained)
    tomllib.loads(updated)
    # Configuration is outside Git, on the runner manager's persistent host mount.
    command(
        [
            "docker",
            "exec",
            "-i",
            MANAGER,
            "sh",
            "-c",
            f"umask 077; cat > {CONFIG}.terraform-new && chmod 600 {CONFIG}.terraform-new && mv {CONFIG}.terraform-new {CONFIG}",
        ],
        data=updated,
    )
    print("Runner configuration refreshed from KeePassXC; GitLab Runner reloads it automatically.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # urllib exceptions must not print request credentials.
        print(
            f"Runner setup failed: {type(error).__name__}: {str(error) if isinstance(error, RuntimeError) else 'check local setup and credentials'}",
            file=sys.stderr,
        )
        sys.exit(1)
