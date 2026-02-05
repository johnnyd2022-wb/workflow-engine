"""
Session security middleware for inactivity timeout and session management.

Design (aligned with big-tech SaaS):
- Secure by default: short default session lifetime (24h); long sessions require explicit user choice.
- Inactivity is always enforced: cookie lifetime != active session; every request checks last_activity_at.
- Long sessions only after explicit user review (settings); no silent weakening of guarantees.

Explicit non-goals (intentionally deferred for current product maturity):
- Trusted device modeling; per-device session lifetimes; admin-enforced org security policies;
  role-based session controls. Session invalidation forces full re-login (2FA required if enabled).
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

# Conservative defaults (Google-style): 24h default; long sessions only with explicit user choice.
DEFAULT_SESSION_TIMEOUT_MINUTES = 24 * 60  # 24 hours
MIN_SESSION_TIMEOUT_MINUTES = 15  # Minimum 15 minutes
MAX_SESSION_TIMEOUT_MINUTES = 30 * 24 * 60  # 30 days max


def setup_session_security(app):
    """Set up session security middleware"""

    @app.before_request
    def check_session_timeout():
        """Check and enforce session inactivity timeout (hard requirement: every authenticated request)."""
        if not request.endpoint:
            return
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint.endswith(".static"):
            return

        user_id = session.get("user_id")
        if not user_id:
            return

        # User's configured timeout (from session cache or database)
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

        timeout_minutes = max(MIN_SESSION_TIMEOUT_MINUTES, min(MAX_SESSION_TIMEOUT_MINUTES, timeout_minutes))

        # Inactivity enforcement: compare last_activity_at to session_timeout_minutes; invalidate if exceeded.
        # Cookie lifetime != session validity; inactivity timeout is authoritative (Google/GitHub-style).
        last_activity_str = session.get("last_activity_at")
        if last_activity_str:
            try:
                last_activity = datetime.fromisoformat(last_activity_str)
                time_since_activity = datetime.utcnow() - last_activity
                if time_since_activity > timedelta(minutes=timeout_minutes):
                    logger.info(f"Session expired due to inactivity for user {user_id}")
                    session.clear()
                    session.modified = True

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

        # Update last activity on every authenticated request (so inactivity window is enforced).
        session["last_activity_at"] = datetime.utcnow().isoformat()
        session.modified = True

    @app.after_request
    def update_session_activity(response):
        """Update last activity after each request so activity is recorded even when the view returns 4xx/5xx."""
        if session.get("user_id"):
            session["last_activity_at"] = datetime.utcnow().isoformat()
            session.modified = True
        return response
