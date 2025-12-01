"""Tenant context middleware for multi-tenant support"""

from uuid import UUID

from flask import abort, g, request, session

from app.core.db import db_session
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository

# Public endpoints that don't require tenant context
# These are full endpoint names as Flask resolves them (blueprint.endpoint)
PUBLIC_ENDPOINTS = {
    "auth.login",
    "auth.signup",
    "healthcheck",  # Health check endpoint (in app.py, not a blueprint)
    "static",  # Flask's application-wide static file handler
}


def setup_tenant_context(app):
    """Set up tenant context middleware for the Flask app"""

    @app.before_request
    def load_tenant_context():
        """Load tenant and user context before each request"""
        # Initialize context
        g.current_user = None
        g.current_org = None
        g.current_org_id = None

        # Skip static files (including blueprint-specific static handlers)
        # Flask can have static handlers like "admin.static", "crm.static", etc.
        if request.endpoint and (request.endpoint.endswith(".static") or request.endpoint == "static"):
            return

        # Skip public endpoints that don't need tenancy
        if request.endpoint in PUBLIC_ENDPOINTS:
            return

        db = db_session()

        try:
            user_id = None
            org_id = None

            # Load user_id from session
            if "user_id" in session:
                try:
                    user_id = UUID(session["user_id"])
                except (ValueError, TypeError):
                    pass

            # Load org_id from session
            if "org_id" in session:
                try:
                    org_id = UUID(session["org_id"])
                except (ValueError, TypeError):
                    pass

            # SECURITY: Only allow X-Org-Id header if NO user is logged in
            # This prevents org_id spoofing when a user is authenticated
            if not user_id and "X-Org-Id" in request.headers:
                try:
                    org_id = UUID(request.headers["X-Org-Id"])
                except (ValueError, TypeError):
                    pass

            # Load user first (without org_id filter for security)
            # Then use the user's actual org_id to prevent spoofing
            if user_id:
                user_repo = UserRepository(db)
                # SECURITY: Load user WITHOUT org_id filter first
                # This ensures we get the user's actual org_id, not a spoofed one
                user = user_repo.get_user_by_id(user_id, org_id=None)

                if user and user.is_active:
                    g.current_user = user
                    # SECURITY: Always use the user's actual org_id, never trust supplied org_id
                    g.current_org_id = user.org_id
                    org_id = user.org_id  # Override any supplied org_id with user's actual org_id
                elif user and not user.is_active:
                    # User exists but is inactive - abort for security
                    if hasattr(app, "logger"):
                        app.logger.warning(f"Inactive user attempted access: {user_id}")
                    abort(403, "Account is inactive")

            # Load organisation if org_id is known
            if org_id:
                org_repo = OrganisationRepository(db)
                org = org_repo.get_org_by_id(org_id)

                if org:
                    g.current_org = org
                    g.current_org_id = org.id
                else:
                    # SECURITY: Abort if org doesn't exist
                    # This prevents processing requests with invalid org_id
                    # and ensures consistent state
                    if hasattr(app, "logger"):
                        app.logger.warning(f"Unknown org_id attempted: {org_id} (user_id: {user_id})")
                    abort(403, "Invalid organisation")

        except Exception as e:
            # Log error and abort for security
            # We don't want to process requests with broken tenant context
            if hasattr(app, "logger"):
                app.logger.error(f"Error loading tenant context: {e}")
            else:
                print(f"Error loading tenant context: {e}")
            abort(500, "Failed to load tenant context")

    @app.teardown_appcontext
    def close_db_session(error):
        """Close database session after request"""
        db_session.remove()
