"""CRM blueprint factory — assembles all CRM sub-blueprints."""

import functools
import hashlib
import os

from flask import Blueprint, send_from_directory

from app.core.security.permissions import requires_auth
from app.features.crm.routes.api_routes import api_bp
from app.features.crm.routes.oauth_routes import oauth_bp
from app.features.crm.routes.page_routes import page_bp


def create_crm_blueprint() -> Blueprint:
    """Create and return the assembled CRM blueprint."""
    crm_bp = Blueprint("crm", __name__)

    crm_bp.register_blueprint(oauth_bp)
    crm_bp.register_blueprint(api_bp)
    crm_bp.register_blueprint(page_bp)

    # Serve CRM static files (JS, CSS)
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    _frontend_js_dir = os.path.join(_current_dir, "frontend", "js")
    _frontend_css_dir = os.path.join(_current_dir, "frontend", "css")

    @functools.lru_cache(maxsize=1)
    def _crm_asset_version() -> str:
        """See app.core.backend.backend._asset_version -- same cache-bust, CRM's bundles."""
        h = hashlib.blake2b(digest_size=8)
        for directory in (_frontend_js_dir, _frontend_css_dir):
            try:
                names = sorted(os.listdir(directory))
            except OSError:
                continue
            for name in names:
                try:
                    st = os.stat(os.path.join(directory, name))
                except OSError:
                    continue
                h.update(f"{name}:{int(st.st_mtime)}:{st.st_size}\n".encode())
        return h.hexdigest()

    @crm_bp.url_defaults
    def _crm_static_asset_version(endpoint: str, values: dict) -> None:
        if endpoint in ("crm.serve_crm_js", "crm.serve_crm_css") and "v" not in values:
            values["v"] = _crm_asset_version()

    @crm_bp.route("/crm/static/js/<path:filename>")
    @requires_auth
    def serve_crm_js(filename):
        from flask import abort

        if ".." in filename or "/" in filename:
            abort(400)
        if not filename.endswith(".js"):
            abort(400)
        return send_from_directory(_frontend_js_dir, filename, mimetype="application/javascript")

    @crm_bp.route("/crm/static/css/<path:filename>")
    @requires_auth
    def serve_crm_css(filename):
        from flask import abort

        if ".." in filename or "/" in filename:
            abort(400)
        if not filename.endswith(".css"):
            abort(400)
        return send_from_directory(_frontend_css_dir, filename, mimetype="text/css")

    return crm_bp
