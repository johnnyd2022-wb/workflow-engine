"""
Session security middleware for inactivity timeout and session management.

Implements:
- Inactivity-based session timeout (default 10 minutes, user-configurable)
- Session activity tracking (last_activity_at)
- Automatic session expiry on inactivity
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from flask import g, make_response, request, session

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
                        from flask import Response

                        html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Session Expired</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(8px);
            z-index: 2000;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .modal-content {
            background: rgba(30, 30, 30, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 1rem;
            padding: 2rem;
            max-width: 28rem;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        .icon {
            width: 64px;
            height: 64px;
            margin: 0 auto 1rem;
            background: rgba(239, 68, 68, 0.2);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        h2 {
            margin: 0 0 0.5rem 0;
            font-size: 1.5rem;
            font-weight: 600;
        }
        p {
            margin: 0 0 1rem 0;
            color: #999;
        }
        .countdown {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            color: #999;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="modal-overlay">
        <div class="modal-content">
            <div class="icon">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
            </div>
            <h2>Session Expired</h2>
            <p>Your session has expired due to inactivity. You will be redirected to the Sign In screen.</p>
            <div class="countdown">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span id="countdown">Redirecting in 3 seconds...</span>
            </div>
        </div>
    </div>
    <script>
        let seconds = 3;
        const countdownEl = document.getElementById('countdown');
        const timer = setInterval(() => {
            seconds--;
            if (seconds > 0) {
                countdownEl.textContent = 'Redirecting in ' + seconds + ' second' + (seconds !== 1 ? 's' : '') + '...';
            } else {
                clearInterval(timer);
                countdownEl.textContent = 'Redirecting now...';
                setTimeout(() => {
                    window.location.href = '/';
                }, 300);
            }
        }, 1000);
    </script>
</body>
</html>
                        """
                        return Response(html_content, mimetype="text/html", status=401)
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
