"""Blueprint factory for the Compliant product area."""

import os

from flask import Blueprint, abort, send_from_directory

from app.core.security.permissions import requires_auth
from app.features.compliant.routes.api_routes import api_bp
from app.features.compliant.routes.page_routes import page_bp


def create_compliant_blueprint() -> Blueprint:
    bp = Blueprint("compliant", __name__)
    bp.register_blueprint(api_bp)
    bp.register_blueprint(page_bp)
    root = os.path.dirname(os.path.abspath(__file__))

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
