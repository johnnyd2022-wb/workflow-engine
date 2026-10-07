"""Platform admin operations: the one implementation behind the admin site and the admin CLI.

Each operation acts on an organisation named by the caller, so every one runs unscoped
(there is no tenant of its own to scope to) and names the organisation explicitly in its
queries. Each change is written to that organisation's audit log with who made it: an
admin's email from the site, or ``cli`` from the command line.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.db.models.audit_log import AuditLog
from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.db.models.organisation import Organisation, OrganisationStatus
from app.core.db.models.site import Site
from app.core.db.models.two_factor_backup_code import TwoFactorBackupCode
from app.core.db.models.user import User, UserRole
from app.core.db.models.user_identity import UserIdentity
from app.core.db.repositories.audit_repo import AuditRepository
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.trusted_device_repo import TrustedDeviceRepository
from app.core.db.repositories.user_repo import EmailConflictError, UserRepository
from app.core.security.auth_service import AuthService
from app.core.security.org_manager import OrgManager
from app.core.security.people import PeopleError, active_admins, issue_invite, validate_new_password
from app.core.security.tenant_scope import unscoped
from app.observability import get_logger

LOGGER = get_logger(__name__)

CLI_ACTOR = "cli"
PAGE_SIZE = 50
SIGN_IN_ACTIONS = ("login", "login_google")
# Features that are switched on per organisation (`feature_subscriptions`).
KNOWN_FEATURES = ("compliant",)


class AdminOperationError(ValueError):
    """The request cannot be carried out; the message is safe to show the admin."""


@dataclass(frozen=True)
class OrganisationSummary:
    id: UUID
    name: str
    status: OrganisationStatus
    created_at: datetime
    user_count: int


def _audit(org_id: UUID, action: str, entity: str, entity_id: UUID | None, actor: str, **details) -> None:
    """Record the change against the organisation. Never fails the operation it describes."""
    LOGGER.info("admin_operation", action=action, entity=entity, org_id=str(org_id), actor=actor)
    db = SessionLocal()
    try:
        with unscoped():
            AuditRepository(db).write_log(
                org_id=org_id,
                user_id=None,
                action=f"platform_admin.{action}",
                entity=entity,
                entity_id=entity_id,
                metadata={"platform_admin": actor, **details},
            )
    except Exception as exc:
        LOGGER.warning("admin_audit_write_failed", action=action, reason=type(exc).__name__)
        db.rollback()
    finally:
        db.close()


def parse_id(value, what: str = "ID") -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError):
        raise AdminOperationError(f"Invalid {what}: {value}") from None


def _clean_email(value) -> str:
    email = (value or "").strip().lower() if isinstance(value, str) else ""
    if len(email) > 255 or email.count("@") != 1 or not all(email.split("@")) or " " in email:
        raise AdminOperationError("Enter a valid email address.")
    return email


def _role(value) -> UserRole:
    if value in (UserRole.ADMIN, "admin"):
        return UserRole.ADMIN
    if value in (UserRole.MEMBER, "member"):
        return UserRole.MEMBER
    raise AdminOperationError("Role must be admin or member.")


def _check_password(password: str) -> None:
    try:
        validate_new_password(password)
    except PeopleError as exc:
        raise AdminOperationError(str(exc)) from None
    if len(password.encode("utf-8")) > 72:
        raise AdminOperationError("Password is too long.")


# ── Organisations ──────────────────────────────────────────────────────────────


def list_organisations(
    db: Session, *, search: str = "", status: OrganisationStatus | None = None, limit: int = PAGE_SIZE, offset: int = 0
) -> tuple[list[OrganisationSummary], int]:
    """One page of organisations, newest first, with how many matched in total."""
    with unscoped():
        query = db.query(Organisation)
        if search.strip():
            literal = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.filter(Organisation.name.ilike(f"%{literal}%", escape="\\"))
        if status is not None:
            query = query.filter(Organisation.status == status)
        total = query.count()
        orgs = query.order_by(Organisation.created_at.desc(), Organisation.id).limit(limit).offset(offset).all()
        counts = {}
        if orgs:
            counts = dict(
                db.query(User.org_id, func.count(User.id))
                .filter(User.org_id.in_([org.id for org in orgs]))
                .group_by(User.org_id)
                .all()
            )
    return [OrganisationSummary(o.id, o.name, o.status, o.created_at, counts.get(o.id, 0)) for o in orgs], total


def get_organisation(db: Session, org_id) -> Organisation:
    with unscoped():
        org = OrganisationRepository(db).get_org_by_id(parse_id(org_id, "organisation ID"))
    if org is None:
        raise AdminOperationError(f"Organisation not found: {org_id}")
    return org


def create_organisation(
    db: Session, *, name: str, admin_email: str, password: str | None = None, actor: str
) -> tuple[Organisation, User, str | None]:
    """Create an organisation and its first admin.

    With a password the admin can sign in straight away (the CLI's behaviour). Without one
    the admin is invited: the returned one-time token goes in a link they open to choose
    their own password, so no one else ever knows it.
    """
    name = (name or "").strip()
    if not name or len(name) > 255:
        raise AdminOperationError("Enter an organisation name of up to 255 characters.")
    email = _clean_email(admin_email)
    with unscoped():
        if password is not None:
            _check_password(password)
            try:
                org, user = OrgManager(db).create_org_with_admin_user(name, email, password)
            except ValueError as exc:
                raise AdminOperationError(str(exc)) from None
            token = None
        else:
            org_repo, user_repo = OrganisationRepository(db), UserRepository(db)
            if org_repo.get_org_by_name(name):
                raise AdminOperationError(f"Organisation with name '{name}' already exists")
            if user_repo.get_user_by_email(email):
                raise AdminOperationError(f"User with email '{email}' already exists")
            org = org_repo.create_org(name)
            user, token = _invite(db, org.id, email, UserRole.ADMIN)
    _audit(org.id, "create", "organisation", org.id, actor, name=org.name, admin_email=email, invited=bool(token))
    return org, user, token


def set_organisation_status(db: Session, org_id, status: OrganisationStatus, *, actor: str) -> Organisation:
    """Suspend an organisation (its people can no longer sign in) or make it active again."""
    org = get_organisation(db, org_id)
    if org.status == status:
        return org
    before = org.status
    with unscoped():
        org = OrganisationRepository(db).update_org(org.id, status=status)
    _audit(org.id, "set_status", "organisation", org.id, actor, before=before.value, after=status.value)
    return org


def rename_organisation(db: Session, org_id, name: str, *, actor: str) -> Organisation:
    org = get_organisation(db, org_id)
    name = (name or "").strip()
    if not name or len(name) > 255:
        raise AdminOperationError("Enter an organisation name of up to 255 characters.")
    if name == org.name:
        return org
    before = org.name
    with unscoped():
        repo = OrganisationRepository(db)
        if repo.get_org_by_name(name):
            raise AdminOperationError(f"Organisation with name '{name}' already exists")
        org = repo.update_org(org.id, name=name)
    _audit(org.id, "rename", "organisation", org.id, actor, before=before, after=name)
    return org


def organisation_overview(db: Session, org_id) -> dict:
    """What support needs to see about an organisation before asking the customer anything."""
    # Imported here: Sales is an optional area and its models are not loaded by every caller.
    from app.features.crm.models.xero_tenant import XeroTenant

    org = get_organisation(db, org_id)
    with unscoped():
        sites = db.query(func.count(Site.id)).filter(Site.org_id == org.id).scalar()
        xero = (
            db.query(XeroTenant)
            .filter(XeroTenant.org_id == org.id, XeroTenant.is_connected.is_(True))
            .order_by(XeroTenant.connected_at.desc())
            .first()
        )
        last_sign_ins = dict(
            db.query(AuditLog.user_id, func.max(AuditLog.timestamp))
            .filter(AuditLog.org_id == org.id, AuditLog.action.in_(SIGN_IN_ACTIONS))
            .group_by(AuditLog.user_id)
            .all()
        )
        google_linked = {
            user_id for (user_id,) in db.query(UserIdentity.user_id).filter(UserIdentity.org_id == org.id).all()
        }
    return {
        "go_live_date": org.go_live_date,
        "sites": sites,
        "multiple_sites": bool(org.multiple_sites_enabled),
        "contract_materials": bool(org.contract_materials_enabled),
        "xero_name": (xero.xero_tenant_name or "Connected") if xero else None,
        "xero_last_sync": xero.last_successful_sync_at if xero else None,
        "last_sign_ins": last_sign_ins,
        "last_sign_in": max(last_sign_ins.values(), default=None),
        "google_linked": google_linked,
    }


def list_audit(db: Session, org_id, *, limit: int = PAGE_SIZE, offset: int = 0) -> tuple[list[tuple], int]:
    """One page of an organisation's audit log, newest first: (entry, user email or None)."""
    org = get_organisation(db, org_id)
    with unscoped():
        total = db.query(func.count(AuditLog.id)).filter(AuditLog.org_id == org.id).scalar()
        rows = (
            db.query(AuditLog, User.email)
            .outerjoin(User, (User.id == AuditLog.user_id) & (User.org_id == AuditLog.org_id))
            .filter(AuditLog.org_id == org.id)
            .order_by(AuditLog.timestamp.desc(), AuditLog.id)
            .limit(limit)
            .offset(offset)
            .all()
        )
    return [(entry, email) for entry, email in rows], total


# ── Users ──────────────────────────────────────────────────────────────────────


def find_people(db: Session, search: str, *, limit: int = PAGE_SIZE) -> list[tuple[User, Organisation]]:
    """People in any organisation whose email contains ``search``. Support requests arrive
    as an email address, not an organisation."""
    search = (search or "").strip().lower()
    if len(search) < 3:
        return []
    literal = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with unscoped():
        rows = (
            db.query(User, Organisation)
            .join(Organisation, Organisation.id == User.org_id)
            .filter(User.email.ilike(f"%{literal}%", escape="\\"))
            .order_by(User.email)
            .limit(limit)
            .all()
        )
    return [(user, org) for user, org in rows]


def get_user(db: Session, org_id, user_id) -> User:
    org = get_organisation(db, org_id)
    with unscoped():
        return _user_in_org(db, org, user_id=user_id)


def list_users(db: Session, org_id, *, active_only: bool = False) -> list[User]:
    org = get_organisation(db, org_id)
    with unscoped():
        users = UserRepository(db).list_users_for_org(org.id, active_only=active_only)
    return sorted(users, key=lambda user: user.email)


def _invite(db: Session, org_id: UUID, email: str, role: UserRole) -> tuple[User, str]:
    """An inactive account with an unusable password and a one-time setup token."""
    try:
        user = UserRepository(db).create_user(
            org_id=org_id,
            email=email,
            password_hash=AuthService.hash_password(secrets.token_urlsafe(48)),
            role=role,
            is_active=False,
        )
    except EmailConflictError:
        raise AdminOperationError(f"User with email '{email}' already exists") from None
    token = issue_invite(user)
    db.commit()
    return user, token


def create_user(
    db: Session, org_id, *, email: str, role="member", password: str | None = None, actor: str
) -> tuple[User, str | None]:
    """Add a person to an organisation: active with a password, or invited without one."""
    org = get_organisation(db, org_id)
    email, user_role = _clean_email(email), _role(role)
    with unscoped():
        user_repo = UserRepository(db)
        if user_repo.get_user_by_email(email):
            raise AdminOperationError(f"User with email '{email}' already exists")
        if password is None:
            user, token = _invite(db, org.id, email, user_role)
        else:
            _check_password(password)
            token = None
            try:
                user = user_repo.create_user(
                    org_id=org.id,
                    email=email,
                    password_hash=AuthService.hash_password(password),
                    role=user_role,
                    is_active=True,
                )
            except EmailConflictError:
                raise AdminOperationError(f"User with email '{email}' already exists") from None
    _audit(org.id, "create", "user", user.id, actor, email=email, role=user_role.value, invited=bool(token))
    return user, token


def _user_in_org(db: Session, org: Organisation, *, user_id=None, email: str | None = None) -> User:
    repo = UserRepository(db)
    if user_id is not None:
        user = repo.get_user_by_id(parse_id(user_id, "user ID"), org_id=org.id)
    else:
        user = repo.get_user_by_email(email or "", org_id=org.id)
    if user is None:
        raise AdminOperationError(f"No user '{email or user_id}' in organisation {org.id}")
    return user


def reissue_invite(db: Session, org_id, user_id, *, actor: str) -> tuple[User, str]:
    """A fresh setup link for someone who has not accepted yet; the old link stops working."""
    org = get_organisation(db, org_id)
    with unscoped():
        user = _user_in_org(db, org, user_id=user_id)
        if user.is_active or not user.invite_token_hash:
            raise AdminOperationError(f"{user.email} has already set up their account.")
        token = issue_invite(user)
        db.commit()
    _audit(org.id, "reissue_invite", "user", user.id, actor, email=user.email)
    return user, token


def reset_password(
    db: Session, org_id, *, email: str | None = None, user_id=None, password: str | None = None, actor: str
) -> tuple[User, str]:
    """Set a new password and clear any lockout. Without ``password`` a random one is
    generated; either way it is returned so the caller can pass it on once."""
    org = get_organisation(db, org_id)
    if password is None:
        password = secrets.token_urlsafe(18)
    else:
        _check_password(password)
    with unscoped():
        repo = UserRepository(db)
        user = _user_in_org(db, org, user_id=user_id, email=email)
        user = repo.update_user(user.id, org_id=org.id, password_hash=AuthService.hash_password(password))
        repo.reset_failed_login_attempts(user.id)
        repo.unlock_account(user.id)
    _audit(org.id, "reset_password", "user", user.id, actor, email=user.email)
    return user, password


def unlock_user(db: Session, org_id, user_id, *, actor: str) -> User:
    """Clear a sign-in lockout without touching the password."""
    org = get_organisation(db, org_id)
    with unscoped():
        user = _user_in_org(db, org, user_id=user_id)
        UserRepository(db).unlock_account(user.id)
    _audit(org.id, "unlock", "user", user.id, actor, email=user.email)
    return user


def _keeps_an_admin(db: Session, org: Organisation, user: User) -> None:
    """Refuse a change that would leave the organisation with no one able to administer it."""
    admins = active_admins(UserRepository(db).list_users_for_org(org.id))
    if [admin.id for admin in admins] == [user.id]:
        raise AdminOperationError(f"{user.email} is the organisation's only admin. Make someone else an admin first.")


def set_user_role(db: Session, org_id, user_id, role, *, actor: str) -> User:
    org, new_role = get_organisation(db, org_id), _role(role)
    with unscoped():
        user = _user_in_org(db, org, user_id=user_id)
        if user.role == new_role:
            return user
        if user.role not in (UserRole.ADMIN, UserRole.MEMBER):
            raise AdminOperationError(f"{user.email} has the role {user.role.value}; change it in the app.")
        if new_role != UserRole.ADMIN:
            _keeps_an_admin(db, org, user)
        before = user.role
        user = UserRepository(db).update_user(user.id, org_id=org.id, role=new_role)
    _audit(org.id, "set_role", "user", user.id, actor, email=user.email, before=before.value, after=new_role.value)
    return user


def set_user_active(db: Session, org_id, user_id, active: bool, *, actor: str) -> User:
    """Deactivate someone (they can no longer sign in; nothing is deleted) or bring them back."""
    org = get_organisation(db, org_id)
    with unscoped():
        user = _user_in_org(db, org, user_id=user_id)
        if bool(user.is_active) == active:
            return user
        if active and user.invite_token_hash:
            raise AdminOperationError(f"{user.email} has not accepted their invite yet. Send them a new setup link.")
        if not active:
            _keeps_an_admin(db, org, user)
        user = UserRepository(db).update_user(user.id, org_id=org.id, is_active=active)
    _audit(org.id, "reactivate" if active else "deactivate", "user", user.id, actor, email=user.email)
    return user


def change_user_email(db: Session, org_id, user_id, email: str, *, actor: str) -> User:
    org, email = get_organisation(db, org_id), _clean_email(email)
    with unscoped():
        user = _user_in_org(db, org, user_id=user_id)
        before = user.email
        if email == before:
            return user
        try:
            user = UserRepository(db).update_user(user.id, org_id=org.id, email=email)
        except EmailConflictError:
            raise AdminOperationError(f"User with email '{email}' already exists") from None
    _audit(org.id, "change_email", "user", user.id, actor, before=before, after=email)
    return user


def reset_two_factor(db: Session, org_id, user_id, *, actor: str) -> User:
    """Switch 2FA off for someone who has lost their authenticator, with everything tied to
    that enrolment: backup codes and remembered devices. An admin is asked to enrol again
    the next time they sign in."""
    org = get_organisation(db, org_id)
    with unscoped():
        user = _user_in_org(db, org, user_id=user_id)
        if not user.two_factor_enabled and not user.totp_secret:
            raise AdminOperationError(f"{user.email} does not have 2FA switched on.")
        db.query(TwoFactorBackupCode).filter(
            TwoFactorBackupCode.org_id == org.id, TwoFactorBackupCode.user_id == user.id
        ).delete(synchronize_session=False)
        TrustedDeviceRepository(db).delete_user_devices(user.id)
        UserRepository(db).disable_two_factor(user.id)  # commits
    _audit(org.id, "reset_two_factor", "user", user.id, actor, email=user.email)
    return user


def is_locked(user: User) -> bool:
    return bool(user.account_locked_until and user.account_locked_until > datetime.now(UTC))


# ── Features ───────────────────────────────────────────────────────────────────


def _feature_key(value) -> str:
    key = (value or "").strip().lower() if isinstance(value, str) else ""
    if not key or len(key) > 80 or not key.replace("_", "").replace("-", "").isalnum():
        raise AdminOperationError("Enter a feature key (letters, digits, hyphens and underscores).")
    return key


def list_features(db: Session, org_id) -> list[FeatureSubscription]:
    org = get_organisation(db, org_id)
    with unscoped():
        return FeatureSubscriptionRepository(db).list_for_org(org.id)


def grant_feature(db: Session, org_id, feature: str, *, note: str | None = None, actor: str) -> FeatureSubscription:
    org, key = get_organisation(db, org_id), _feature_key(feature)
    with unscoped():
        row = FeatureSubscriptionRepository(db).grant(org.id, key, notes=note)
    _audit(org.id, "grant_feature", "feature_subscription", row.id, actor, feature=key)
    return row


def revoke_feature(db: Session, org_id, feature: str, *, actor: str) -> bool:
    """Returns False when the organisation never had the feature."""
    org, key = get_organisation(db, org_id), _feature_key(feature)
    with unscoped():
        changed = FeatureSubscriptionRepository(db).revoke(org.id, key)
    if changed:
        _audit(org.id, "revoke_feature", "feature_subscription", None, actor, feature=key)
    return changed


# ── System ─────────────────────────────────────────────────────────────────────


def system_status(db: Session) -> dict:
    """What the System page shows. A database that cannot be reached is reported, not raised."""
    try:
        with unscoped():
            return {
                "database": "reachable",
                "schema_version": db.execute(text("select version_num from alembic_version")).scalar(),
                "organisations": db.query(func.count(Organisation.id)).scalar(),
                "suspended": db.query(func.count(Organisation.id))
                .filter(Organisation.status == OrganisationStatus.SUSPENDED)
                .scalar(),
                "users": db.query(func.count(User.id)).scalar(),
            }
    except Exception as exc:
        db.rollback()
        LOGGER.warning("admin_system_status_failed", reason=type(exc).__name__)
        return {"database": "unreachable"}
