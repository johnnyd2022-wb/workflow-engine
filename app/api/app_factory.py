"""Flask application factory"""

import json
import os
import re

import requests
from flask import Flask, Response, g, jsonify, redirect, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from app.api.middleware.session_security import setup_session_security
from app.api.middleware.tenant_context import setup_tenant_context
from app.api.routes.auth_routes import auth_bp
from app.api.routes.org_routes import org_bp
from app.observability import (
    configure_logging,
    configure_metrics,
    configure_tracing,
    get_logger,
    setup_observability,
)
from app.utils.config_loader import config

# Assets under /ui/shared that the logged-out landing page needs. Everything else in that
# directory stays authenticated. password-policy.js is only a thin client for
# /auth/password-policy-check, which is itself public (auth_routes.py) because signup must
# call it before a session exists — gating the script but not its endpoint left the signup
# form with no live password guidance at all. Add here only for assets a logged-out page
# genuinely loads, and only when the asset is not org-specific: these bytes are
# world-readable.
PUBLIC_UI_SHARED_FILES = frozenset({"password-policy.js"})


def create_app():
    """Create and configure Flask application"""
    configure_logging(config)
    logger = get_logger(__name__)

    # Get the path to app/ui/templates for shared components
    current_file = os.path.abspath(__file__)  # app/api/app_factory.py
    api_dir = os.path.dirname(current_file)  # app/api/
    app_dir = os.path.dirname(api_dir)  # app/
    ui_templates_dir = os.path.join(app_dir, "ui", "templates")

    # Set the app's template folder to the shared templates directory
    # Flask will also search blueprint template folders automatically
    app = Flask(__name__, template_folder=ui_templates_dir)

    # Enforce max request body for uploads (evidence max size) to avoid memory spikes under load
    if hasattr(config, "evidence_max_file_size_mb"):
        app.config["MAX_CONTENT_LENGTH"] = config.evidence_max_file_size_mb * 1024 * 1024

    # Set secret key for sessions (should be in config in production)
    app.secret_key = config.get("app", "secret_key", fallback="dev-secret-key-change-in-production")

    # Configure session cookies for production security
    # CRITICAL: Always use Secure=True (HTTPS is used in both local dev and production)
    # This prevents session cookies from being sent over unencrypted connections
    app.config["SESSION_COOKIE_SECURE"] = config.getboolean("app", "session_cookie_secure", fallback=True)
    app.config["SESSION_COOKIE_HTTPONLY"] = True  # Prevent XSS attacks by blocking JavaScript access
    app.config["SESSION_COOKIE_SAMESITE"] = (
        "Lax"  # Lax: blocks cross-site POST/PUT/DELETE (CSRF) while allowing top-level GET navigations
    )
    app.config["SESSION_COOKIE_PATH"] = "/"  # Explicitly set cookie path to root
    # Align PERMANENT_SESSION_LIFETIME with default user session timeout (7 days default, max 30 days)
    app.config["PERMANENT_SESSION_LIFETIME"] = 30 * 24 * 3600  # 30 days (max session lifetime)
    app.config.setdefault("ENFORCE_HTTPS", True)

    # Initialize rate limiter (IP-based)
    # Import limiter from auth_routes and initialize it with the app
    from app.api.routes.auth_routes import limiter

    limiter.init_app(app)
    app.limiter = limiter

    # Observability providers and automatic instrumentation are configured before
    # blueprint registration so request hooks and spans are available to all routes.
    configure_tracing(app, config)
    configure_metrics(config)
    if config.otel_enabled and config.grafana_data_enabled:
        try:
            from opentelemetry.instrumentation.requests import RequestsInstrumentor
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            from app.core.db import engine

            SQLAlchemyInstrumentor().instrument(engine=engine)
            RequestsInstrumentor().instrument()
        except Exception:
            logger.exception("Failed to initialize OpenTelemetry auto-instrumentors")

    # Register multi-tenant blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(org_bp)

    # Register core blueprint
    from app.core.backend.backend import core_bp

    app.register_blueprint(core_bp)

    # Register CRM blueprint (feature-flagged)
    if config.crm_enabled:
        from app.features.crm.crm_bp import create_crm_blueprint

        app.register_blueprint(create_crm_blueprint())

    # Serve shared UI files (JavaScript and CSS) (register before middleware)
    @app.route("/ui/shared/<path:filename>")
    @limiter.exempt
    def serve_ui_shared(filename):
        """Serve shared UI files (JS/CSS): authenticated by default, public by allowlist.

        Auth is enforced inside the view rather than via @requires_auth so the allowlist
        can be honoured. A 401 here would be turned into a 302 to "/" by the global 401
        handler, so a gated script returns HTML and the browser refuses to execute it —
        which is exactly the bug this allowlist fixes for password-policy.js.
        """
        from flask import abort
        from werkzeug.security import safe_join

        if filename not in PUBLIC_UI_SHARED_FILES and (not hasattr(g, "current_user") or not g.current_user):
            abort(401, description="Authentication required")

        # Path traversal protection: reject filenames with .. or /
        if ".." in filename or "/" in filename or "\\" in filename:
            abort(400, "Invalid filename")

        # Extension whitelist for security
        allowed_extensions = {".js", ".css"}
        if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
            abort(400, "Invalid file type")

        # Calculate path: app_factory.py is in app/api/
        # Go up 3 levels: app/api/ -> app/ -> project_root/
        # Then join with app/ui/shared
        current_file = os.path.abspath(__file__)  # full path to app/api/app_factory.py
        api_dir = os.path.dirname(current_file)  # app/api/
        app_dir = os.path.dirname(api_dir)  # app/
        project_root = os.path.dirname(app_dir)  # project root
        shared_dir = os.path.join(project_root, "app", "ui", "shared")

        # Use safe_join for validation only (not for file access)
        safe_path = safe_join(shared_dir, filename)
        if safe_path is None:
            abort(400, "Invalid filename")

        # File serving must be done exclusively via send_from_directory
        try:
            response = send_from_directory(shared_dir, filename)
            # Set explicit Content-Type headers
            if filename.endswith(".js"):
                response.headers["Content-Type"] = "application/javascript; charset=utf-8"
            elif filename.endswith(".css"):
                response.headers["Content-Type"] = "text/css; charset=utf-8"
            # X-Content-Type-Options is set globally in after_request handler
            return response
        except FileNotFoundError:
            # Missing static file - log at info level (not error)
            logger.info(f"Static file not found: {filename} from {shared_dir}")
            abort(404, "File not found")
        except Exception:
            # Unexpected exception - log at exception level
            logger.exception(f"Unexpected error serving static file: {filename}")
            abort(500, "Internal server error")

    def _telemetry_response(upstream_base, endpoint_path, data_enabled):
        """Forward a constrained telemetry payload to one configured collector endpoint."""
        if not config.rum_enabled or not data_enabled:
            return jsonify({"error": "Telemetry disabled"}), 404

        upstream_url = f"{upstream_base.rstrip('/')}/{endpoint_path.lstrip('/')}"
        if request.query_string:
            upstream_url = f"{upstream_url}?{request.query_string.decode('utf-8')}"

        allowed_headers = {
            "accept",
            "content-encoding",
            "content-type",
            "user-agent",
            "x-requested-with",
        }
        outbound_headers = {
            header: value
            for header, value in request.headers.items()
            if header.lower() in allowed_headers or header.lower().startswith("x-posthog-")
        }

        try:
            upstream_response = requests.request(
                method=request.method,
                url=upstream_url,
                headers=outbound_headers,
                data=request.get_data(),
                allow_redirects=False,
                timeout=(3.05, 15),
            )
        except requests.RequestException:
            logger.exception("Telemetry proxy request failed")
            return jsonify({"error": "Telemetry collector unavailable"}), 503

        response_headers = [
            (header, value)
            for header, value in upstream_response.headers.items()
            if header.lower() in {"cache-control", "content-type", "etag"}
        ]
        return Response(upstream_response.content, status=upstream_response.status_code, headers=response_headers)

    @app.post("/telemetry")
    @limiter.limit("120 per minute")
    def ingest_faro_telemetry():
        """Accept Faro's fixed collect endpoint without exposing a general HTTP proxy."""
        return _telemetry_response(config.rum_faro_upstream, "collect", config.grafana_data_enabled)

    def _posthog_telemetry_upstream(endpoint: str):
        """Return the dedicated PostHog ingestion service for an SDK endpoint."""
        normalized = endpoint.strip("/")
        if normalized in {"e", "i/v0/e"}:
            return config.rum_posthog_capture_upstream, f"{normalized}/"
        if normalized == "s":
            return config.rum_posthog_replay_upstream, "s/"
        if normalized == "flags":
            return config.rum_posthog_feature_flags_upstream, "flags/"
        # Static SDK assets (e.g. the lazy-loaded session-recording recorder)
        # are Django-served files, unlike the array/config endpoint below.
        if normalized.startswith("static/"):
            return config.rum_posthog_upstream, normalized
        return None

    @app.route("/telemetry/posthog/<path:endpoint>", methods=["GET", "POST"])
    @limiter.limit("120 per minute")
    def ingest_posthog_telemetry(endpoint):
        """Forward only the PostHog SDK endpoints required by the browser bundle."""
        if not config.rum_enabled or not config.posthog_data_enabled:
            return jsonify({"error": "Telemetry disabled"}), 404
        normalized = endpoint.strip("/")
        # Self-hosted PostHog's Django app has no route for this SDK asset
        # (it's cloud/CDN-only infrastructure); requests fall through to its
        # login-redirect catch-all. The SDK loads this as a <script> tag and
        # only reads one thing from the resulting global (`sessionRecording`,
        # checked truthy) before it will ever arm the recorder, so synthesize
        # the minimal shape as executable JS rather than proxy to a route
        # that doesn't exist.
        config_match = re.fullmatch(r"array/([^/]+)/config(?:\.js)?", normalized)
        if config_match:
            token = json.dumps(config_match.group(1))
            remote_config = json.dumps({"sessionRecording": {}, "supportedCompression": ["gzip-js"]})
            script = (
                "window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {};"
                f"window._POSTHOG_REMOTE_CONFIG[{token}] = {{config: {remote_config}}};"
            )
            return Response(script, mimetype="application/javascript")
        target = _posthog_telemetry_upstream(endpoint)
        if target is None:
            return jsonify({"error": "Unknown telemetry endpoint"}), 404
        upstream_base, endpoint_path = target
        return _telemetry_response(upstream_base, endpoint_path, config.posthog_data_enabled)

    # Global 401 handler: clear session; redirect browser requests, return JSON for API calls.
    # This dual-mode behavior is intentional (SPA + API usage): browser GETs redirect to login,
    # API/auth calls get JSON so the client can show errors and avoid redirect loops.
    @app.errorhandler(401)
    def handle_unauthorized(e):
        if request.path.startswith("/auth/") and request.method != "GET":
            return jsonify({"error": "Authentication required", "message": "Session expired or not authenticated"}), 401
        accepts_html = "text/html" in (request.headers.get("Accept") or "")
        is_static_asset = request.path.startswith("/static/")
        is_likely_page = (
            request.method == "GET"
            and not request.path.startswith("/api/")
            and not request.path.startswith("/auth/")
            and not is_static_asset
        )
        if accepts_html or is_likely_page:
            return redirect("/", code=302)
        return jsonify({"error": "Authentication required", "message": "Session expired or not authenticated"}), 401

    # Set up middleware
    setup_tenant_context(app)
    setup_session_security(app)
    setup_observability(app)

    # CRITICAL: HTTPS Enforcement - Redirect all HTTP traffic to HTTPS
    # This ensures all connections are encrypted, preventing man-in-the-middle attacks
    @app.before_request
    def force_https():
        """Redirect HTTP requests to HTTPS to ensure encrypted connections"""
        if not app.config.get("ENFORCE_HTTPS", True):
            return
        # Skip for healthcheck and static files
        # CRITICAL: Check if endpoint is None before calling methods on it
        if request.endpoint is None:
            return  # Skip if no endpoint (e.g., Chrome DevTools requests)

        if request.endpoint in ("healthcheck", "static", "serve_ui_shared") or (
            request.endpoint and request.endpoint.endswith(".static")
        ):
            return

        # Check if request is not secure (HTTP instead of HTTPS)
        if not request.is_secure:
            # Check for X-Forwarded-Proto header (used by reverse proxies like nginx)
            if request.headers.get("X-Forwarded-Proto") != "https":
                # Redirect to HTTPS version of the same URL
                url = request.url.replace("http://", "https://", 1)
                return redirect(url, code=301)

    # CRITICAL: Security Headers - Add security headers to all responses
    # These headers protect against various attack vectors (XSS, clickjacking, MIME sniffing, etc.)
    @app.after_request
    def set_security_headers(response):
        """Set security headers on all responses to protect against common attacks"""
        # Prevent MIME type sniffing (forces browsers to respect Content-Type)
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking: DENY by default; SAMEORIGIN for process-docs download and the
        # landing diagram (embedded as an iframe on the landing page).
        path = (request.path or "").strip()
        if ("/api/core/process-docs/" in path and path.rstrip("/").endswith("/download")) or path == "/landing-diagram":
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        else:
            response.headers["X-Frame-Options"] = "DENY"

        # Enable XSS protection in older browsers (modern browsers have better built-in protection)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Content Security Policy - balance security with functionality
        # /landing-diagram is a self-contained bundled app that unpacks base64 assets into blob URLs
        # at runtime, so it needs blob: in script-src, style-src, and font-src.
        if path == "/landing-diagram":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' blob:; "
                "style-src 'self' 'unsafe-inline' blob:; "
                "font-src 'self' blob:; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
                "img-src 'self' data: blob:; "
                "connect-src 'self' blob:"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                # PostHog's vendored session-recording bundle spins up its rrweb
                # compression worker from a data: URI rather than a same-origin
                # script file; without this, browsers silently refuse to create
                # the worker and no recording snapshots are ever captured.
                "worker-src 'self' data: blob:"
            )

        # HSTS (HTTP Strict Transport Security) - Force HTTPS for 1 year
        # This prevents protocol downgrade attacks and cookie hijacking
        # includeSubDomains ensures all subdomains also use HTTPS
        if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response

    # CRITICAL: CSRF Protection - Protect against Cross-Site Request Forgery attacks
    # Flask-WTF validates mutating requests; SPA sends token via X-CSRFToken (see base_spa.html + core-api.js).
    app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken", "X-CSRF-Token"])
    try:
        from flask_wtf.csrf import CSRFProtect

        csrf = CSRFProtect(app)
        # Session-cookie JSON auth API (/auth/*): integration tests and API clients POST JSON without
        # a CSRF header. The SPA may still send X-CSRFToken; exemption only skips validation.
        # SameSite=Strict on the session cookie limits cross-site cookie use in browsers.
        for endpoint, view in app.view_functions.items():
            if endpoint.startswith("auth.") or endpoint in {"ingest_faro_telemetry", "ingest_posthog_telemetry"}:
                csrf.exempt(view)
    except ImportError:
        # Unsafe to run session-backed mutating APIs without CSRF outside local dev / CI test.
        if config.environment not in ("local", "test"):
            raise RuntimeError(
                "Flask-WTF is required in this environment for CSRF protection. Install with: pip install Flask-WTF"
            ) from None
        logger.error(
            "Flask-WTF not installed — CSRF protection disabled (allowed only for local/test). "
            "Install with: pip install Flask-WTF"
        )

        @app.context_processor
        def _csrf_token_placeholder():
            def csrf_token():
                return ""

            return dict(csrf_token=csrf_token)

    @app.context_processor
    def _inject_feature_flags():
        return dict(
            crm_enabled=config.crm_enabled,
            rum_enabled=config.rum_enabled,
            grafana_data_enabled=config.grafana_data_enabled,
            posthog_data_enabled=config.posthog_data_enabled,
            rum_collector_url=config.rum_collector_url,
            rum_sample_rate=config.rum_sample_rate,
            rum_mask_inputs=config.rum_mask_inputs,
            rum_posthog_api_key=config.rum_posthog_api_key,
            rum_user_id=getattr(g, "user_id", None),
            rum_org_id=getattr(g, "org_id", None),
        )

    # Trust Cloudflare's forwarded headers (1 proxy hop)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    return app
