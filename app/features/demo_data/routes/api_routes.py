"""Demo data API — reset and reseed the demo organisation.

Register with: demo_data_routes.register_routes(core_bp)

Routes stay on the core blueprint so the URL is unchanged while the slice is
carved out. See .agents/plans/feature-slicing-plan.md (Phase 1).
"""

from flask import jsonify

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
        from app.features.demo_data.services.resetdb import reset_demo_db

        session = db_session()
        try:
            result = reset_demo_db(session)
            if not result.get("success"):
                return jsonify(result), 400
            return jsonify(result), 200
        except Exception as e:
            try:
                session.rollback()
            except Exception:
                pass
            logger.exception("reset_demo_db failed: %s", e)
            return jsonify({"success": False, "message": str(e), "error": "RESET_FAILED"}), 500
