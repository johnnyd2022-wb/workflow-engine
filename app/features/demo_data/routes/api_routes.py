"""Demo data API — reset and reseed the demo organisation.

Register with: demo_data_routes.register_routes(core_bp)

Routes stay on the core blueprint so the URL is unchanged while the slice is
carved out. See .agents/plans/feature-slicing-plan.md (Phase 1).
"""

from flask import g, jsonify, request

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)


def register_routes(bp):
    """Register demo-data API routes on the given Flask Blueprint."""

    @bp.route("/api/core/reset-demo-db", methods=["POST"])
    @requires_auth
    def reset_demo_db_route():
        """Reset and populate DB with demo data for demo@whistlebird.co.nz. Only available in test or local environment."""
        if config.environment not in ("test", "local"):
            return jsonify(
                {"error": "Reset demo DB is only available in test or local environment", "success": False}
            ), 403
        from app.core.db.repositories.user_repo import UserRepository
        from app.core.security.tenant_scope import unscoped
        from app.features.demo_data.services.resetdb import DEMO_USER_EMAIL

        session = db_session()

        # Explicit caller-identity check, deliberately independent of the global tenant
        # filter (app/core/db/tenant_filter.py) that incidentally also scopes the
        # demo-user lookup below to the caller's own org: that filter is documented as
        # additive defense-in-depth, not a substitute for this route's own
        # authorization, and relying on it alone fails silently (a confusing 400 "user
        # not found" instead of a clear, logged access-denied) if that lookup's shape
        # ever changes. `unscoped()` makes this comparison genuine rather than an
        # accidental side effect of the filter. Only members of the demo org itself may
        # trigger a reset of its data.
        with unscoped():
            demo_user = UserRepository(session).get_user_by_email(DEMO_USER_EMAIL)
        if not demo_user or g.current_org_id != demo_user.org_id:
            logger.warning(
                "access_denied",
                reason="not_demo_org_member",
                path=request.path,
                method=request.method,
                user_id=str(g.current_user.id),
                org_id=str(g.current_org_id),
            )
            return jsonify({"success": False, "error": "FORBIDDEN", "message": "Not authorized"}), 403

        from app.features.demo_data.services.resetdb import reset_demo_db

        try:
            result = reset_demo_db(session)
            if not result.get("success"):
                return jsonify(result), 400
            logger.info(
                "demo_data_reset_completed",
                org_id=str(demo_user.org_id),
                user_id=str(g.current_user.id),
            )
            return jsonify(result), 200
        except Exception as e:
            try:
                session.rollback()
            except Exception:
                pass
            logger.exception("reset_demo_db failed: %s", e)
            return jsonify(
                {"success": False, "message": "Demo reset failed, see server logs", "error": "RESET_FAILED"}
            ), 500
