#!/usr/bin/env python3
"""Run Terraform in an isolated root with KeePassXC credentials in memory."""

import argparse
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_KDBX = "/mnt/c/Users/OEM/Documents/workflow-engine/Passwords.kdbx"


class Secrets:
    def __init__(self):
        self.database = os.getenv("KEEPASS_KDBX_PATH", DEFAULT_KDBX)
        if not Path(self.database).is_file():
            raise RuntimeError("KeePassXC database not found; set KEEPASS_KDBX_PATH.")
        if not shutil.which("keepassxc-cli"):
            raise RuntimeError("Install keepassxc-cli before loading credentials.")
        self.password = os.getenv("KEEPASS_PASSWORD") or getpass.getpass("KeePassXC database password: ")

    def read(self, entry, attribute):
        result = subprocess.run(
            ["keepassxc-cli", "show", "-q", "-s", "-a", attribute, self.database, entry],
            input=self.password + "\n",
            text=True,
            capture_output=True,
            timeout=30,
        )
        value = result.stdout.rstrip("\r\n")
        if result.returncode or not value or value == "PROTECTED":
            # Never include CLI stdout/stderr: it may contain secret material.
            raise RuntimeError(f"Cannot read {attribute!r} from KeePassXC entry {entry!r}.")
        return value


def run(command, env, cwd=ROOT):
    result = subprocess.run(command, env=env, cwd=cwd)
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Run Terraform with KeePassXC secrets (default root: cloudflare).",
        epilog="Examples: tf.py init; tf.py plan -out=review.tfplan; tf.py apply review.tfplan; tf.py db-up",
    )
    parser.add_argument("--stack", default="cloudflare", help="Terraform subdirectory (before command)")
    parser.add_argument("command", help="Terraform command, or db-up / db-stop / db-status")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded unchanged to Terraform")
    options = parser.parse_args()
    stack = (ROOT / options.stack).resolve()
    if stack.parent != ROOT or not stack.is_dir() or not any(stack.glob("*.tf")):
        parser.error("--stack must name an immediate Terraform root subdirectory")
    if options.args and options.args[0] == "--":
        options.args.pop(0)
    if any(arg.startswith("-chdir") for arg in options.args):
        parser.error("Use --stack to choose the Terraform root")
    if options.command.startswith("-"):
        parser.error("Supply a Terraform subcommand")

    env = os.environ.copy()
    env.pop("KEEPASS_PASSWORD", None)
    env["TF_DATA_DIR"] = str(stack / ".terraform")
    env["TF_IN_AUTOMATION"] = "1"
    secrets = None
    db_commands = {"db-up", "db-stop", "db-status"}
    offline_commands = {"fmt", "validate", "version"}
    if options.command not in db_commands and not shutil.which("terraform"):
        raise RuntimeError("Install Terraform >= 1.5 and < 2.0 and add it to PATH.")

    if options.command not in offline_commands:
        secrets = Secrets()
        entry = os.getenv("TERRAFORM_STATE_DB_ENTRY", "workflow-engine/terraform-state-db")
        password = secrets.read(entry, "Password")
        env["TERRAFORM_STATE_DB_PASSWORD"] = password
        env["PGPASSWORD"] = password
        # Do not put passwords in connection URLs: backend metadata is written to disk.
        port = os.getenv("TERRAFORM_STATE_DB_PORT", "8402")
        if not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise RuntimeError("TERRAFORM_STATE_DB_PORT must be a valid TCP port")
        env["PG_CONN_STR"] = f"postgres://terraform@127.0.0.1:{port}/terraform_state?sslmode=disable"
        compose = ["docker", "compose", "-f", str(ROOT / "compose.yml")]
        if options.command in db_commands:
            if options.args:
                parser.error("Database commands do not accept extra arguments")
            arguments = {
                "db-up": ["up", "-d", "--wait", "--wait-timeout", "90", "state-db"],
                "db-stop": ["stop", "state-db"],
                "db-status": ["ps", "state-db"],
            }
            run(compose + arguments[options.command], env)
            return
        run(compose + ["up", "-d", "--wait", "--wait-timeout", "90", "state-db"], env)

    # Backend-only and local commands do not need Cloudflare API credentials.
    provider_commands = {"plan", "apply", "destroy", "console", "import", "refresh", "test"}
    if stack.name == "cloudflare" and options.command in provider_commands:
        entry = os.getenv("TERRAFORM_CLOUDFLARE_ENTRY", "workflow-engine/terraform-cloudflare")
        env["CLOUDFLARE_API_TOKEN"] = secrets.read(entry, "Password")
        env["TF_VAR_account_id"] = secrets.read(entry, "Account ID")
        env["TF_VAR_zone_id"] = secrets.read(entry, "Zone ID")
    run(["terraform", options.command, *options.args], env, cwd=stack)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"tf.py: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
