"""Blueprint factory for the deployment-wide operational-cases capability.

``config.operational_cases_enabled`` is the one feature gate. Cases are available to every
organisation when it is on; Compliant remains the only per-organisation subscription-gated
module. Read-only history routes stay available during a deployment-wide disable so an
ADMIN can still recover the affected organisation's audit trail.
"""

from flask import Blueprint, abort, request

from app.features.operational_cases.routes.api_routes import api_bp
from app.features.operational_cases.routes.page_routes import page_bp
from app.utils.config_loader import config

_HISTORY_PATH_PREFIXES = ("/api/core/cases/history", "/core/cases/history")


def create_operational_cases_blueprint() -> Blueprint:
    bp = Blueprint("operational_cases", __name__)
    bp.register_blueprint(api_bp)
    bp.register_blueprint(page_bp)

    @bp.before_request
    def _bounded_request():
        if request.method in {"POST", "PATCH"}:
            request.max_content_length = 32 * 1024

    @bp.before_request
    def _require_operational_cases_enabled():
        if request.path.startswith(_HISTORY_PATH_PREFIXES):
            return None
        if not config.operational_cases_enabled:
            abort(404)
        return None

    return bp
