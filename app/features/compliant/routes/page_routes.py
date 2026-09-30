"""HTML surfaces for Compliant."""

from uuid import UUID

from flask import Blueprint, g, redirect, render_template, request

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
    return {
        "active_page": "compliant",
        "food_control_programme": _food_safety_programme(settings),
        "liquor_licensing": bool((settings or {}).get("liquor_licence_types")),
        **context,
    }


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
def legacy_nz_alcohol_evidence():
    """Historic URL: NP3 evidence now lives per-check, so this page is Customs-only."""
    query = f"?{request.query_string.decode()}" if request.query_string else ""
    return redirect(f"/compliant/nz-alcohol/customs{query}", code=302)


@page_bp.route("/compliant/nz-alcohol/customs", methods=["GET"])
@requires_auth
def nz_alcohol_customs_workspace():
    """Customs alcohol reconciliation: product mapping and Customs record-keeping evidence.

    NP3 food-safety evidence is recorded per check in its own workspace (np3_check.html) and
    does not use this generic record form.
    """
    return render_template("compliant/customs.html", **_nz_alcohol_template_context())


@page_bp.route("/compliant/nz-alcohol/np3-audit", methods=["GET"])
@requires_auth
def nz_alcohol_np3_audit():
    """Keep previously shared NP3 links working as the programme page becomes generic."""
    return redirect("/compliant/nz-alcohol/food-safety", code=302)


@page_bp.route("/compliant/nz-alcohol/food-safety", methods=["GET"])
@requires_auth
def nz_alcohol_food_safety():
    context = _nz_alcohol_template_context()
    programme = context["food_control_programme"]
    if programme in {"np1", "np2", "np3"}:  # one verification workspace for every programme (plan 2.4b)
        return render_template("compliant/np3_audit.html", **_programme_labels(programme), **context)
    return redirect("/compliant/nz-alcohol/configuration", code=302)


@page_bp.route("/compliant/nz-alcohol/np3-audit/check/<control_id>", methods=["GET"])
@requires_auth
def nz_alcohol_np3_audit_check(control_id: str):
    context = _nz_alcohol_template_context(control_id=control_id)
    programme = context["food_control_programme"]
    if programme not in {"np1", "np2", "np3"}:
        return redirect("/compliant/nz-alcohol/food-safety", code=302)
    return render_template("compliant/np3_check.html", **_programme_labels(programme), **context)


def _programme_labels(programme: str) -> dict:
    from app.features.compliant.modules.nz_alcohol.national_programmes import GUIDANCE

    guidance = GUIDANCE[programme]
    return {"programme_label": guidance["label"], "programme_short": guidance["short"], "guidance_url": guidance["url"]}


@page_bp.route("/compliant/nz-alcohol/configuration", methods=["GET"])
@requires_auth
def nz_alcohol_configuration():
    return render_template(
        "compliant/configuration.html", **_nz_alcohol_template_context()
    )
