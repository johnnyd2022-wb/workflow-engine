"""HTML pages for operational_cases: the Cases queue and case detail. Registered at the
existing /core/* URL convention (spec: "takes precedence over a new slug URL prefix").
"""

import os
from uuid import UUID

from flask import Blueprint, abort, g, render_template, send_from_directory

from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.features.operational_cases.repositories.operational_case_repo import OperationalCaseRepository

page_bp = Blueprint("operational_cases_pages", __name__, template_folder="../frontend/templates")

_STATIC_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "static")


@page_bp.route("/core/cases", methods=["GET"])
@requires_auth
def queue():
    return render_template("operational_cases/queue.html", active_page="cases")


@page_bp.route("/core/cases/new", methods=["GET"])
@requires_auth
def new_case():
    return render_template("operational_cases/new.html", active_page="cases")


@page_bp.route("/core/cases/static/<path:filename>")
@requires_auth
def serve_static(filename: str):
    # Same shape as compliant_bp.serve_compliant_static: authenticated, allowlisted
    # extensions only, no path traversal.
    if "/" in filename or ".." in filename or not filename.endswith((".js", ".css")):
        abort(400)
    return send_from_directory(_STATIC_ROOT, filename)


@page_bp.route("/core/cases/<case_id>", methods=["GET"])
@requires_auth
def detail(case_id: str):
    try:
        cid = UUID(case_id)
    except ValueError:
        abort(404)
    if OperationalCaseRepository(db_session()).get_by_id(cid, g.current_org_id) is None:
        abort(404)
    return render_template("operational_cases/detail.html", active_page="cases", case_id=case_id)
