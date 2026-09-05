"""Blueprint factory for operational_cases (A1).

Two independent gates, per .agents/specs/operational_cases.md "Concrete gating":
1. ``config.operational_cases_enabled`` -- deployment-wide kill switch. The blueprint is
   only registered at all when this is true (same pattern as compliant/crm).
2. A per-org active ``FeatureSubscription(feature_key='operational_cases')`` row --
   pilot-controlled entitlement, checked on every request via ``before_request``.

The read-only history routes (``/api/core/cases/history/*``, admin-only) are explicitly
exempted from gate 2 so a defect that revokes an org's subscription doesn't also strand
its own recovery path (see the spec's rollout/recovery plan, point 4).
"""

from flask import Blueprint, abort, g, request

from app.core.db import db_session
from app.core.security.entitlements import org_has_feature
from app.features.operational_cases.routes.api_routes import api_bp
from app.features.operational_cases.routes.page_routes import page_bp
from app.features.operational_cases.services.operational_case_service import OPERATIONAL_CASES_FEATURE_KEY
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

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
    def _require_operational_cases_subscription():
        org_id = getattr(g, "current_org_id", None)
        if not org_id:
            # No tenant context yet: let the route's own @requires_auth produce the
            # app's normal response, same reasoning as compliant_bp's identical gate.
            return None

        if request.path.startswith(_HISTORY_PATH_PREFIXES):
            return None

        subscribed = config.operational_cases_enabled and org_has_feature(
            db_session(), org_id, OPERATIONAL_CASES_FEATURE_KEY
        )
        g.operational_cases_subscribed = subscribed
        g.operational_cases_subscribed_org = org_id
        if not subscribed:
            logger.info(
                "access_denied",
                reason="org_not_subscribed",
                feature=OPERATIONAL_CASES_FEATURE_KEY,
                org_id=str(org_id),
                path=request.path,
                method=request.method,
            )
            abort(404)
        return None

    return bp
