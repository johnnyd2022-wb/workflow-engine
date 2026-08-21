"""HTML surface for the industry process template catalogue browser."""

from flask import Blueprint, render_template

from app.core.security.permissions import requires_auth

page_bp = Blueprint("process_templates_pages", __name__, template_folder="../frontend/templates")


@page_bp.route("/core/flows/create/template-catalog", methods=["GET"])
@requires_auth
def template_catalog_page():
    """Template browser. Not capability-gated itself — an org with zero permitted
    families still gets a 200 render with an empty-state message (AC12); only the
    catalogue *data*, fetched client-side, is gated per-org.
    """
    return render_template("process_templates/template-catalog.html", active_page="core")
