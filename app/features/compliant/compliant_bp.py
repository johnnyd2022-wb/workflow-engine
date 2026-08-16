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

    @bp.route("/compliant/static/<path:filename>")
    @requires_auth
    def static(filename: str):
        if "/" in filename or ".." in filename or not filename.endswith((".js", ".css")):
            abort(400)
        return send_from_directory(os.path.join(root, "frontend", "static"), filename)

    return bp
