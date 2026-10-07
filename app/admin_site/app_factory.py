"""The admin site's own Flask application. Nothing here registers a customer-app route."""

from __future__ import annotations

import os
from datetime import timedelta

from flask import Flask, jsonify, send_from_directory
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from app.admin_site.auth import admin_auth_bp, limiter, require_admin
from app.admin_site.routes import admin_bp
from app.admin_site.settings import SESSION_HOURS, load_settings
from app.core.db import db_session
from app.features.google_sign_in.oidc import register_google_client
from app.observability import configure_logging, get_logger
from app.utils.config_loader import config

_CORE_CSS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "frontend", "css")
# The customer app's shared look, served read-only so both sites stay in step.
SHARED_STYLES = frozenset({"design-system.css", "workspace-overviews.css"})

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self' https://accounts.google.com"
)


def create_admin_app(settings=None) -> Flask:
    configure_logging(config)
    logger = get_logger(__name__)
    settings = settings or load_settings(config)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.extensions["admin_settings"] = settings
    app.secret_key = settings.secret_key
    app.config.update(
        # A cookie of its own: an admin session and a customer session never mix, even
        # when both sites are open in one browser on the same parent domain.
        SESSION_COOKIE_NAME="bize_admin_session",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",  # Lax, not Strict: Google's redirect back must carry the cookie
        PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
        MAX_CONTENT_LENGTH=64 * 1024,  # forms only; nothing is uploaded here
        WTF_CSRF_TIME_LIMIT=SESSION_HOURS * 3600,
    )
    # One proxy in front (the Cloudflare tunnel): trust its scheme and client address.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    limiter.init_app(app)
    CSRFProtect(app)
    register_google_client(app, settings.google_client_id, settings.google_client_secret, settings.google_redirect_uri)

    app.before_request(require_admin)
    app.register_blueprint(admin_auth_bp)
    app.register_blueprint(admin_bp)

    @app.route("/healthcheck")
    def healthcheck():
        return jsonify({"status": "ok"})

    @app.route("/shared/<name>")
    def shared_style(name):
        if name not in SHARED_STYLES:
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(_CORE_CSS_DIR, name, mimetype="text/css")

    @app.after_request
    def secure_response(response):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        if response.mimetype != "text/css":
            # Pages can show a one-time invite link or password; nothing may keep a copy.
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.teardown_appcontext
    def release_database_session(_exc=None):
        db_session.remove()

    logger.info(
        "admin_site_ready",
        environment=settings.environment,
        admins=len(settings.allowed_emails),
        redirect_uri=settings.google_redirect_uri,
    )
    return app
