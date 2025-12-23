"""
Session security middleware for inactivity timeout and session management.

Implements:
- Inactivity-based session timeout (default 10 minutes, user-configurable)
- Session activity tracking (last_activity_at)
- Automatic session expiry on inactivity
"""

import logging
import os
from datetime import datetime, timedelta
from uuid import UUID

from flask import g, make_response, render_template_string, request, session

from app.api.middleware.tenant_context import PUBLIC_ENDPOINTS
from app.core.db import db_session
from app.core.db.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

# Default inactivity timeout (10 minutes)
DEFAULT_SESSION_TIMEOUT_MINUTES = 10
MIN_SESSION_TIMEOUT_MINUTES = 1
MAX_SESSION_TIMEOUT_MINUTES = 240


def setup_session_security(app):
    """Set up session security middleware"""

    @app.before_request
    def check_session_timeout():
        """Check and enforce session inactivity timeout"""
        # Skip for public endpoints
        if not request.endpoint:
            return

        # Use PUBLIC_ENDPOINTS from tenant_context to avoid duplication
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint.endswith(".static"):
            return

        # Check if user is authenticated
        user_id = session.get("user_id")
        if not user_id:
            return

        # Get user's configured timeout from session, or load from database
        timeout_minutes = session.get("session_timeout_minutes")
        if timeout_minutes is None:
            # Try to get from g.current_user first (loaded by tenant_context middleware)
            if hasattr(g, "current_user") and g.current_user and hasattr(g.current_user, "session_timeout_minutes"):
                timeout_minutes = g.current_user.session_timeout_minutes
                # Cache in session for performance
                session["session_timeout_minutes"] = timeout_minutes
            else:
                # Load from database if not in g
                try:
                    db = db_session()
                    user_repo = UserRepository(db)
                    user = user_repo.get_user_by_id(UUID(user_id))
                    if user and hasattr(user, "session_timeout_minutes"):
                        timeout_minutes = user.session_timeout_minutes
                        # Cache in session for performance
                        session["session_timeout_minutes"] = timeout_minutes
                    else:
                        timeout_minutes = DEFAULT_SESSION_TIMEOUT_MINUTES
                except Exception as e:
                    logger.warning(f"Failed to load user session timeout: {e}")
                    timeout_minutes = DEFAULT_SESSION_TIMEOUT_MINUTES

        # Ensure timeout is within bounds
        timeout_minutes = max(MIN_SESSION_TIMEOUT_MINUTES, min(MAX_SESSION_TIMEOUT_MINUTES, timeout_minutes))

        # Check last activity
        last_activity_str = session.get("last_activity_at")
        if last_activity_str:
            try:
                last_activity = datetime.fromisoformat(last_activity_str)
                time_since_activity = datetime.utcnow() - last_activity

                # Check if timeout exceeded
                if time_since_activity > timedelta(minutes=timeout_minutes):
                    # Session expired due to inactivity
                    logger.info(f"Session expired due to inactivity for user {user_id}")
                    session.clear()

                    # Check if this is an HTML page request (not an API call)
                    # If Accept header includes text/html, or if it's a page route, redirect to login
                    accepts_html = request.headers.get("Accept", "").find("text/html") != -1
                    is_page_route = not request.path.startswith("/auth/") and not request.path.startswith("/api/")

                    if accepts_html or is_page_route:
                        # For HTML page requests, return a response that shows modal then redirects
                        # This prevents the immediate redirect and allows modal to show first
                        # Load the session expired template
                        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        template_path = os.path.join(app_dir, "ui", "templates", "session_expired.html")

                        with open(template_path, encoding="utf-8") as f:
                            template_content = f.read()

                        return render_template_string(template_content), 401
                    else:
                        # For API requests, return JSON 401 so frontend can show modal
                        from flask import jsonify

                        response = make_response(jsonify({"error": "Session expired due to inactivity"}), 401)
                        return response

            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid last_activity_at format: {e}")
                # Reset on invalid format
                session["last_activity_at"] = datetime.utcnow().isoformat()

        # Update last activity timestamp
        session["last_activity_at"] = datetime.utcnow().isoformat()

    @app.after_request
    def update_session_activity(response):
        """Update session activity after each request"""
        # Only update for authenticated requests
        if session.get("user_id"):
            session["last_activity_at"] = datetime.utcnow().isoformat()
        return response
