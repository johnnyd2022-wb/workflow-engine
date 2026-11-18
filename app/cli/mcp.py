"""``workflow mcp ...``: turn AI assistant access on or off for an organisation (public MCP 8.2b).

Until the Settings page (8.2e) exists this is how an organisation gets the feature:
``uv run workflow mcp enable --org-id <uuid> --roles admin,member``.
"""

from uuid import UUID

import click

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.security.tenant_scope import tenant_scope, unscoped
from app.features.mcp_oauth.services import settings_service
from app.features.mcp_oauth.services.settings_service import SettingsError


@click.group(name="mcp")
def mcp():
    """AI assistant (MCP) access per organisation."""


def _org_id(value: str) -> UUID:
    try:
        org_id = UUID(value)
    except ValueError:
        raise click.UsageError("--org-id must be a UUID") from None
    with unscoped():  # the admin CLI is the one place that names an organisation from outside
        if db_session().query(Organisation.id).filter(Organisation.id == org_id).first() is None:
            raise click.UsageError(f"No organisation {org_id}")
    return org_id


def _role_keys(roles: str) -> list[str]:
    """``admin,member`` -> ``builtin:admin,builtin:member``; a ``custom:<uuid>`` key is kept as given."""
    keys = []
    for item in (part.strip() for part in roles.split(",")):
        if not item:
            continue
        keys.append(item if item.startswith(("builtin:", "custom:")) else f"builtin:{item}")
    return keys


@mcp.command(name="enable")
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--roles", required=True, help="Comma-separated roles that may connect, e.g. admin,member")
def enable(org_id, roles):
    """Switch assistants on for an organisation and choose which roles may connect."""
    org = _org_id(org_id)
    db = db_session()
    try:
        with tenant_scope(org):
            result = settings_service.update_settings(
                db, org, None, {"enabled": True, "allowed_roles": _role_keys(roles)}
            )
    except SettingsError as err:
        db.rollback()
        raise click.UsageError(str(err)) from None
    finally:
        db.close()
    click.echo(f"Assistants are on for {org}. Roles: {', '.join(result['allowed_roles']) or 'none'}")


@mcp.command(name="disable")
@click.option("--org-id", required=True, help="Organisation ID")
def disable(org_id):
    """Switch assistants off for an organisation. The role list is kept."""
    org = _org_id(org_id)
    db = db_session()
    try:
        with tenant_scope(org):
            current = settings_service.get_settings(db, org)
            settings_service.update_settings(
                db, org, None, {"enabled": False, "allowed_roles": current["allowed_roles"]}
            )
    finally:
        db.close()
    click.echo(f"Assistants are off for {org}.")
