"""The authorization endpoint's rules: validate a request, decide whether consent may be shown, and
turn an approval into a one-time code (spec "OAuth", ``GET /oauth/authorize`` and the consent page).

Two kinds of failure, kept apart on purpose (RFC 6749 §4.1.2.1):

* ``PageError``: the client or the redirect URI is not trustworthy, so the browser must *not* be
  sent anywhere; the app shows an error page.
* ``RedirectError``: the client and redirect URI are known good, so the error goes back to the
  client in the redirect, with the same ``state``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.exc import IntegrityError

from app.core.security.access_policy import PERMISSIONS, READ_PERMISSIONS, permissions_for
from app.core.security.auth_service import auth_stamp
from app.core.utils.log_action import log_action
from app.features.mcp_oauth import SCOPE_READ, SUPPORTED_SCOPES
from app.features.mcp_oauth.models import OAuthClient, OAuthGrant
from app.features.mcp_oauth.repositories.grant_repo import GrantRepository
from app.features.mcp_oauth.repositories.settings_repo import SettingsRepository
from app.features.mcp_oauth.services import client_registry
from app.features.mcp_oauth.services.client_registry import ClientError
from app.features.mcp_oauth.services.settings_service import is_allowed_for
from app.features.mcp_oauth.services.tokens import CODE_PREFIX, CODE_TTL, hash_token, is_valid_challenge, new_token
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

MAX_STATE_LENGTH = 1024

MESSAGE_ORG_OFF = "Your organisation hasn't turned on AI assistant access. An admin can turn it on in Settings."
MESSAGE_ROLE = "Your role can't use AI assistant access. Ask an admin."
MESSAGE_CLIENT_DISABLED = "This app has been switched off by Biz-E and can't connect."


class PageError(Exception):
    """Show an error page; never redirect."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class RedirectError(Exception):
    """Redirect to the client's redirect URI with ``error=`` and the request's ``state``."""

    def __init__(self, error: str, description: str, redirect_uri: str, state: str | None):
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
        self.redirect_uri = redirect_uri
        self.state = state

    def location(self) -> str:
        # RFC 9207: say which server answered, on errors as well as success (mix-up defence).
        params = {"error": self.error, "error_description": self.description, "iss": config.mcp_issuer}
        if self.state is not None:
            params["state"] = self.state
        return append_query(self.redirect_uri, params)


@dataclass(frozen=True)
class AuthorizeRequest:
    client: OAuthClient
    redirect_uri: str
    state: str | None
    code_challenge: str
    scope: str
    resource: str

    def form_fields(self) -> dict[str, str]:
        """The parameters to carry through the consent form, so the POST can validate them afresh."""
        fields = {
            "response_type": "code",
            "client_id": self.client.client_id,
            "redirect_uri": self.redirect_uri,
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "scope": self.scope,
            "resource": self.resource,
        }
        if self.state is not None:
            fields["state"] = self.state
        return fields


def append_query(uri: str, params: dict[str, str]) -> str:
    """``uri`` with ``params`` added to its query (an existing query is kept)."""
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + list(params.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def needs_metadata_fetch(db, client_id) -> bool:
    """True for an https client_id we would have to fetch (no usable cached row yet)."""
    if not isinstance(client_id, str) or not client_id.startswith("https://") or len(client_id) > 2000:
        return False
    row = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).one_or_none()
    return row is None or (row.registration == "metadata_url" and not client_registry._fresh(row, datetime.now(UTC)))


def parse_authorize(db, args) -> AuthorizeRequest:
    """Validate an authorization request (query string or consent form). Raises the two errors above."""
    resource_expected = config.mcp_resource
    if not resource_expected or not config.mcp_issuer:
        logger.error("mcp.not_configured")
        raise PageError("AI assistant access isn't configured on this server.", 503)

    client_id = args.get("client_id")
    try:
        client = client_registry.lookup_client(db, client_id)
    except ClientError:
        raise PageError("We couldn't identify the app that sent you here, so we haven't sent you back to it.") from None

    redirect_uri = args.get("redirect_uri")
    if not client_registry.redirect_uri_matches(redirect_uri, client.redirect_uris):
        raise PageError("This app asked to return you to an address it hasn't registered, so we stopped.")

    state = args.get("state")
    if state is not None and (not isinstance(state, str) or len(state) > MAX_STATE_LENGTH):
        raise RedirectError("invalid_request", "state is too long", redirect_uri, None)

    def fail(error: str, description: str) -> RedirectError:
        return RedirectError(error, description, redirect_uri, state)

    if args.get("response_type") != "code":
        raise fail("unsupported_response_type", "Only response_type=code is supported")
    method = args.get("code_challenge_method")
    challenge = args.get("code_challenge")
    if method != "S256":
        raise fail("invalid_request", "PKCE with code_challenge_method=S256 is required")
    if not is_valid_challenge(challenge):
        raise fail("invalid_request", "code_challenge must be a base64url SHA-256 digest")
    scope = args.get("scope") or SCOPE_READ
    if not isinstance(scope, str) or not scope.split() or any(s not in SUPPORTED_SCOPES for s in scope.split()):
        raise fail("invalid_scope", f"Supported scope: {SCOPE_READ}")
    resources = args.getlist("resource") if hasattr(args, "getlist") else [args.get("resource")]
    if resources != [resource_expected]:
        raise fail("invalid_target", "resource must be this server's MCP URL")
    return AuthorizeRequest(
        client=client,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
        scope=" ".join(dict.fromkeys(scope.split())),
        resource=resource_expected,
    )


def connect_block_reason(db, user) -> str | None:
    """Why this person cannot connect any assistant right now (the org's switch, their role), else ``None``.

    The consent page and the Settings page say the same thing, so they share this.
    """
    org_id = user.org_id
    if not SettingsRepository(db).is_enabled(org_id):
        return MESSAGE_ORG_OFF
    if not is_allowed_for(db, org_id, user):
        return MESSAGE_ROLE
    return None


def consent_block_reason(db, user, client: OAuthClient) -> str | None:
    """Why this person may not approve an assistant right now, or ``None`` when they may."""
    if client.disabled_at is not None:
        return MESSAGE_CLIENT_DISABLED
    return connect_block_reason(db, user)


def readable_summary(user) -> list[str]:
    """Plain-English list of what read access covers: the person's own view permissions only."""
    held = permissions_for(user) & READ_PERMISSIONS
    order = ("production.view", "inventory.view", "sales.view", "compliance.view", "costs.view")
    return [PERMISSIONS[p] for p in order if p in held]


def approve(db, user, req: AuthorizeRequest) -> str:
    """Record the approval and return the redirect URL carrying a one-time code and the state."""
    now = datetime.now(UTC)
    repo = GrantRepository(db)
    org_id = user.org_id
    grant = repo.get_live_grant(org_id, user.id, req.client.id)
    if grant is not None and grant.auth_stamp != auth_stamp(user.password_hash):
        # The password changed since this connection was made. It is over: do not revive its tokens
        # by refreshing the stamp in place; start a fresh grant.
        repo.revoke_grant(org_id, grant.id, "password_changed", now)
        db.flush()
        grant = None
    if grant is None:
        grant = OAuthGrant(
            org_id=org_id,
            user_id=user.id,
            client_pk=req.client.id,
            scope=req.scope,
            resource=req.resource,
            auth_stamp="",
        )
        try:
            with db.begin_nested():
                db.add(grant)
        except IntegrityError:  # two approvals at once: the other won, use its grant
            grant = repo.get_live_grant(org_id, user.id, req.client.id)
            if grant is None:
                raise
    grant.scope = req.scope
    grant.resource = req.resource
    grant.auth_stamp = auth_stamp(user.password_hash)
    raw = new_token(CODE_PREFIX)
    repo.add_code(
        org_id,
        grant.id,
        code_hash=hash_token(raw),
        code_challenge=req.code_challenge,
        redirect_uri=req.redirect_uri,
        resource=req.resource,
        expires_at=now + CODE_TTL,
    )
    db.commit()
    log_action(
        "mcp_grant_approved",
        "oauth_grant",
        grant.id,
        {
            "client": req.client.client_id[:200],
            "client_name": req.client.client_name,
            "verified": bool(req.client.verified),
        },
        org_id,
        user.id,
    )
    logger.info("mcp.grant_approved", grant_id=str(grant.id), client=req.client.client_id[:200])
    params = {"code": raw, "iss": config.mcp_issuer}
    if req.state is not None:
        params["state"] = req.state
    return append_query(req.redirect_uri, params)
