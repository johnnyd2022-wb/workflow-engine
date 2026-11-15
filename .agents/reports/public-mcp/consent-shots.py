"""Screenshot scenarios for the assistant consent page (public MCP 8.2b), for scripts/ui_shots.py.

    export UI_SHOTS_HOME=~/.cache/workflow-engine-ui-shots/mcp-consent
    env -u ENVIRONMENT uv run python scripts/ui_shots.py seed stock
    env -u ENVIRONMENT uv run python scripts/ui_shots.py shoot OUT --scenarios .agents/reports/public-mcp/consent-shots.py
    env -u ENVIRONMENT uv run python scripts/ui_shots.py purge

The seeded org gets assistants switched on for its roles; the clients these scenarios create carry
the client_id prefix "shots-" and the last scenario (``zz_cleanup``) deletes them.
"""

from urllib.parse import urlencode

from ui_shots import LAPTOP, PHONE, _state, settle, shot

CLIENTS = {
    "claude": ("shots-claude", "Claude", "https://claude.ai/api/mcp/auth_callback", False),
    "verified": ("shots-verified", "Biz-E Assistant", "https://assistant.biz-e.app/callback", True),
    "long": (
        "shots-long",
        "Acme Distillery Production Planning and Compliance Assistant for Multi-Site Operations (beta)",
        "https://a-very-long-subdomain-name.assistants.example-corporation-international.co.nz/oauth/callback/v2",
        False,
    ),
}
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def _config():
    from app.utils.config_loader import config

    return config


def _prepare(role=None, enabled=True, roles=("admin", "sales")):
    """Make the seeded org assistant-ready; optionally change the seeded user's role."""
    from app.core.db import db_session
    from app.core.db.models.user import User, UserRole
    from app.core.security.tenant_scope import unscoped
    from app.features.mcp_oauth.models import McpAllowedRole, McpOrgSettings, OAuthClient

    state = _state()
    db = db_session()
    with unscoped():
        org_id = state["org_id"]
        db.query(McpAllowedRole).filter(McpAllowedRole.org_id == org_id).delete(synchronize_session=False)
        settings = db.get(McpOrgSettings, org_id)
        if settings is None:
            settings = McpOrgSettings(org_id=org_id)
            db.add(settings)
        settings.enabled = enabled
        for role_name in roles:
            db.add(McpAllowedRole(org_id=org_id, role_key=f"builtin:{role_name}"))
        for client_id, name, redirect, verified in CLIENTS.values():
            row = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).one_or_none()
            if row is None:
                row = OAuthClient(client_id=client_id, client_name=name, redirect_uris=[redirect], registration="dcr")
                db.add(row)
            row.verified = verified
        user = db.get(User, state["user_id"])
        user.role = UserRole(role or "admin")
        db.commit()


def _url(key, **overrides):
    client_id, _name, redirect, _verified = CLIENTS[key]
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "state": "abc123",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "scope": "bize.read",
        "resource": _config().mcp_resource,
    }
    params.update(overrides)
    return "/oauth/authorize?" + urlencode(params)


def _set_theme(page, mode):
    page.evaluate("mode => localStorage.setItem('spa-theme', mode)", mode)


def _open(page, key, viewport=None, **overrides):
    if viewport:
        page.set_viewport_size(viewport)
    page.goto(_url(key, **overrides))
    page.wait_for_selector("h1")
    settle(page, 200)


def consent_desktop(page, out):
    _prepare()
    _open(page, "claude")
    shot(page, out, "consent-desktop")
    shot(page, out, "consent-desktop-full", full=True)


def consent_laptop(page, out):
    _prepare()
    _open(page, "claude", LAPTOP)
    shot(page, out, "consent-laptop")


def consent_phone(page, out):
    _prepare()
    _open(page, "claude", PHONE)
    shot(page, out, "consent-phone")
    shot(page, out, "consent-phone-full", full=True)


def consent_verified_phone(page, out):
    _prepare()
    _open(page, "verified", PHONE)
    shot(page, out, "consent-verified-phone")


def consent_narrow_role_phone(page, out):
    """A Sales person sees only what Sales can read."""
    _prepare(role="sales")
    _open(page, "claude", PHONE)
    shot(page, out, "consent-sales-phone", full=True)
    _prepare()


def consent_long_values_phone(page, out):
    _prepare()
    _open(page, "long", PHONE)
    shot(page, out, "consent-long-phone", full=True)
    _open(page, "long")
    shot(page, out, "consent-long-desktop")


def consent_dark_desktop(page, out):
    _prepare()
    _set_theme(page, "dark")
    try:
        _open(page, "claude")
        shot(page, out, "consent-dark-desktop")
    finally:
        _set_theme(page, "light")


def consent_dark_phone(page, out):
    _prepare()
    _set_theme(page, "dark")
    try:
        _open(page, "claude", PHONE)
        shot(page, out, "consent-dark-phone", full=True)
    finally:
        _set_theme(page, "light")


def blocked_org_off(page, out):
    _prepare(enabled=False)
    _open(page, "claude", PHONE)
    shot(page, out, "blocked-org-off-phone")
    _open(page, "claude")
    shot(page, out, "blocked-org-off-desktop")
    _prepare()


def blocked_role_dark(page, out):
    _prepare(roles=("sales",))  # the seeded user is an admin and is not ticked
    _set_theme(page, "dark")
    try:
        _open(page, "claude", PHONE)
        shot(page, out, "blocked-role-dark-phone")
    finally:
        _set_theme(page, "light")
    _prepare()


def error_page(page, out):
    _prepare()
    _open(page, "claude", PHONE, redirect_uri="https://elsewhere.example/steal")
    shot(page, out, "error-phone")
    _open(page, "claude")
    shot(page, out, "error-desktop")


def zz_cleanup(page, out):
    from app.core.db import db_session
    from app.features.mcp_oauth.models import OAuthClient

    db = db_session()
    db.query(OAuthClient).filter(OAuthClient.client_id.like("shots-%")).delete(synchronize_session=False)
    db.commit()
