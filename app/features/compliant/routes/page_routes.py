"""HTML surfaces for Compliant."""

from uuid import UUID

from flask import Blueprint, g, redirect, render_template

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.features.compliant.service import ComplianceService

page_bp = Blueprint("compliant_pages", __name__, template_folder="../frontend/templates")
_FOOD_SAFETY_PROGRAMMES = frozenset({"np1", "np2", "np3", "none"})


def _food_safety_programme(settings: dict | None) -> str:
    """Return the single programme whose workspace may appear in navigation."""
    programme = (settings or {}).get("food_control_programme", "np3")
    return programme if isinstance(programme, str) and programme in _FOOD_SAFETY_PROGRAMMES else "np3"


def _nz_alcohol_template_context(**context):
    profile = ComplianceService(db_session()).get_profile(UUID(g.org_id))
    settings = profile.settings if profile else {}
    return {"active_page": "compliant", "food_control_programme": _food_safety_programme(settings), **context}


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
    return render_template("compliant/dashboard.html", **_nz_alcohol_template_context())


@page_bp.route("/compliant/nz-alcohol/evidence", methods=["GET"])
@requires_auth
def nz_alcohol_evidence_register():
    """Fallback evidence and product-mapping workspace for non-NP3 controls."""
    return render_template("compliant/evidence_register.html", **_nz_alcohol_template_context(active_compliant_tab="evidence"))


@page_bp.route("/compliant/nz-alcohol/np3-audit", methods=["GET"])
@requires_auth
def nz_alcohol_np3_audit():
    """Keep previously shared NP3 links working as the programme page becomes generic."""
    return redirect("/compliant/nz-alcohol/food-safety", code=302)


@page_bp.route("/compliant/nz-alcohol/food-safety", methods=["GET"])
@requires_auth
def nz_alcohol_food_safety():
    context = _nz_alcohol_template_context(active_compliant_tab="food-safety")
    programme = context["food_control_programme"]
    if programme == "np3":
        return render_template("compliant/np3_audit.html", **context)
    if programme in {"np1", "np2"}:
        return render_template("compliant/food_safety_coming_soon.html", **context)
    return redirect("/compliant/nz-alcohol/configuration", code=302)


@page_bp.route("/compliant/nz-alcohol/np3-audit/check/<control_id>", methods=["GET"])
@requires_auth
def nz_alcohol_np3_audit_check(control_id: str):
    context = _nz_alcohol_template_context(active_compliant_tab="food-safety", control_id=control_id)
    if context["food_control_programme"] != "np3":
        return redirect("/compliant/nz-alcohol/food-safety", code=302)
    return render_template("compliant/np3_check.html", **context)


@page_bp.route("/compliant/nz-alcohol/configuration", methods=["GET"])
@requires_auth
def nz_alcohol_configuration():
    return render_template(
        "compliant/configuration.html", **_nz_alcohol_template_context(active_compliant_tab="configuration")
    )
