"""Flask application factory"""

import os

from flask import Flask, jsonify, redirect, request, send_from_directory, session

from app.api.middleware.session_security import setup_session_security
from app.api.middleware.tenant_context import setup_tenant_context
from app.api.routes.auth_routes import auth_bp
from app.api.routes.org_routes import org_bp
from app.core.security.permissions import requires_auth
from app.utils.config_loader import config


def create_app():
    """Create and configure Flask application"""
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
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # Lax: blocks cross-site POST/PUT/DELETE (CSRF) while allowing top-level GET navigations
    app.config["SESSION_COOKIE_PATH"] = "/"  # Explicitly set cookie path to root
    # Align PERMANENT_SESSION_LIFETIME with default user session timeout (7 days default, max 30 days)
    app.config["PERMANENT_SESSION_LIFETIME"] = 30 * 24 * 3600  # 30 days (max session lifetime)

    # Initialize rate limiter (IP-based)
    # Import limiter from auth_routes and initialize it with the app
    from app.api.routes.auth_routes import limiter

    limiter.init_app(app)
    app.limiter = limiter

    # Register multi-tenant blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(org_bp)

    # Register core blueprint
    from app.core.backend.backend import core_bp

    app.register_blueprint(core_bp)

    # Register existing feature blueprints conditionally
    if config.crm_enabled:
        from features.crm.backend.backend import crm_bp

        app.register_blueprint(crm_bp)

    if config.workflow_engine_enabled:
        from features.workflow_engine.backend.backend import workflow_engine_bp

        app.register_blueprint(workflow_engine_bp)

    # Serve shared UI files (JavaScript and CSS) (register before middleware)
    @app.route("/ui/shared/<path:filename>")
    @limiter.exempt
    @requires_auth
    def serve_ui_shared(filename):
        """Serve shared UI files (JavaScript and CSS) - requires authentication"""
        from flask import abort
        from werkzeug.security import safe_join

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
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"Static file not found: {filename} from {shared_dir}")
            abort(404, "File not found")
        except Exception:
            # Unexpected exception - log at exception level
            import logging

            logger = logging.getLogger(__name__)
            logger.exception(f"Unexpected error serving static file: {filename}")
            abort(500, "Internal server error")

    # Global 401 handler: clear session; redirect browser requests, return JSON for API calls.
    # This dual-mode behavior is intentional (SPA + API usage): browser GETs redirect to login,
    # API/auth calls get JSON so the client can show errors and avoid redirect loops.
    @app.errorhandler(401)
    def handle_unauthorized(e):
        session.clear()
        session.modified = True
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

    # CRITICAL: HTTPS Enforcement - Redirect all HTTP traffic to HTTPS
    # This ensures all connections are encrypted, preventing man-in-the-middle attacks
    @app.before_request
    def force_https():
        """Redirect HTTP requests to HTTPS to ensure encrypted connections"""
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

        # Prevent clickjacking: DENY by default; allow SAMEORIGIN only for process-docs download (PDF preview in execution modal)
        path = (request.path or "").strip()
        if "/api/core/process-docs/" in path and path.rstrip("/").endswith("/download"):
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        else:
            response.headers["X-Frame-Options"] = "DENY"

        # Enable XSS protection in older browsers (modern browsers have better built-in protection)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Content Security Policy - balance security with functionality
        # Allow Google Fonts, inline styles, and inline scripts (required for current frontend)
        # Note: For production, consider using nonces for inline scripts instead of 'unsafe-inline'
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
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
            if endpoint.startswith("auth."):
                csrf.exempt(view)
    except ImportError:
        # Unsafe to run session-backed mutating APIs without CSRF outside local dev / CI test.
        import logging

        logger = logging.getLogger(__name__)
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

    return app
