"""The org switch, the role picker, and the Connected apps list (spec "MCP settings API")."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from app.core.db.models.user import UserRole
from app.core.security.access_policy import ROLE_LABELS
from app.core.utils.log_action import log_action
from app.features.mcp_oauth.repositories.grant_repo import GrantRepository
from app.features.mcp_oauth.repositories.settings_repo import SettingsRepository
from app.features.mcp_oauth.services import verified_clients
from app.observability import get_logger

logger = get_logger(__name__)

MAX_ROLE_KEYS = 200
_BUILTIN_KEYS = {f"builtin:{role.value}" for role in UserRole}
_CUSTOM_RE = re.compile(r"custom:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


class SettingsError(Exception):
    """A settings body that cannot be saved. The message is safe to show."""


SHARED_STORE_MESSAGE = (
    "Assistants can't be switched on yet: this Biz-E server is missing a security setting that limits "
    "how often an assistant can ask for data. Contact Biz-E support."
)


class SharedStoreRequiredError(SettingsError):
    """MCP cannot be switched on: more than one worker and no shared rate-limit store (design review
    S4), so every per-grant limit would be per worker. ``str()`` is for the organisation's admin;
    ``detail`` is for the operator (the CLI prints it, the log records it)."""

    def __init__(self, detail: str):
        super().__init__(SHARED_STORE_MESSAGE)
        self.detail = detail


def _require_shared_store() -> None:
    from app.api.ratelimit_store import shared_store_problem
    from app.utils.config_loader import config

    problem = shared_store_problem(config)
    if problem:
        logger.error("mcp.enable_refused_no_shared_store", detail=problem)
        raise SharedStoreRequiredError(problem)


def role_key_for(user) -> str:
    """The key an organisation ticks for this person: their custom role if they have one."""
    custom_id = getattr(user, "custom_role_id", None)
    if custom_id is not None:
        return f"custom:{custom_id}"
    return f"builtin:{user.role.value}"


def role_choices(db, org_id: UUID) -> list[dict]:
    roles = [
        {"key": f"builtin:{role.value}", "label": ROLE_LABELS.get(role, role.value), "custom": False}
        for role in UserRole
    ]
    roles += [
        {"key": f"custom:{r.id}", "label": r.name, "custom": True} for r in SettingsRepository(db).custom_roles(org_id)
    ]
    return roles


def get_settings(db, org_id: UUID) -> dict:
    repo = SettingsRepository(db)
    return {
        "enabled": repo.is_enabled(org_id),
        "allowed_roles": repo.allowed_role_keys(org_id),
        "roles": role_choices(db, org_id),
    }


def is_allowed_for(db, org_id: UUID, user) -> bool:
    """The org has assistants on and this person's role is ticked (checked on every request)."""
    repo = SettingsRepository(db)
    return repo.is_enabled(org_id) and repo.role_is_allowed(org_id, role_key_for(user))


def validate_role_keys(db, org_id: UUID, keys) -> list[str]:
    """The keys, deduplicated, if each is a built-in role or a custom role of *this* organisation."""
    if not isinstance(keys, list) or len(keys) > MAX_ROLE_KEYS:
        raise SettingsError("allowed_roles must be a list of role keys")
    repo = SettingsRepository(db)
    clean: list[str] = []
    for key in keys:
        if not isinstance(key, str):
            raise SettingsError("allowed_roles must be a list of role keys")
        if key in _BUILTIN_KEYS:
            pass
        else:
            match = _CUSTOM_RE.fullmatch(key)
            if match is None or not repo.custom_role_exists(org_id, UUID(match.group(1))):
                raise SettingsError("Choose a role belonging to this organisation")
        if key not in clean:
            clean.append(key)
    return clean


_REQUIRED_KEYS = {"enabled", "allowed_roles"}


def update_settings(db, org_id: UUID, user_id: UUID | None, body) -> dict:
    """Save the organisation switch and allowed roles."""
    usage = "Send {enabled: true|false, allowed_roles: [role keys]}"
    if not isinstance(body, dict) or set(body) != _REQUIRED_KEYS or not isinstance(body["enabled"], bool):
        raise SettingsError(usage)
    keys = validate_role_keys(db, org_id, body["allowed_roles"])
    if body["enabled"]:
        _require_shared_store()  # switching off is always allowed
    repo = SettingsRepository(db)
    repo.save(org_id, body["enabled"], keys, user_id, datetime.now(UTC))
    db.commit()
    log_action(
        "mcp_settings_updated",
        "mcp_settings",
        org_id,
        {"enabled": body["enabled"], "allowed_roles": keys},
        org_id,
        user_id,
    )
    logger.info("mcp.settings_updated", enabled=body["enabled"], roles=len(keys))
    return get_settings(db, org_id)


def prune_custom_role(db, org_id: UUID, role_id: UUID) -> None:
    """A deleted custom role can no longer be ticked. Call inside the transaction that deletes it."""
    SettingsRepository(db).prune_role(org_id, f"custom:{role_id}")


def _person(user) -> dict:
    name = " ".join(part for part in (user.first_name, user.last_name) if part) or None
    return {"id": str(user.id), "name": name, "email": user.email}


def list_grants(db, org_id: UUID, *, viewer_id: UUID, can_manage: bool) -> list[dict]:
    """Live grants: all of the org's with ``users.manage``, otherwise only the viewer's own."""
    rows = GrantRepository(db).list_live_grants(org_id, None if can_manage else viewer_id)
    return [
        {
            "id": str(grant.id),
            "client_name": client.client_name,
            # The code list decides, read here without writing (a GET never writes).
            "verified": verified_clients.is_verified(client),
            "user": _person(user),
            "scope": grant.scope,
            "created_at": grant.created_at.isoformat() if grant.created_at else None,
            "last_used_at": grant.last_used_at.isoformat() if grant.last_used_at else None,
        }
        for grant, client, user in rows
    ]


def revoke_grant(db, org_id: UUID, grant_id: UUID, actor, *, can_manage: bool) -> bool:
    """Revoke a grant the actor may revoke (their own, or any with ``users.manage``). False if none."""
    repo = GrantRepository(db)
    grant = repo.get_grant(org_id, grant_id)
    if grant is None or grant.revoked_at is not None or (grant.user_id != actor.id and not can_manage):
        return False
    revoke_and_audit(db, org_id, grant_id, "revoked_by_user", actor_id=actor.id)
    return True


def revoke_and_audit(db, org_id: UUID, grant_id: UUID, reason: str, *, actor_id: UUID | None) -> bool:
    repo = GrantRepository(db)
    grant = repo.get_grant(org_id, grant_id)
    owner_id = grant.user_id if grant is not None else None
    if not repo.revoke_grant(org_id, grant_id, reason, datetime.now(UTC)):
        return False
    db.commit()
    log_action(
        "mcp_grant_revoked", "oauth_grant", grant_id, {"reason": reason, "user_id": str(owner_id)}, org_id, actor_id
    )
    logger.info("mcp.grant_revoked", grant_id=str(grant_id), reason=reason)
    return True
