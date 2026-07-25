"""Dilution calculator page — serves the calculator SPA page."""

from flask import Blueprint, render_template

from app.core.security.permissions import requires_auth

page_bp = Blueprint("dilution_calculator_pages", __name__, template_folder="../frontend/templates")


@page_bp.route("/dilution-calculator", methods=["GET"])
@requires_auth
def dilution_calculator_index():
    return render_template("dilution_calculator/index.html", active_page="dilution_calculator")
