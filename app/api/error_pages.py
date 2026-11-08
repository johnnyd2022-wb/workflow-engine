"""Error pages and error JSON that say how to get help, with a reference (GL-C04).

A page that isn't there, or a request that fails on the server, used to answer Flask's bare
"Not Found" / "Internal Server Error" page with nothing to quote. Now:

* a page (browser navigation) gets a short page in the app's words, with the support email and
  the request's reference;
* an API call gets ``{"error": ..., "reference": ...}``, so a script or a page's own error
  message can show the reference too.

Every response already carries the full id as ``X-Request-ID`` (observability middleware).
"""

from __future__ import annotations

from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException, InternalServerError, NotFound

from app.observability import get_logger
from app.observability.reference import request_reference

logger = get_logger(__name__)

_COPY = {
    404: ("We couldn't find that page", "The link may be old, or the page may have moved."),
    500: ("Something went wrong on our side", "Nothing you did caused this. Try again in a minute."),
}


def _wants_json() -> bool:
    if request.path.startswith("/api/") or request.is_json:
        return True
    accept = request.accept_mimetypes
    return accept.best_match(["application/json", "text/html"]) == "application/json"


def _respond(status: int, api_message: str):
    reference = request_reference()
    if _wants_json():
        return jsonify({"error": api_message, "reference": reference}), status
    title, detail = _COPY[status]
    return render_template("errors/error.html", status=status, title=title, detail=detail, reference=reference), status


def register_error_pages(app) -> None:
    app.add_template_global(request_reference, "request_reference")

    @app.errorhandler(NotFound)
    def _not_found(_e: HTTPException):
        return _respond(404, "Not found")

    @app.errorhandler(InternalServerError)
    def _server_error(e: InternalServerError):
        # The original exception was already logged with its traceback by Flask; this line ties
        # the reference the person sees to that log entry.
        logger.error("server_error_page", reference=request_reference(), original=type(e.original_exception).__name__)
        return _respond(500, "Something went wrong on our side")
