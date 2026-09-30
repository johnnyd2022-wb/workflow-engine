"""Resolve verified Google claims without creating or changing account ownership."""

import time
from datetime import UTC, datetime

from sqlalchemy import func

from app.core.db.models.organisation import Organisation, OrganisationStatus
from app.core.db.models.user import User
from app.core.db.models.user_identity import UserIdentity
from app.core.security.access_policy import access_expired
from app.core.security.people import hash_invite_token
from app.core.security.tenant_scope import unscoped

PROVIDER = "google"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleSignInError(ValueError):
    """A verified identity still cannot use this local account."""


def validate_verified_claims(claims, client_id, nonce):
    """Extra fail-closed checks after Authlib verifies the signature and OIDC claims.

    In particular never honor a provider's nonce_supported=false shortcut. Only the
    verified ID token is used, not a separate userinfo response or client email.
    """
    audience = claims.get("aud")
    audience = audience if isinstance(audience, list) else [audience]
    if (
        claims.get("iss") not in ISSUERS
        or client_id not in audience
        or (len(audience) > 1 and claims.get("azp") != client_id)
        or (claims.get("azp") is not None and claims["azp"] != client_id)
        or not isinstance(claims.get("exp"), (int, float))
        or claims["exp"] <= time.time()
        or claims.get("nonce") != nonce
        or not nonce
        or claims.get("email_verified") is not True
    ):
        raise GoogleSignInError("Invalid Google identity")
    email = claims.get("email")
    subject = claims.get("sub")
    if (
        not isinstance(email, str)
        or len(email) > 255
        or email.count("@") != 1
        or email != email.strip()
        or not all(email.split("@"))
        or not isinstance(subject, str)
        or not subject
        or len(subject) > 255
    ):
        raise GoogleSignInError("Invalid Google identity")
    return claims


def authoritative_email(claims):
    domain = claims["email"].lower().rsplit("@", 1)[1]
    hd = claims.get("hd")
    return domain == "gmail.com" or (isinstance(hd, str) and hd.lower() == domain)


def assert_account_available(db, user, *, invited=False):
    if user is None or (not invited and not user.is_active) or access_expired(user):
        raise GoogleSignInError("Account unavailable")
    locked = user.account_locked_until
    if locked and locked > datetime.now(UTC):
        raise GoogleSignInError("Account unavailable")
    org = db.query(Organisation).filter(Organisation.id == user.org_id).one_or_none()
    if org is None or org.status != OrganisationStatus.ACTIVE:
        raise GoogleSignInError("Account unavailable")


def _bind(db, user, claims):
    existing = db.query(UserIdentity).filter_by(org_id=user.org_id, user_id=user.id, provider=PROVIDER).one_or_none()
    if existing:
        if existing.subject != claims["sub"]:
            raise GoogleSignInError("Another Google account is already linked")
        return existing
    identity = UserIdentity(
        org_id=user.org_id,
        user_id=user.id,
        provider=PROVIDER,
        subject=claims["sub"],
        email_at_link=claims["email"].lower(),
    )
    db.add(identity)
    db.flush()  # Unique constraints also refuse racing links across users/tenants.
    return identity


def resolve_identity(db, claims, *, linking_user=None, invite_token=None, current_user_id=None):
    """Global subject lookup is needed before a tenant is known; every returned account
    is tied to the identity's composite org/user key. No tenant hint comes from a client.
    """
    with unscoped():
        # Authentication bootstrap: a verified globally unique subject determines the tenant.
        # nosemgrep: filter-by-missing-org-id
        identity = db.query(UserIdentity).filter_by(provider=PROVIDER, subject=claims["sub"]).one_or_none()
        user = None
        if identity:
            user = db.query(User).filter_by(id=identity.user_id, org_id=identity.org_id).with_for_update().one_or_none()
        if linking_user is not None:
            if identity and (user is None or user.id != linking_user.id or user.org_id != linking_user.org_id):
                raise GoogleSignInError("Google account already belongs to another account")
            user = db.query(User).filter_by(id=linking_user.id, org_id=linking_user.org_id).with_for_update().one()
            assert_account_available(db, user)
        elif invite_token:
            # A globally unique one-time invite hash determines the tenant before login.
            invited = (
                db.query(User)  # nosemgrep: filter-by-missing-org-id
                .filter_by(invite_token_hash=hash_invite_token(invite_token))
                .with_for_update()
                .one_or_none()
            )
            if (
                invited is None
                or invited.is_active
                or not invited.invite_expires_at
                or invited.invite_expires_at <= datetime.now(UTC)
                or invited.email.lower() != claims["email"].lower()
                or not authoritative_email(claims)
                or (identity and (user is None or user.id != invited.id or user.org_id != invited.org_id))
            ):
                raise GoogleSignInError("Invite cannot be accepted by this Google account")
            user = invited
            assert_account_available(db, user, invited=True)
        elif user is None:
            if not authoritative_email(claims):
                raise GoogleSignInError("Sign in with your password and link Google in Settings")
            user = (
                db.query(User).filter(func.lower(User.email) == claims["email"].lower()).with_for_update().one_or_none()
            )
            assert_account_available(db, user)
        else:
            assert_account_available(db, user)
        if current_user_id and str(user.id) != str(current_user_id):
            raise GoogleSignInError("Sign out before choosing another account")
        _bind(db, user, claims)
        if invite_token:
            user.is_active = True
            user.invite_token_hash = None
            user.invite_expires_at = None
            # Invite accounts have no known password yet; require Google reauthentication
            # to set one before allowing unlink. An empty hash cannot authenticate.
            user.password_hash = ""
        return user
