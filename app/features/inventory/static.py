"""Core's public Inventory header assets."""

import os

from flask import abort, send_from_directory
from werkzeug.exceptions import NotFound
from werkzeug.security import safe_join

from app.api.routes.auth_routes import limiter
from app.core.backend.static_assets import INVENTORY_STATIC_DIR
from app.observability import get_logger

logger = get_logger(__name__)

_INVENTORY_STATIC_ALLOWLIST = frozenset({"inventory-icon.svg", "inventory-spa-header.css"})


def register_routes(bp):
    @bp.route("/static/inventory/<filename>")
    @limiter.exempt
    def serve_core_inventory_static(filename):
        """Serve the two public SVG/CSS assets from inventory_static/ (used by
        the inventory SPA header partial). That directory holds public assets only -- the
        server-rendered inventory templates live in feature template directories and are never
        reachable through this route or the WhiteNoise layer that fronts it."""
        if ".." in filename or "/" in filename or "\\" in filename:
            abort(400, "Invalid filename")
        if filename not in _INVENTORY_STATIC_ALLOWLIST:
            abort(400, "Invalid file")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".svg", ".css"):
            abort(400, "Invalid file type")

        inventory_dir = INVENTORY_STATIC_DIR
        safe_path = safe_join(inventory_dir, filename)
        if safe_path is None:
            abort(400, "Invalid filename")

        try:
            response = send_from_directory(inventory_dir, filename)
            if ext == ".svg":
                response.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
            else:
                response.headers["Content-Type"] = "text/css; charset=utf-8"
            return response
        except (FileNotFoundError, NotFound):
            logger.info("Inventory static file not found: %s", filename)
            abort(404, "File not found")
        except Exception:
            logger.exception("Error serving inventory static: %s", filename)
            abort(500, "Internal server error")
