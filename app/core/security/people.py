"""Managing the people in an organisation: roles, invites, time-limited access (plan 0.4).

Kept apart from the routes so the rules (last admin, auditor expiry, invite tokens) are
plain functions with their own tests.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.db.models.user import User, UserRole
from app.core.security.access_policy import (
    CUSTOM_ROLE_BASES,
    GRANTABLE,
    PERMISSIONS,
    ROLE_DESCRIPTIONS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    access_expired,
    permissions_for,
    role_label_for,
)

INVITE_VALID_FOR = timedelta(days=7)
AUDITOR_MAX_ACCESS = timedelta(days=90)
MIN_PASSWORD_LENGTH = 8
_NZ = ZoneInfo("Pacific/Auckland")


class PeopleError(ValueError):
    """A request that breaks one of the rules below; the message is safe to show."""


CUSTOM_PREFIX = "custom:"


def role_options(custom_roles: list | None = None) -> list[dict]:
    """Built-in roles, then the organisation's custom roles (plan 0.4c)."""
    options = [
        {
            "value": role.value,
            "label": ROLE_LABELS[role],
            "description": ROLE_DESCRIPTIONS[role],
            "needs_expiry": role == UserRole.AUDITOR,
            "custom": False,
        }
        for role in UserRole
    ]
    for custom in custom_roles or []:
        base = UserRole(custom.base_role)
        options.append(
            {
                "value": f"{CUSTOM_PREFIX}{custom.id}",
                "label": custom.name,
                "description": custom.description or f"Custom role based on {ROLE_LABELS[base]}.",
                "needs_expiry": base == UserRole.AUDITOR,
                "custom": True,
            }
        )
    return options


def parse_role(value) -> UserRole:
    try:
        return UserRole(str(value or "").strip().lower())
    except ValueError:
        raise PeopleError(f"Unknown role: {value!r}") from None


def parse_role_choice(value, custom_roles: list) -> tuple[UserRole, object | None]:
    """A built-in role value, or ``custom:<id>`` for one of this organisation's roles."""
    text = str(value or "").strip()
    if text.startswith(CUSTOM_PREFIX):
        wanted = text[len(CUSTOM_PREFIX) :]
        custom = next((r for r in custom_roles if str(r.id) == wanted), None)
        if custom is None:
            raise PeopleError("Unknown role")
        return UserRole(custom.base_role), custom
    return parse_role(text), None


def role_value(user: User) -> str:
    custom_id = getattr(user, "custom_role_id", None)
    return f"{CUSTOM_PREFIX}{custom_id}" if custom_id else user.role.value


def validate_custom_role(data: dict, existing_names: set[str]) -> dict:
    """Name, base role (any built-in but Admin) and the permissions ticked for it."""
    name = " ".join(str(data.get("name") or "").split())[:100]
    if not name:
        raise PeopleError("Give the role a name.")
    if name.casefold() in existing_names or name.casefold() in {label.casefold() for label in ROLE_LABELS.values()}:
        raise PeopleError(f"There's already a role called {name}.")
    try:
        base = UserRole(str(data.get("base_role") or ""))
    except ValueError:
        raise PeopleError("Pick the built-in role to start from.") from None
    if base not in CUSTOM_ROLE_BASES:
        raise PeopleError("Admin can't be customised. Start from another role.")
    permissions = data.get("permissions")
    if permissions is None:
        permissions = sorted(ROLE_PERMISSIONS[base] & GRANTABLE)
    if not isinstance(permissions, list) or any(p not in PERMISSIONS for p in permissions):
        raise PeopleError("Unknown permission")
    refused = sorted(set(permissions) - GRANTABLE)
    if refused:
        raise PeopleError(f"Only admins can have {', '.join(refused)}.")
    if not permissions:
        raise PeopleError("Tick at least one permission.")
    description = " ".join(str(data.get("description") or "").split())[:500] or None
    return {"name": name, "base_role": base.value, "permissions": sorted(set(permissions)), "description": description}


def permission_catalogue() -> list[dict]:
    return [{"key": key, "description": text, "grantable": key in GRANTABLE} for key, text in PERMISSIONS.items()]


def parse_access_expiry(value, role: UserRole, now: datetime | None = None) -> datetime | None:
    """Auditors need an end date within 90 days; other roles may have one, optionally."""
    now = now or datetime.now(UTC)
    if value in (None, ""):
        if role == UserRole.AUDITOR:
            raise PeopleError("Auditor access needs an end date.")
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            # A bare date means "until the end of that day" in New Zealand, so an auditor
            # keeps access for the whole visit.
            parsed = datetime.combine(date.fromisoformat(text), time(23, 59, 59), tzinfo=_NZ)
        else:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_NZ)
    except ValueError:
        raise PeopleError("Access end date must be a date, e.g. 2026-10-31.") from None
    if parsed <= now:
        raise PeopleError("Access end date must be in the future.")
    if role == UserRole.AUDITOR and parsed - now > AUDITOR_MAX_ACCESS:
        raise PeopleError("Auditor access can last at most 90 days.")
    return parsed


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_invite(user: User, now: datetime | None = None) -> str:
    """Give ``user`` a fresh one-time setup token; returns the raw token (shown once)."""
    token = secrets.token_urlsafe(32)
    user.invite_token_hash = hash_invite_token(token)
    user.invite_expires_at = (now or datetime.now(UTC)) + INVITE_VALID_FOR
    return token


def invite_is_pending(user: User) -> bool:
    return bool(getattr(user, "invite_token_hash", None)) and not user.is_active


def active_admins(users: list[User]) -> list[User]:
    return [u for u in users if u.role == UserRole.ADMIN and u.is_active and not access_expired(u)]


def check_change(
    actor: User, target: User, org_users: list[User], *, role: UserRole | None, is_active: bool | None
) -> None:
    """Refuse changes that would lock the organisation out or let people edit themselves."""
    if target.id == actor.id:
        if role is not None and role != target.role:
            raise PeopleError("You can't change your own role. Ask another admin.")
        if is_active is False:
            raise PeopleError("You can't deactivate your own account.")
    loses_admin = target.role == UserRole.ADMIN and (
        (role is not None and role != UserRole.ADMIN) or is_active is False
    )
    if loses_admin and [u.id for u in active_admins(org_users)] == [target.id]:
        raise PeopleError("This is the organisation's only admin. Make someone else an admin first.")


def validate_new_password(password: str, confirm: str | None = None) -> None:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise PeopleError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if confirm is not None and password != confirm:
        raise PeopleError("Passwords don't match.")


def serialize_person(user: User) -> dict:
    first = getattr(user, "first_name", None)
    last = getattr(user, "last_name", None)
    display = " ".join(x for x in (first, last) if x).strip() or user.email
    if invite_is_pending(user):
        status = "invited"
    elif not user.is_active:
        status = "deactivated"
    elif access_expired(user):
        status = "expired"
    else:
        status = "active"
    return {
        "id": str(user.id),
        "email": user.email,
        "first_name": first,
        "last_name": last,
        "display_name": display,
        "role": role_value(user),
        "role_label": role_label_for(user),
        "is_active": user.is_active,
        "status": status,
        "two_factor_enabled": bool(user.two_factor_enabled),
        "access_expires_at": user.access_expires_at.isoformat() if user.access_expires_at else None,
        "invite_expires_at": user.invite_expires_at.isoformat()
        if invite_is_pending(user) and user.invite_expires_at
        else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def permission_list(user: User) -> list[str]:
    return sorted(permissions_for(user))
