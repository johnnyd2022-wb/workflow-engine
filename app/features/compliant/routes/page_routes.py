"""HTML surfaces for Compliant."""

from flask import Blueprint, redirect, render_template

from app.core.security.permissions import requires_auth

page_bp = Blueprint("compliant_pages", __name__, template_folder="../frontend/templates")


@page_bp.route("/compliant", methods=["GET"])
@requires_auth
def home():
    """The product-level landing page.

    Modules own their working surfaces.  Keeping this route as a small index gives an
    organisation a useful destination as new industries are added, rather than making
    the NZ Alcohol dashboard pretend it is the whole product.
    """
    return render_template("compliant/home.html", active_page="compliant")


@page_bp.route("/complaint", methods=["GET"])
@requires_auth
def legacy_complaint_home():
    """Forgive the historic public-facing spelling while keeping one canonical URL."""
    return redirect("/compliant", code=302)


@page_bp.route("/compliant/nz-alcohol", methods=["GET"])
@requires_auth
def nz_alcohol_dashboard():
    return render_template("compliant/dashboard.html", active_page="compliant")


@page_bp.route("/compliant/nz-alcohol/np3-audit", methods=["GET"])
@requires_auth
def nz_alcohol_np3_audit():
    return render_template("compliant/np3_audit.html", active_page="compliant")


@page_bp.route("/compliant/nz-alcohol/np3-audit/check/<control_id>", methods=["GET"])
@requires_auth
def nz_alcohol_np3_audit_check(control_id: str):
    return render_template("compliant/np3_check.html", active_page="compliant", control_id=control_id)


@page_bp.route("/compliant/nz-alcohol/configuration", methods=["GET"])
@requires_auth
def nz_alcohol_configuration():
    return render_template("compliant/configuration.html", active_page="compliant")
