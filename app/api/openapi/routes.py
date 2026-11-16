"""``GET /api/openapi.json``: the API's own description, narrowed to the caller (public MCP 8.2f).

A session or an assistant's token may fetch it. Each caller is shown only the operations their own
permissions reach, so the document names nothing they could not call; ``?audience=mcp`` narrows it
further to the operations marked ``x-bize.mcp`` that an assistant token of that person may call.
"""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from app.api.openapi.document import BuiltDocument, build, narrow
from app.core.security.permissions import requires_auth

openapi_bp = Blueprint("openapi", __name__)

AUDIENCES = frozenset({"mcp"})


def _built(app) -> BuiltDocument:
    """The whole document, built once per app: routes and the overlay do not change while it runs."""
    built = app.extensions.get("openapi_document")
    if built is None:
        built = app.extensions["openapi_document"] = build(app)
    return built


@openapi_bp.get("/api/openapi.json")
@requires_auth
def get_openapi():
    """The OpenAPI 3.1 description of this API, narrowed to the operations the caller may reach."""
    audience = request.args.get("audience")
    if audience is not None and audience not in AUDIENCES:
        return jsonify({"error": "unknown_audience", "message": "audience, when given, must be 'mcp'"}), 400
    document = narrow(_built(current_app), g.current_user, via_token=g.auth_via == "mcp", audience=audience)
    response = jsonify(document)
    # Different for every caller, so no shared cache may keep a copy.
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie, Authorization"
    return response
