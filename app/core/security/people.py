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
    ROLE_DESCRIPTIONS,
    ROLE_LABELS,
    access_expired,
    permissions_for,
)

INVITE_VALID_FOR = timedelta(days=7)
AUDITOR_MAX_ACCESS = timedelta(days=90)
MIN_PASSWORD_LENGTH = 8
_NZ = ZoneInfo("Pacific/Auckland")


class PeopleError(ValueError):
    """A request that breaks one of the rules below; the message is safe to show."""


def role_options() -> list[dict]:
    return [
        {"value": role.value, "label": ROLE_LABELS[role], "description": ROLE_DESCRIPTIONS[role]} for role in UserRole
    ]


def parse_role(value) -> UserRole:
    try:
        return UserRole(str(value or "").strip().lower())
    except ValueError:
        raise PeopleError(f"Unknown role: {value!r}") from None


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
        "role": user.role.value,
        "role_label": ROLE_LABELS.get(user.role, user.role.value),
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
