"""Tenant context middleware for multi-tenant support"""

from flask import g, request, session
from uuid import UUID

from app.core.db import db_session
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository


def setup_tenant_context(app):
    """Set up tenant context middleware for the Flask app"""

    @app.before_request
    def load_tenant_context():
        """Load tenant and user context before each request"""
        # Initialize context
        g.current_user = None
        g.current_org = None
        g.current_org_id = None

        db = db_session()

        try:
            # Try to get user_id and org_id from session
            user_id = None
            org_id = None

            if "user_id" in session:
                try:
                    user_id = UUID(session["user_id"])
                except (ValueError, TypeError):
                    pass

            if "org_id" in session:
                try:
                    org_id = UUID(session["org_id"])
                except (ValueError, TypeError):
                    pass

            # Also check for org_id in headers (for API clients)
            if not org_id and "X-Org-Id" in request.headers:
                try:
                    org_id = UUID(request.headers["X-Org-Id"])
                except (ValueError, TypeError):
                    pass

            # Load user if we have user_id
            if user_id:
                user_repo = UserRepository(db)
                user = user_repo.get_user_by_id(user_id, org_id=org_id)

                if user and user.is_active:
                    g.current_user = user
                    g.current_org_id = user.org_id

                    # Load organisation
                    if user.org_id:
                        org_repo = OrganisationRepository(db)
                        org = org_repo.get_org_by_id(user.org_id)
                        if org:
                            g.current_org = org
                            g.current_org_id = org.id

            # If we have org_id but no user (for some public endpoints)
            elif org_id:
                org_repo = OrganisationRepository(db)
                org = org_repo.get_org_by_id(org_id)
                if org:
                    g.current_org = org
                    g.current_org_id = org.id

        except Exception as e:
            # Log error but don't fail the request
            if hasattr(app, "logger"):
                app.logger.error(f"Error loading tenant context: {e}")
            else:
                print(f"Error loading tenant context: {e}")

    @app.teardown_appcontext
    def close_db_session(error):
        """Close database session after request"""
        db_session.remove()

