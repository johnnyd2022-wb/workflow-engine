"""A separate authentication realm; never resolve a staff User from portal credentials."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.backend.event_writer import EventWriter
from app.core.security.auth_service import AuthService
from app.core.security.tenant_scope import unscoped
from app.features.contract_manufacturing.models.orders import ContractCustomer
from app.features.contract_manufacturing.models.portal import PortalInvite, PortalPrincipal, PortalSession
from app.features.contract_manufacturing.services.orders import (
    ContractOrderService,
    OrderError,
    object_body,
    text_value,
)

SESSION_LIFETIME = timedelta(hours=12)
SESSION_IDLE = timedelta(minutes=30)
INVITE_LIFETIME = timedelta(hours=72)
_DUMMY_HASH = AuthService.hash_password(secrets.token_urlsafe(32))


def token_hash(value):
    if not isinstance(value, str) or not 32 <= len(value) <= 128:
        raise OrderError("Invalid or expired access", 401)
    return hashlib.sha256(value.encode()).hexdigest()


def email_value(value):
    value = text_value(value, "email", 255).lower()
    if value.count("@") != 1 or any(c.isspace() for c in value) or not all(value.split("@")):
        raise OrderError("A valid email is required")
    return value


def password_value(value):
    if not isinstance(value, str) or len(value) < 12 or len(value.encode()) > 72:
        raise OrderError("Use a password of at least 12 characters and at most 72 UTF-8 bytes")
    return value


def audit(db, org_id, kind, row):
    # No bearer secrets, passwords or email addresses in event payloads.
    EventWriter(db, org_id).emit(
        event_type=f"contract.portal_{kind}", entity_type="contract_portal", entity_id=row.id, payload={}
    )


def issue_invite(db, org_id, actor_id, customer_id, data):
    object_body(data, {"email"})
    customer = ContractOrderService(db, org_id).customer(customer_id)
    if not customer.is_active:
        raise OrderError("Customer is inactive", 409)
    email = email_value(data.get("email"))
    principal = db.query(PortalPrincipal).filter_by(org_id=org_id, customer_id=customer.id, email=email).first()
    if principal and principal.is_active:
        raise OrderError("This person already has portal access; revoke it before issuing a new invitation", 409)
    now = datetime.now(UTC)
    db.query(PortalInvite).filter_by(
        org_id=org_id, customer_id=customer.id, email=email, consumed_at=None, revoked_at=None
    ).update({"revoked_at": now}, synchronize_session=False)
    raw = secrets.token_urlsafe(32)
    invite = PortalInvite(
        org_id=org_id,
        customer_id=customer.id,
        email=email,
        token_hash=token_hash(raw),
        expires_at=now + INVITE_LIFETIME,
        created_by=actor_id,
    )
    db.add(invite)
    db.flush()
    audit(db, org_id, "invited", invite)
    return invite, raw


def new_session(db, principal):
    now = datetime.now(UTC)
    raw = secrets.token_urlsafe(32)
    row = PortalSession(
        org_id=principal.org_id,
        principal_id=principal.id,
        token_hash=token_hash(raw),
        expires_at=now + SESSION_LIFETIME,
        last_seen_at=now,
    )
    db.add(row)
    db.flush()
    return raw


def accept_invite(db, data):
    object_body(data, {"token", "password"})
    password = password_value(data.get("password"))
    now = datetime.now(UTC)
    with unscoped():
        invite = (
            db.query(PortalInvite)
            .filter(PortalInvite.token_hash == token_hash(data.get("token")))
            .with_for_update()
            .first()
        )
        if invite is None or invite.consumed_at or invite.revoked_at or invite.expires_at <= now:
            raise OrderError("Invitation is unavailable or has expired", 410)
        customer = (
            db.query(ContractCustomer).filter_by(org_id=invite.org_id, id=invite.customer_id, is_active=True).first()
        )
        if customer is None:
            raise OrderError("Invitation is unavailable or has expired", 410)
        principal = (
            db.query(PortalPrincipal)
            .filter_by(org_id=invite.org_id, customer_id=invite.customer_id, email=invite.email)
            .with_for_update()
            .first()
        )
        if principal is None:
            principal = PortalPrincipal(org_id=invite.org_id, customer_id=invite.customer_id, email=invite.email)
            db.add(principal)
        elif principal.is_active:
            raise OrderError("Invitation is unavailable or has expired", 410)
        principal.password_hash = AuthService.hash_password(password)
        principal.is_active = True
        principal.failed_attempts = 0
        principal.locked_until = None
        db.flush()
        db.query(PortalSession).filter_by(org_id=principal.org_id, principal_id=principal.id, revoked_at=None).update(
            {"revoked_at": now}, synchronize_session=False
        )
        invite.consumed_at = now
        audit(db, principal.org_id, "invite_accepted", invite)
        raw = new_session(db, principal)
        audit(db, principal.org_id, "signed_in", principal)
    return principal, raw


def authenticate(db, data):
    object_body(data, {"customer_id", "email", "password"})
    try:
        customer_id = UUID(str(data.get("customer_id")))
        email = email_value(data.get("email"))
    except (ValueError, OrderError):
        customer_id, email = None, ""
    password = data.get("password")
    if not isinstance(password, str) or len(password.encode()) > 72:
        password = "invalid"
    now = datetime.now(UTC)
    with unscoped():
        principal = (
            # Customer IDs are globally unique. The public login has no org before lookup.
            db.query(PortalPrincipal)
            .filter(PortalPrincipal.customer_id == customer_id, PortalPrincipal.email == email)
            .with_for_update()
            .first()
            if customer_id
            else None
        )
        valid_password = AuthService.verify_password(password, principal.password_hash if principal else _DUMMY_HASH)
        customer = (
            db.query(ContractCustomer)
            .filter_by(org_id=principal.org_id, id=principal.customer_id, is_active=True)
            .first()
            if principal
            else None
        )
        if (
            principal is None
            or not principal.is_active
            or customer is None
            or not valid_password
            or (principal.locked_until and principal.locked_until > now)
        ):
            if principal and principal.is_active:
                principal.failed_attempts += 1
                if principal.failed_attempts >= 5:
                    principal.locked_until = now + timedelta(minutes=10)
                # Preserve the account-level throttle even though the HTTP response fails.
                db.commit()
            raise OrderError("Unable to sign in with those details", 401)
        principal.failed_attempts = 0
        principal.locked_until = None
        raw = new_session(db, principal)
        audit(db, principal.org_id, "signed_in", principal)
    return principal, raw


def resolve_session(db, raw):
    now = datetime.now(UTC)
    with unscoped():
        # A random token hash is globally unique; the session supplies the org scope.
        row = (
            db.query(PortalSession)
            .filter(PortalSession.token_hash == token_hash(raw), PortalSession.revoked_at.is_(None))
            .with_for_update()
            .first()
        )
        if row is None or row.expires_at <= now or row.last_seen_at <= now - SESSION_IDLE:
            raise OrderError("Portal session has expired", 401)
        principal = db.query(PortalPrincipal).filter_by(org_id=row.org_id, id=row.principal_id, is_active=True).first()
        customer = (
            db.query(ContractCustomer).filter_by(org_id=row.org_id, id=principal.customer_id, is_active=True).first()
            if principal
            else None
        )
        if principal is None or customer is None:
            raise OrderError("Portal access is unavailable", 401)
        row.last_seen_at = now
        db.commit()
    return principal, customer, row


def revoke_access(db, org_id, customer_id, principal_id):
    ContractOrderService(db, org_id).customer(customer_id)
    row = (
        db.query(PortalPrincipal)
        .filter_by(org_id=org_id, customer_id=UUID(str(customer_id)), id=UUID(str(principal_id)))
        .with_for_update()
        .first()
    )
    if row is None:
        raise OrderError("Portal person not found", 404)
    row.is_active = False
    now = datetime.now(UTC)
    db.query(PortalSession).filter_by(org_id=org_id, principal_id=row.id, revoked_at=None).update(
        {"revoked_at": now}, synchronize_session=False
    )
    db.query(PortalInvite).filter_by(
        org_id=org_id, customer_id=row.customer_id, email=row.email, consumed_at=None, revoked_at=None
    ).update({"revoked_at": now}, synchronize_session=False)
    audit(db, org_id, "access_revoked", row)
    return row


def portal_people(db, org_id, customer_id):
    customer = ContractOrderService(db, org_id).customer(customer_id)
    people = (
        db.query(PortalPrincipal)
        .filter_by(org_id=org_id, customer_id=customer.id)
        .order_by(PortalPrincipal.email)
        .all()
    )
    invites = (
        db.query(PortalInvite)
        .filter_by(org_id=org_id, customer_id=customer.id, consumed_at=None, revoked_at=None)
        .filter(PortalInvite.expires_at > datetime.now(UTC))
        .all()
    )
    return {
        "people": [{"id": str(p.id), "email": p.email, "is_active": p.is_active} for p in people],
        "invitations": [{"id": str(i.id), "email": i.email, "expires_at": i.expires_at.isoformat()} for i in invites],
    }
