"""Local observability stack lifecycle commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from app.utils.config_loader import config as app_config

REPO_ROOT = Path(__file__).resolve().parents[2]
_STACK_SECRET_CONFIG_KEYS = {
    "POSTHOG_SECRET": "keepass_posthog_secret_entry",
    "ENCRYPTION_SALT_KEYS": "keepass_posthog_encryption_salt_keys_entry",
    "GRAFANA_ADMIN_PASSWORD": "keepass_grafana_admin_password_entry",
}
_STACK_SECRET_HEX_BYTES = {
    "POSTHOG_SECRET": 32,
    # PostHog requires each ENCRYPTION_SALT_KEYS value to be exactly 32 text
    # characters. Hex encoding 16 random bytes produces that length.
    "ENCRYPTION_SALT_KEYS": 16,
    "GRAFANA_ADMIN_PASSWORD": 32,
}


def _require_local_environment() -> None:
    if app_config.environment != "local":
        raise click.ClickException("Observability stack commands require ENVIRONMENT=local.")


def _observability_value(key: str, fallback: str = "") -> str:
    return app_config.get("observability", key, fallback).strip()


def _local_secrets_module() -> Any:
    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import local_secrets

    return local_secrets


def _read_keepass_password(entry_name: str) -> str:
    entry = _local_secrets_module().get_keepass_entry(entry_name=entry_name)
    value = str(entry.get("Password", "")).strip() if entry else ""
    return "" if value == "PROTECTED" else value


def _stack_environment() -> tuple[dict[str, str], list[str]]:
    _require_local_environment()
    environment = os.environ.copy()
    environment["GRAFANA_ADMIN_USER"] = _observability_value("grafana_admin_user", "admin")
    environment["POSTHOG_SITE_URL"] = _observability_value("posthog_site_url", "http://localhost:8000")
    missing: list[str] = []

    for environment_name, config_key in _STACK_SECRET_CONFIG_KEYS.items():
        entry_name = _observability_value(config_key)
        if not entry_name:
            missing.append(f"{config_key} (configure app/config/local.ini)")
            continue
        value = _read_keepass_password(entry_name)
        if value:
            environment[environment_name] = value
            if environment_name == "ENCRYPTION_SALT_KEYS" and len(value) != 32:
                missing.append(
                    f"{entry_name} must be exactly 32 characters; run "
                    "uv run workflow observability secrets --repair-posthog-salt"
                )
        else:
            missing.append(entry_name)
    return environment, missing


def _require_stack_environment() -> dict[str, str]:
    environment, missing = _stack_environment()
    if missing:
        raise click.ClickException(
            "Missing KeePassXC observability entries:\n" + "\n".join(f"- {item}" for item in missing)
        )
    return environment


def _compose_command() -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        "workflow-observability",
        "-f",
        str(REPO_ROOT / "docker-compose.observability-grafana.yml"),
        "-f",
        str(REPO_ROOT / "docker-compose.observability-posthog.yml"),
    ]


def _run_compose(args: list[str], environment: dict[str, str]) -> None:
    result = subprocess.run([*_compose_command(), *args], cwd=REPO_ROOT, env=environment, check=False)
    if result.returncode:
        raise click.ClickException(f"Docker Compose failed with exit code {result.returncode}.")


def _keepass_database_password() -> str:
    password = os.getenv("KEEPASS_PASSWORD")
    if password:
        return password
    return click.prompt("Enter KeePassXC database password", hide_input=True)


def _run_keepass(command: list[str], database_password: str, entry_password: str | None = None) -> bool:
    """Run a KeePassXC write command without exposing generated values in argv."""
    payload = f"{database_password}\n"
    if entry_password is not None:
        payload += f"{entry_password}\n"
    result = subprocess.run(command, input=payload, text=True, capture_output=True, check=False)
    return result.returncode == 0


def _rotate_stack_secrets() -> None:
    _require_local_environment()
    local_secrets = _local_secrets_module()
    database_path = os.getenv("KEEPASS_KDBX_PATH", local_secrets.DEFAULT_KDBX_PATH)
    database_password = _keepass_database_password()
    if not database_password:
        raise click.ClickException("No KeePassXC database password was provided.")

    os.environ["KEEPASS_PASSWORD"] = database_password
    for group_name in ("workflow-engine", "workflow-engine/observability"):
        _run_keepass(["keepassxc-cli", "mkdir", "-q", database_path, group_name], database_password)

    for environment_name, config_key in _STACK_SECRET_CONFIG_KEYS.items():
        entry_name = _observability_value(config_key)
        if not entry_name:
            raise click.ClickException(f"Missing {config_key} in app/config/local.ini.")

        generated = subprocess.run(
            ["openssl", "rand", "-hex", str(_STACK_SECRET_HEX_BYTES[environment_name])],
            capture_output=True,
            text=True,
            check=False,
        )
        secret_value = generated.stdout.strip()
        if generated.returncode or len(secret_value) != _STACK_SECRET_HEX_BYTES[environment_name] * 2:
            raise click.ClickException(f"OpenSSL could not generate a valid {environment_name} value.")

        if not _run_keepass(
            ["keepassxc-cli", "edit", "-q", "-p", database_path, entry_name], database_password, secret_value
        ) and not _run_keepass(
            ["keepassxc-cli", "add", "-q", "-p", database_path, entry_name], database_password, secret_value
        ):
            raise click.ClickException(f"Unable to create or update KeePassXC entry: {entry_name}")

    _require_stack_environment()
    click.echo("KeePassXC observability stack secrets were rotated and verified.")


def _repair_posthog_encryption_salt() -> None:
    """Replace an invalid local PostHog salt without touching data volumes."""
    _require_local_environment()
    entry_name = _observability_value("keepass_posthog_encryption_salt_keys_entry")
    if not entry_name:
        raise click.ClickException("Missing keepass_posthog_encryption_salt_keys_entry in app/config/local.ini.")

    current_value = _read_keepass_password(entry_name)
    if len(current_value) == 32:
        click.echo("PostHog encryption salt already has the required 32-character length.")
        return

    local_secrets = _local_secrets_module()
    database_path = os.getenv("KEEPASS_KDBX_PATH", local_secrets.DEFAULT_KDBX_PATH)
    database_password = _keepass_database_password()
    if not database_password:
        raise click.ClickException("No KeePassXC database password was provided.")

    generated = subprocess.run(["openssl", "rand", "-hex", "16"], capture_output=True, text=True, check=False)
    salt_value = generated.stdout.strip()
    if generated.returncode or len(salt_value) != 32:
        raise click.ClickException("OpenSSL could not generate a valid PostHog encryption salt.")

    if not _run_keepass(
        ["keepassxc-cli", "edit", "-q", "-p", database_path, entry_name], database_password, salt_value
    ):
        raise click.ClickException(f"Unable to update KeePassXC entry: {entry_name}")

    if len(_read_keepass_password(entry_name)) != 32:
        raise click.ClickException("KeePassXC PostHog encryption-salt verification failed.")
    click.echo("PostHog encryption salt was repaired and verified. No data volumes were changed.")


@click.group()
def observability() -> None:
    """Manage the complete local Grafana and PostHog observability stack."""


@observability.command("help")
def show_help() -> None:
    """Show local observability commands and browser URLs."""
    grafana_url = "http://localhost:3000"
    posthog_url = _observability_value("posthog_site_url", "http://localhost:8000")
    click.echo(
        """Local observability commands:

  uv run workflow observability secrets
      Verify the required KeePassXC entries without showing secret values.

  uv run workflow observability start | stop | status
      Start, stop, or inspect the complete Grafana + PostHog stack.

  uv run workflow observability logs -f alloy
      Follow a service's Docker Compose logs. Replace alloy with any service.

  uv run workflow observability config
      Validate the combined Docker Compose configuration.

  uv run workflow observability reset
      Recreate containers while preserving data volumes and existing secrets.

  uv run workflow observability reset --volumes
      Delete observability data volumes, then recreate containers.

  uv run workflow observability reset --volumes --rotate-secrets
      Delete data volumes and generate/store new PostHog and Grafana secrets in KeePassXC.
"""
    )
    click.echo("Open the local observability tools in a browser:")
    click.echo(f"  Grafana:   {grafana_url}  (username from local.ini; password from KeePassXC)")
    click.echo(f"  PostHog:   {posthog_url}")
    click.echo("  Alloy UI:  http://localhost:12345")
    click.echo("  Loki:      http://localhost:3100")
    click.echo("  Tempo:     http://localhost:3200")
    click.echo("  Mimir:     http://localhost:9009")
    click.echo("  Pyroscope: http://localhost:4040")


@observability.command()
@click.option(
    "--repair-posthog-salt",
    is_flag=True,
    help="Replace an invalid PostHog encryption salt; safe only before encrypted PostHog data exists.",
)
def secrets(repair_posthog_salt: bool) -> None:
    """Verify required local KeePassXC entries without showing their values."""
    if repair_posthog_salt:
        _repair_posthog_encryption_salt()
    _require_stack_environment()
    click.echo("KeePassXC observability stack entries are available.")


@observability.command()
def start() -> None:
    """Start the complete local observability stack."""
    environment = _require_stack_environment()
    _run_compose(["up", "-d", "--remove-orphans"], environment)
    _run_compose(["ps"], environment)


@observability.command()
def stop() -> None:
    """Stop stack containers while preserving all data volumes."""
    _run_compose(["stop"], _require_stack_environment())


@observability.command()
def status() -> None:
    """Show the current state of every observability stack container."""
    _run_compose(["ps"], _require_stack_environment())


@observability.command(context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def logs(args: tuple[str, ...]) -> None:
    """Pass arguments through to Docker Compose logs, e.g. logs -f alloy."""
    _run_compose(["logs", *args], _require_stack_environment())


@observability.command("config")
def validate_config() -> None:
    """Validate the combined Docker Compose configuration."""
    _run_compose(["config", "-q"], _require_stack_environment())
    click.echo("Combined observability Compose configuration is valid.")


@observability.command()
@click.option("--volumes", is_flag=True, help="Delete stack data volumes as part of the reset.")
@click.option("--rotate-secrets", is_flag=True, help="Generate replacement KeePassXC secrets (requires --volumes).")
def reset(volumes: bool, rotate_secrets: bool) -> None:
    """Recreate containers, preserving data by default."""
    if rotate_secrets and not volumes:
        raise click.UsageError(
            "--rotate-secrets requires --volumes because existing PostHog encrypted data would be unreadable."
        )
    if rotate_secrets:
        _rotate_stack_secrets()

    environment = _require_stack_environment()
    down_args = ["down", "--remove-orphans"]
    if volumes:
        click.echo("Resetting containers and deleting observability data volumes.")
        down_args.append("--volumes")
    else:
        click.echo("Resetting containers while preserving observability data volumes.")
    _run_compose(down_args, environment)
    _run_compose(["pull"], environment)
    _run_compose(["up", "-d", "--force-recreate", "--remove-orphans"], environment)
    _run_compose(["ps"], environment)
