"""Authentication routes"""

from uuid import UUID

from flask import Blueprint, jsonify, request, session

from app.core.db import db_session
from app.core.security.auth_service import AuthService
from app.core.security.org_manager import OrgManager
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/signup", methods=["POST"])
def signup():
    """Create a new organisation with an admin user"""
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    org_name = data.get("org_name")
    email = data.get("email")
    password = data.get("password")

    if not org_name or not email or not password:
        return jsonify({"error": "org_name, email, and password are required"}), 400

    db = db_session()
    try:
        org_manager = OrgManager(db)
        org, user = org_manager.create_org_with_admin_user(org_name, email, password)

        # Create session - stores user_id, org_id, user_email, org_name
        auth_service = AuthService(db)
        session_data = auth_service.generate_session(user)
        session.update(session_data)

        # Extract values before any potential session issues
        org_id = str(org.id)
        org_name_val = org.name
        org_status = org.status.value
        user_id = str(user.id)
        user_email = user.email
        user_role = user.role.value

        # Log signup
        log_action("signup", "organisation", org.id, {"org_name": org_name}, org.id, user.id)

        return jsonify(
            {
                "message": "Organisation and admin user created successfully",
                "organisation": {"id": org_id, "name": org_name_val, "status": org_status},
                "user": {"id": user_id, "email": user_email, "role": user_role},
            }
        ), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Failed to create organisation: {str(e)}"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/login", methods=["POST"])
def login():
    """Login with email and password"""
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    email = data.get("email")
    password = data.get("password")
    org_id = data.get("org_id")  # Optional: allow specifying org_id

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    db = db_session()
    try:
        auth_service = AuthService(db)
        org_uuid = UUID(org_id) if org_id else None
        user = auth_service.authenticate(email, password, org_id=org_uuid)

        if not user:
            return jsonify({"error": "Invalid email or password"}), 401

        # Create session - stores user_id, org_id, user_email, org_name
        session_data = auth_service.generate_session(user)
        session.update(session_data)

        # Extract values before any potential session issues
        user_id = str(user.id)
        user_email = user.email
        user_role = user.role.value
        user_org_id = str(user.org_id)

        # Log login
        log_action("login", "user", user.id, None, user.org_id, user.id)

        return jsonify(
            {
                "message": "Login successful",
                "user": {"id": user_id, "email": user_email, "role": user_role, "org_id": user_org_id},
            }
        ), 200

    except ValueError as e:
        return jsonify({"error": f"Invalid org_id: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Login failed: {str(e)}"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Logout and clear session"""
    user_id = session.get("user_id")
    org_id = session.get("org_id")

    # Log logout before clearing session
    if user_id and org_id:
        try:
            log_action("logout", "user", UUID(user_id), None, UUID(org_id), UUID(user_id))
        except Exception:
            pass  # Don't fail logout if logging fails

    session.clear()
    return jsonify({"message": "Logout successful"}), 200


@auth_bp.route("/me", methods=["GET"])
@requires_auth
def get_current_user():
    """
    Get current authenticated user.

    Returns ONLY values from flask.g (populated by middleware).
    Uses lightweight session values when available (no DB query).
    Falls back to DB objects only if needed.
    This is the single source of truth for login status.
    """
    from flask import g

    # Prefer lightweight session values (already loaded, no DB query)
    # This makes the endpoint extremely fast
    if hasattr(g, "user_email") and g.user_email:
        # Use lightweight session values - fastest path
        user_email = g.user_email
        user_role = getattr(g, "current_user", None) and g.current_user.role.value or "Unknown"
        user_id = getattr(g, "user_id", None) or (
            str(g.current_user.id) if hasattr(g, "current_user") and g.current_user else None
        )
        user_org_id = getattr(g, "org_id", None) or (
            str(g.current_user.org_id) if hasattr(g, "current_user") and g.current_user else None
        )
        user_is_active = g.current_user.is_active if hasattr(g, "current_user") and g.current_user else True

        org_name = getattr(g, "org_name", None) or (
            g.current_org.name if hasattr(g, "current_org") and g.current_org else "Unknown"
        )
        org_status = g.current_org.status.value if hasattr(g, "current_org") and g.current_org else "Unknown"
        org_id = getattr(g, "org_id", None) or (
            str(g.current_org.id) if hasattr(g, "current_org") and g.current_org else None
        )

        org_data = None
        if org_id:
            org_data = {"id": org_id, "name": org_name, "status": org_status}

        return jsonify(
            {
                "user": {
                    "id": user_id,
                    "email": user_email,
                    "role": user_role,
                    "org_id": user_org_id,
                    "is_active": user_is_active,
                },
                "organisation": org_data,
            }
        ), 200

    # Fallback to DB objects if session values not available
    if not g.current_user:
        return jsonify({"error": "Not authenticated"}), 401

    # Extract values while objects are still bound to session
    # This prevents "detached instance" errors
    user_id = str(g.current_user.id)
    user_email = g.current_user.email
    user_role = g.current_user.role.value
    user_org_id = str(g.current_user.org_id)
    user_is_active = g.current_user.is_active

    org_data = None
    if g.current_org:
        org_id = str(g.current_org.id)
        org_name = g.current_org.name
        org_status = g.current_org.status.value
        org_data = {"id": org_id, "name": org_name, "status": org_status}

    return jsonify(
        {
            "user": {
                "id": user_id,
                "email": user_email,
                "role": user_role,
                "org_id": user_org_id,
                "is_active": user_is_active,
            },
            "organisation": org_data,
        }
    ), 200
