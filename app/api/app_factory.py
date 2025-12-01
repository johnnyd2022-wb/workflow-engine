"""Flask application factory"""

from flask import Flask

from app.utils.config_loader import config
from app.api.middleware.tenant_context import setup_tenant_context
from app.api.routes.auth_routes import auth_bp
from app.api.routes.org_routes import org_bp


def create_app():
    """Create and configure Flask application"""
    app = Flask(__name__)

    # Set secret key for sessions (should be in config in production)
    app.secret_key = config.get("app", "secret_key", fallback="dev-secret-key-change-in-production")

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

    # Set up tenant context middleware
    setup_tenant_context(app)

    return app

