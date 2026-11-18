"""Settings -> AI assistants (public MCP 8.2e): the page that drives ``/api/core/mcp/*``.

The page is for everyone who is signed in: an admin (``users.manage``) gets the switch, the role
picker and every connected app in the organisation; anyone else gets their own connections and
a plain sentence about whether they can connect one. The controls are not hidden with CSS for
non-admins: the template never renders them, and the API behind them answers 403 as well.
"""

from __future__ import annotations

from flask import Blueprint, g, render_template

from app.core.db import db_session
from app.core.security.access_policy import has_permission
from app.core.security.permissions import requires_auth
from app.features.mcp_oauth.services import authorization
from app.utils.config_loader import config

# The page's script and stylesheet live in this slice, like the costing pages' do.
pages_bp = Blueprint(
    "mcp_pages",
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static",
    static_url_path="/static/mcp-settings",
)

PAGE_PATH = "/core/ai-assistants"


@pages_bp.get(PAGE_PATH)
@requires_auth
def ai_assistants_page():
    user = g.current_user
    can_manage = has_permission(user, "users.manage")
    # An admin turns this on from the page itself, so the note is only for everyone else.
    blocked = None if can_manage else authorization.connect_block_reason(db_session(), user)
    return render_template(
        "mcp_settings/ai_assistants.html",
        active_page="settings",
        can_manage=can_manage,
        blocked=blocked,
        mcp_url=config.mcp_resource,
        user_id=str(user.id),
    )
