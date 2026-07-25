"""Dilution calculator API — stateless solve endpoint, no tenant data touched."""

from flask import Blueprint, jsonify, request

from app.core.security.permissions import requires_auth
from app.features.dilution_calculator.services.dilution_service import (
    DilutionValidationError,
    solve_dilution,
)
from app.observability import get_logger

logger = get_logger(__name__)

api_bp = Blueprint("dilution_calculator_api", __name__)


@api_bp.route("/api/dilution-calculator/solve", methods=["POST"])
@requires_auth
def solve():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    try:
        result = solve_dilution(payload)
    except DilutionValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    logger.info("dilution_calculator.solved", solve_for=result["solved_field"])
    return jsonify(result), 200
