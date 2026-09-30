"""Blueprint factory for the Compliant product area.

Access to *every* route registered here — pages, API, static assets, the tools suite —
is gated on the caller's org holding an active ``compliant`` feature subscription
(``feature_subscriptions``). The gate is a single ``before_request`` on this parent
blueprint; Flask runs it for the nested api/pages/tools blueprints too.
"""

import os

from flask import Blueprint, abort, g, request, send_from_directory

from app.core.db import db_session
from app.core.security.entitlements import org_has_feature
from app.core.security.permissions import requires_auth
from app.features.compliant.routes.api_routes import api_bp
from app.features.compliant.routes.cca_movement_routes import cca_movement_bp
from app.features.compliant.routes.food_registration_routes import food_registration_bp
from app.features.compliant.routes.licensing_routes import licensing_bp
from app.features.compliant.routes.page_routes import page_bp
from app.features.compliant.routes.premises_routes import premises_bp
from app.features.compliant.routes.tools_routes import tools_bp
from app.features.compliant.routes.verification_routes import verification_bp
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

COMPLIANT_FEATURE_KEY = "compliant"


def create_compliant_blueprint() -> Blueprint:
    bp = Blueprint("compliant", __name__)
    bp.register_blueprint(api_bp)
    bp.register_blueprint(cca_movement_bp)
    bp.register_blueprint(page_bp)
    bp.register_blueprint(tools_bp)
    bp.register_blueprint(verification_bp)
    bp.register_blueprint(licensing_bp)
    bp.register_blueprint(premises_bp)
    bp.register_blueprint(food_registration_bp)
    root = os.path.dirname(os.path.abspath(__file__))

    @bp.before_request
    def _require_compliant_subscription():
        # Unauthenticated request: no tenant context yet. Do nothing — the route's own
        # @requires_auth produces the app's normal response (302 to "/" for pages, 401
        # for /api/*). The subscription gate never turns an unauthenticated request into
        # a 404.
        org_id = getattr(g, "current_org_id", None)
        if not org_id:
            return None

        subscribed = bool(config.compliant_enabled) and org_has_feature(db_session(), org_id, COMPLIANT_FEATURE_KEY)
        # Cache for the context processor, tagged with the org it was computed for so a
        # reused Flask app context can't serve a prior request's value (tenant_context.py
        # clears g.current_org_id per request but not arbitrary g attributes).
        g.compliant_subscribed = subscribed
        g.compliant_subscribed_org = org_id
        if not subscribed:
            logger.warning(
                "access_denied",
                reason="org_not_subscribed",
                feature="compliant",
                org_id=str(org_id),
                path=request.path,
                method=request.method,
            )
            abort(404)
        return None

    # Not named `static`: app/api/middleware/tenant_context.py treats any endpoint
    # ending in `.static` as public and skips loading g.current_user for it (the
    # convention exists for Flask's own built-in per-blueprint static-file serving,
    # which is intentionally unauthenticated). An endpoint literally named `static`
    # here would make @requires_auth below unconditionally 401 — g.current_user is
    # never set for it — which the global 401 handler then turns into a redirect to
    # "/" for any GET that doesn't start with /api|/auth|/static (this route doesn't),
    # so the browser follows it and gets HTML back for a script/stylesheet request
    # instead of a 401. See app/features/process_templates/process_templates_bp.py
    # for the same fix applied to the same bug class.
    @bp.route("/compliant/static/<path:filename>")
    @requires_auth
    def serve_compliant_static(filename: str):
        if "/" in filename or ".." in filename or not filename.endswith((".js", ".css")):
            abort(400)
        return send_from_directory(os.path.join(root, "frontend", "static"), filename)

    return bp
