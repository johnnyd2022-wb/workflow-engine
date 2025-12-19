"""Flask application factory"""

from flask import Flask

from app.api.middleware.session_security import setup_session_security
from app.api.middleware.tenant_context import setup_tenant_context
from app.api.routes.auth_routes import auth_bp
from app.api.routes.org_routes import org_bp
from app.utils.config_loader import config


def create_app():
    """Create and configure Flask application"""
    app = Flask(__name__)

    # Set secret key for sessions (should be in config in production)
    app.secret_key = config.get("app", "secret_key", fallback="dev-secret-key-change-in-production")

    # Configure session cookies for production security
    app.config["SESSION_COOKIE_SECURE"] = config.getboolean("app", "session_cookie_secure", fallback=True)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 hours (max session lifetime)

    # Initialize rate limiter (IP-based)
    # Import limiter from auth_routes and initialize it with the app
    from app.api.routes.auth_routes import limiter

    limiter.init_app(app)
    app.limiter = limiter

    # Register multi-tenant blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(org_bp)

    # Register existing feature blueprints conditionally
    if config.crm_enabled:
        from features.crm.backend.backend import crm_bp

        app.register_blueprint(crm_bp)

    if config.workflow_engine_enabled:
        from features.workflow_engine.backend.backend import workflow_engine_bp

        app.register_blueprint(workflow_engine_bp)

    # Set up middleware
    setup_tenant_context(app)
    setup_session_security(app)

    return app
