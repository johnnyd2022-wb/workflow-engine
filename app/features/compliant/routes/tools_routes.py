"""Compliant Tools: the calculators page, the catalogue, and the solve dispatch.

Every route here is gated by the parent blueprint's subscription ``before_request``
(see ``compliant_bp.py``). The solvers are pure functions — these routes touch no
tenant data; the only per-request DB read is the cached ``g.compliant_subscribed`` the
gate already computed.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from app.core.security.permissions import requires_auth
from app.features.compliant.tools.errors import CalculatorValidationError
from app.features.compliant.tools.registry import CALCULATORS, CATALOGUE
from app.observability import get_logger

logger = get_logger(__name__)

tools_bp = Blueprint("compliant_tools", __name__, template_folder="../frontend/templates")


@tools_bp.route("/compliant/tools", methods=["GET"])
@requires_auth
def tools_page():
    return render_template(
        "compliant/tools.html",
        active_page="compliant",
        calculators=CATALOGUE["calculators"],
    )


@tools_bp.route("/api/compliant/tools", methods=["GET"])
@requires_auth
def tools_catalogue():
    return jsonify(CATALOGUE), 200


@tools_bp.route("/api/compliant/tools/<key>/solve", methods=["POST"])
@requires_auth
def tools_solve(key: str):
    solver = CALCULATORS.get(key)
    if solver is None:
        return jsonify({"error": "unknown calculator"}), 404

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    try:
        result = solver(payload)
    except CalculatorValidationError as exc:
        logger.warning("compliant.tool_rejected", tool=key, reason=str(exc))
        return jsonify({"error": str(exc)}), 400

    logger.info("compliant.tool_solved", tool=key)
    return jsonify(result), 200
