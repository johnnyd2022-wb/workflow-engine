"""Authentication routes"""

import io
from uuid import UUID

import pyotp
import qrcode
from flask import Blueprint, g, jsonify, request, session

from app.core.db import db_session
from app.core.db.repositories.user_repo import UserRepository
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
    password_confirm = data.get("password_confirm")

    if not org_name or not email or not password or not password_confirm:
        return jsonify({"error": "org_name, email, password, and password_confirm are required"}), 400

    if password != password_confirm:
        return jsonify({"error": "Passwords do not match"}), 400

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
        error_msg = str(e)
        # Provide more helpful messages for common signup errors
        if "already exists" in error_msg.lower() and "organisation" in error_msg.lower():
            return jsonify(
                {
                    "error": "An organization with this name already exists. If you're part of this organization, please contact your administrator for access or try logging in instead."
                }
            ), 400
        elif "already exists" in error_msg.lower() and "user" in error_msg.lower() and "email" in error_msg.lower():
            return jsonify(
                {
                    "error": "An account with this email already exists. Please try logging in instead, or use a different email address."
                }
            ), 400
        return jsonify({"error": error_msg}), 400
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

    # CRITICAL: Clear ALL authentication-related session data before starting new login
    # This ensures no stale partial authentication state persists
    # Only keep non-auth session data (if any)
    session.pop("pending_2fa_user_id", None)
    session.pop("user_id", None)  # Ensure no user_id exists
    session.pop("org_id", None)  # Ensure no org_id exists
    session.pop("user_email", None)
    session.pop("org_name", None)
    session.pop("_user_cache", None)  # Clear any cached user data

    db = db_session()
    try:
        auth_service = AuthService(db)
        org_uuid = UUID(org_id) if org_id else None
        user = auth_service.authenticate(email, password, org_id=org_uuid)

        if not user:
            return jsonify({"error": "Invalid email or password"}), 401

        # Check if 2FA is enabled
        if user.two_factor_enabled:
            # Do NOT log in yet — return partial auth state
            # CRITICAL: Only set pending_2fa_user_id, NOT user_id
            # User is NOT authenticated until 2FA is verified
            # Explicitly ensure NO authentication session data exists
            session.pop("user_id", None)
            session.pop("org_id", None)
            session.pop("user_email", None)
            session.pop("org_name", None)
            session.pop("_user_cache", None)
            # Only set pending_2fa_user_id
            session["pending_2fa_user_id"] = str(user.id)
            return jsonify({"requires_2fa": True}), 200

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
def get_current_user():
    """
    Public endpoint.
    Returns authenticated user/org context if logged in.
    Returns user: null when logged out.
    Always HTTP 200.
    """

    from flask import current_app, g, jsonify

    # Log user info for debugging (optional: remove or mask IDs in production)
    if g.user_id:
        current_app.logger.debug(f"/auth/me called by user_id={g.user_id}, org_id={g.org_id}")

    # Logged-out state
    if not g.user_id:
        return jsonify({"user": None, "organisation": None}), 200

    # Logged-in state
    user = {
        "id": g.user_id,
        "email": g.user_email,
        "role": g.user_role,
        "org_id": g.org_id,
        "is_active": g.current_user.is_active if g.current_user else True,
        "two_factor_enabled": g.current_user.two_factor_enabled if g.current_user else False,
    }

    org = (
        {
            "id": g.org_id,
            "name": g.org_name,
            "status": g.org_status,
        }
        if g.org_id
        else None
    )

    return jsonify({"user": user, "organisation": org}), 200


@auth_bp.route("/verify-2fa", methods=["POST"])
def verify_two_factor():
    """Verify TOTP token during login

    IMPORTANT: This endpoint requires a valid pending_2fa_user_id in the session.
    The pending session is set by /auth/login after successful email/password verification.
    If the pending session doesn't exist, the user must start the login process again.
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    token = data.get("token")
    if not token:
        return jsonify({"error": "token is required"}), 400

    # Check for pending 2FA session - if it doesn't exist, user must login again
    pending = session.get("pending_2fa_user_id")
    if not pending:
        # Clear any stale session data
        session.pop("pending_2fa_user_id", None)
        return jsonify({"error": "No pending 2FA session. Please login again."}), 401

    db = db_session()
    try:
        user_repo = UserRepository(db)
        auth_service = AuthService(db)

        user = user_repo.get_user_by_id(UUID(pending))
        if not user:
            # User not found - clear pending session
            session.pop("pending_2fa_user_id", None)
            return jsonify({"error": "User not found"}), 404

        # Verify user still has 2FA enabled (security check)
        if not user.two_factor_enabled:
            session.pop("pending_2fa_user_id", None)
            return jsonify({"error": "2FA is not enabled for this account"}), 400

        # Extract ALL values while user is still bound to session
        user_id = user.id
        user_org_id = user.org_id
        user_email = user.email
        user_role = user.role.value

        if not auth_service.verify_totp(user, token):
            # Log 2FA failure - use extracted values
            log_action("2fa_failure", "user", user_id, None, user_org_id, user_id)
            return jsonify({"error": "Invalid 2FA token"}), 401

        # Complete login - use extracted values to avoid session issues
        # CRITICAL: Only set user_id AFTER successful 2FA verification
        # Clear any existing auth data first (defensive)
        session.pop("user_id", None)
        session.pop("org_id", None)
        session.pop("user_email", None)
        session.pop("org_name", None)
        session.pop("_user_cache", None)

        # Now set the authenticated session data
        session_data = auth_service.generate_session(user_id=user_id, user_email=user_email, org_id=user_org_id)
        session.update(session_data)
        session.pop("pending_2fa_user_id", None)

        # Log successful 2FA verification - use extracted values
        log_action("2fa_success", "user", user_id, None, user_org_id, user_id)
        log_action("login", "user", user_id, None, user_org_id, user_id)

        return jsonify(
            {
                "message": "Login successful",
                "user": {"id": str(user_id), "email": user_email, "role": user_role, "org_id": str(user_org_id)},
            }
        ), 200

    except ValueError as e:
        return jsonify({"error": f"Invalid user_id: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"2FA verification failed: {str(e)}"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/2fa/enroll", methods=["POST"])
@requires_auth
def enroll_2fa():
    """Generate a new TOTP secret and QR code image for enrollment"""
    user = g.current_user

    db = db_session()
    try:
        user_repo = UserRepository(db)

        new_secret = pyotp.random_base32()
        user_repo.set_totp_secret(user.id, new_secret)

        totp = pyotp.TOTP(new_secret)
        provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="WorkflowEngine")

        # Generate QR code image
        qr = qrcode.QRCode(version=1, box_size=10, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        img_buffer = io.BytesIO()
        img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        import base64

        img_base64 = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
        qr_code_data_url = f"data:image/png;base64,{img_base64}"

        # Log enrollment
        log_action("2fa_enrolled", "user", user.id, None, user.org_id, user.id)

        return jsonify({"secret": new_secret, "provisioning_uri": provisioning_uri, "qr_code": qr_code_data_url}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to enroll 2FA: {str(e)}"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/2fa/enable", methods=["POST"])
@requires_auth
def enable_2fa():
    """Enable two-factor authentication after verifying two consecutive tokens

    Requires two valid TOTP tokens to ensure:
    1. The authenticator app is properly configured
    2. The device clock is synchronized
    3. The user can successfully generate codes
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    token1 = data.get("token1")
    token2 = data.get("token2")

    if not token1:
        return jsonify({"error": "First token is required"}), 400

    if not token2:
        return jsonify({"error": "Second token is required"}), 400

    # Ensure tokens are different
    if token1 == token2:
        return jsonify({"error": "Second token must be different from the first"}), 400

    user = g.current_user

    db = db_session()
    try:
        auth_service = AuthService(db)
        user_repo = UserRepository(db)

        # Verify first token
        if not auth_service.verify_totp(user, token1):
            log_action("2fa_enable_failure", "user", user.id, {"reason": "invalid_first_token"}, user.org_id, user.id)
            return jsonify({"error": "Invalid first token"}), 400

        # Verify second token
        if not auth_service.verify_totp(user, token2):
            log_action("2fa_enable_failure", "user", user.id, {"reason": "invalid_second_token"}, user.org_id, user.id)
            return jsonify({"error": "Invalid second token"}), 400

        # Both tokens verified - enable 2FA
        user_repo.enable_two_factor(user.id)

        # Log enablement
        log_action("2fa_enabled", "user", user.id, None, user.org_id, user.id)

        return jsonify({"enabled": True}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to enable 2FA: {str(e)}"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/2fa/disable", methods=["POST"])
@requires_auth
def disable_2fa():
    """Disable two-factor authentication"""
    user = g.current_user

    db = db_session()
    try:
        user_repo = UserRepository(db)
        user_repo.disable_two_factor(user.id)

        # Log disablement
        log_action("2fa_disabled", "user", user.id, None, user.org_id, user.id)

        return jsonify({"disabled": True}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to disable 2FA: {str(e)}"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/2fa/cancel", methods=["POST"])
def cancel_2fa():
    """Cancel pending 2FA verification and clear the session

    This endpoint clears any pending_2fa_user_id from the session.
    After calling this, the user must complete the full login flow again
    (email/password + 2FA if enabled).
    """
    # Clear ALL authentication-related session data
    had_pending = "pending_2fa_user_id" in session
    session.pop("pending_2fa_user_id", None)
    session.pop("user_id", None)  # Ensure no user_id exists
    session.pop("org_id", None)  # Ensure no org_id exists
    session.pop("user_email", None)
    session.pop("org_name", None)
    session.pop("_user_cache", None)  # Clear any cached user data

    return jsonify({"cancelled": True, "had_pending": had_pending}), 200
