"""Production secrets in KeePassXC: create what can be generated, and report what is missing.

Until production moves to a managed secret store, its secrets live beside the local and
test ones in the KeePassXC database (`scripts/local_secrets.py`). `scripts/run_prod.sh`
reads them on the host and hands them to the container as environment variables.

    python3 scripts/prod_secrets.py check   # which entries exist (never prints a value)
    python3 scripts/prod_secrets.py init    # generate the ones that can be generated
    eval "$(python3 scripts/prod_secrets.py export)"   # load them into a script's environment
    eval "$(python3 scripts/prod_secrets.py export --scope admin)"   # the admin site's instead

`init` never overwrites an entry. Rotating one is deliberate: delete it in KeePassXC, then
run `init` again -- and read the note against that secret first, because some cannot be
rotated without consequences.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import local_secrets  # noqa: E402

GROUP = "workflow-engine"


def _random_token() -> str:
    return secrets.token_urlsafe(48)


def _fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@dataclass(frozen=True)
class Secret:
    entry: str  # KeePassXC entry path
    env: str  # environment variable the app reads
    generate: object | None  # callable producing a value, or None when a person must supply it
    note: str
    username: str = ""
    scopes: tuple[str, ...] = ("app",)  # which container needs it: the customer app, the admin site


SECRETS = (
    Secret(
        f"{GROUP}/workflow-engine-prod-db",
        "POSTGRES_PASSWORD",
        _random_token,
        "Database password. Set when the database container is first created; changing it "
        "later needs ALTER ROLE in the database as well.",
        username="workflow_rw",
        scopes=("app", "admin"),
    ),
    Secret(
        f"{GROUP}/FLASK_SECRET_KEY_PROD",
        "FLASK_SECRET_KEY",
        _random_token,
        "Signs sessions. Rotating it signs everyone out.",
    ),
    Secret(
        f"{GROUP}/BACKUP_CODE_ENCRYPTION_KEY_PROD",
        "BACKUP_CODE_ENCRYPTION_KEY",
        _fernet_key,
        "Encrypts 2FA backup codes. Rotating it invalidates every stored backup code. The admin site has "
        "it too, so staff can read a locked-out person their codes.",
        scopes=("app", "admin"),
    ),
    Secret(
        f"{GROUP}/XERO_TOKEN_ENCRYPTION_KEY_PROD",
        "XERO_TOKEN_ENCRYPTION_KEY",
        _fernet_key,
        "Encrypts stored Xero tokens. Rotating it means reconnecting Xero.",
    ),
    Secret(f"{GROUP}/xero_client_id", "XERO_CLIENT_ID", None, "Client id of the PRODUCTION Xero app."),
    Secret(f"{GROUP}/xero_client_secret", "XERO_CLIENT_SECRET", None, "Client secret of the PRODUCTION Xero app."),
    Secret(
        f"{GROUP}/ADMIN_FLASK_SECRET_KEY_PROD",
        "ADMIN_FLASK_SECRET_KEY",
        _random_token,
        "Signs admin-site sessions. Never the same as FLASK_SECRET_KEY. Rotating it signs the admins out.",
        scopes=("admin",),
    ),
    Secret(
        f"{GROUP}/ADMIN_GOOGLE_CLIENT_ID",
        "ADMIN_GOOGLE_CLIENT_ID",
        None,
        "Google OAuth client for admin.biz-e.app (redirect URI https://admin.biz-e.app/auth/google/callback).",
        scopes=("admin",),
    ),
    Secret(
        f"{GROUP}/ADMIN_GOOGLE_CLIENT_SECRET",
        "ADMIN_GOOGLE_CLIENT_SECRET",
        None,
        "Client secret of the admin-site Google OAuth client.",
        scopes=("admin",),
    ),
)


def _database_path() -> str:
    return os.getenv("KEEPASS_KDBX_PATH", local_secrets.DEFAULT_KDBX_PATH)


def _database_password() -> str:
    return os.getenv("KEEPASS_PASSWORD") or getpass.getpass("KeePassXC database password: ")


def exists(entry: str, database_password: str) -> bool:
    result = subprocess.run(
        ["keepassxc-cli", "show", "-q", "-a", "Title", _database_path(), entry],
        input=f"{database_password}\n",
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def create(secret: Secret, value: str, database_password: str) -> bool:
    """Add the entry. The value travels on stdin, never in argv or the environment."""
    command = ["keepassxc-cli", "add", "-q", "-p"]
    if secret.username:
        command += ["-u", secret.username]
    command += [_database_path(), secret.entry]
    result = subprocess.run(
        command, input=f"{database_password}\n{value}\n", text=True, capture_output=True, check=False
    )
    return result.returncode == 0


def _export(database_password: str, scope: str = "app") -> int:
    """Print `export NAME='value'` lines for `eval` in scripts/run_prod.sh. Never run this bare
    in a terminal: its whole output is secret."""
    os.environ["KEEPASS_PASSWORD"] = database_password
    missing = []
    for secret in SECRETS:
        if scope not in secret.scopes:
            continue
        value = local_secrets.get_keepass_entry(entry_name=secret.entry).get("Password", "")
        if not value or value == "PROTECTED":
            missing.append(secret.entry)
            continue
        print(f"export {secret.env}={shlex.quote(value)}")
    if missing:
        print(f"echo 'Missing production secrets in KeePassXC: {' '.join(missing)}' >&2; false")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "init", "export"))
    parser.add_argument("--scope", choices=("app", "admin"), default="app", help="which container to export for")
    args = parser.parse_args(argv)
    database_password = _database_password()
    if args.command == "export":
        return _export(database_password, args.scope)
    missing_manual = 0
    for secret in SECRETS:
        present = exists(secret.entry, database_password)
        if present:
            status = "present"
        elif secret.generate is None:
            status = "MISSING - add it in KeePassXC yourself"
            missing_manual += 1
        elif args.command == "init":
            status = "created" if create(secret, secret.generate(), database_password) else "FAILED to create"
        else:
            status = "missing - `init` will generate it"
        print(f"{secret.env:<28} {secret.entry:<48} {status}")
    return 1 if missing_manual and args.command == "check" else 0


if __name__ == "__main__":
    raise SystemExit(main())
