"""Authlib boundary: authorization code, S256 PKCE and verified ID tokens only."""

from urllib.parse import urlsplit

from authlib.integrations.flask_client import OAuth
from flask import current_app

from app.features.google_sign_in.service import ISSUERS, GoogleSignInError, validate_verified_claims


def setup_google_oidc(app, config):
    app.config["GOOGLE_SIGN_IN_ENABLED"] = config.getboolean("google_sign_in", "enabled", False)
    if not app.config["GOOGLE_SIGN_IN_ENABLED"]:
        return
    register_google_client(app, config.google_client_id, config.google_client_secret, config.google_redirect_uri)


def register_google_client(app, client_id, client_secret, redirect_uri):
    """Register the one Google client an app signs in with. Shared with the admin site."""
    if not app.config.get("SESSION_COOKIE_SECURE") or not app.config.get("SESSION_COOKIE_HTTPONLY"):
        raise RuntimeError("Google sign-in requires Secure and HttpOnly session cookies")
    parsed = urlsplit(redirect_uri)
    if (
        not client_id
        or not client_secret
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/auth/google/callback"
    ):
        raise RuntimeError("Google sign-in requires credentials and a fixed HTTPS /auth/google/callback redirect URI")
    app.config["GOOGLE_SIGN_IN_ENABLED"] = True
    app.config["GOOGLE_CLIENT_ID"] = client_id
    app.config["GOOGLE_REDIRECT_URI"] = redirect_uri
    oauth = OAuth(app)
    client = oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email", "code_challenge_method": "S256", "timeout": 10},
    )
    app.extensions["google_oidc_client"] = client


def google_client():
    if not current_app.config.get("GOOGLE_SIGN_IN_ENABLED"):
        raise GoogleSignInError("Google sign-in is not configured")
    return current_app.extensions["google_oidc_client"]


def exchange_verified_identity(nonce):
    """This is the only token-verification boundary mocked by route tests.

    Authlib checks state, exchanges the one-time code with the saved PKCE verifier,
    and verifies the ID token's signature against Google's discovered JWKS. Zero
    expiry leeway, pinned issuers and essential nonce/email claims fail closed.
    No access/refresh token is stored in an application session or database.
    """
    token = google_client().authorize_access_token(
        leeway=0,
        claims_options={
            "iss": {"essential": True, "values": list(ISSUERS)},
            "aud": {"essential": True},
            "exp": {"essential": True},
            "nonce": {"essential": True, "value": nonce},
            "email_verified": {"essential": True, "value": True},
        },
    )
    claims = token.get("userinfo")
    if not token.get("id_token") or claims is None:
        raise GoogleSignInError("Missing verified Google identity")
    return validate_verified_claims(claims, current_app.config["GOOGLE_CLIENT_ID"], nonce)
