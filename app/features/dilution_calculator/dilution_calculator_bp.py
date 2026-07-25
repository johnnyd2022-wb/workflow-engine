"""Dilution calculator blueprint factory — assembles the API and page sub-blueprints."""

from flask import Blueprint

from app.features.dilution_calculator.routes.api_routes import api_bp
from app.features.dilution_calculator.routes.page_routes import page_bp


def create_dilution_calculator_blueprint() -> Blueprint:
    """Create and return the assembled dilution calculator blueprint."""
    dilution_calculator_bp = Blueprint("dilution_calculator", __name__)

    dilution_calculator_bp.register_blueprint(api_bp)
    dilution_calculator_bp.register_blueprint(page_bp)

    return dilution_calculator_bp
