"""HTML surfaces for Compliant."""

from flask import Blueprint, render_template

from app.core.security.permissions import requires_auth

page_bp = Blueprint("compliant_pages", __name__, template_folder="../frontend/templates")


@page_bp.route("/compliant", methods=["GET"])
@requires_auth
def dashboard():
    return render_template("compliant/dashboard.html", active_page="compliant")
