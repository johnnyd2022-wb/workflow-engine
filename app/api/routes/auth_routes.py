"""Authentication routes"""

import io
import logging
from datetime import datetime, timedelta
from uuid import UUID

import pyotp
import qrcode
from flask import Blueprint, current_app, g, jsonify, make_response, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app.api.middleware.session_security import (
    MAX_SESSION_TIMEOUT_MINUTES,
    MIN_SESSION_TIMEOUT_MINUTES,
)
from app.core.db import db_session
from app.core.db.models.trusted_device import TrustedDevice
from app.core.db.repositories.trusted_device_repo import TrustedDeviceRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.core.security.org_manager import OrgManager
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# Create a limiter instance (will be initialized with app in app_factory)
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])

# Pending 2FA session expiry (Using 5 minutes as default)
PENDING_2FA_EXPIRY_MINUTES = 5


def rotate_session():
    """Rotate session ID to prevent session fixation attacks

    This function clears the current session and creates a new one
    by copying non-auth data (if any) and marking as permanent.
    """
    # Store any non-auth session data we want to preserve
    # (Currently we don't preserve anything, but this is extensible)
    preserved_data = {}

    # Clear the session (this invalidates the old session ID)
    session.clear()

    # Mark as permanent for cookie security
    session.permanent = True

    # Restore preserved data if needed
    session.update(preserved_data)


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
    except Exception:
        db.rollback()
        logger.exception("Failed to create organisation")
        return jsonify({"error": "Internal server error"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per 15 minutes")
def login():
    """Login with email and password

    Rate limited: 5 attempts per 15 minutes per IP
    """
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
    session.pop("pending_2fa_created_at", None)
    session.pop("user_id", None)  # Ensure no user_id exists
    session.pop("org_id", None)  # Ensure no org_id exists
    session.pop("user_email", None)
    session.pop("org_name", None)
    session.pop("_user_cache", None)  # Clear any cached user data

    db = db_session()
    try:
        auth_service = AuthService(db)
        org_uuid = UUID(org_id) if org_id else None

        # Normalize authentication to prevent user enumeration
        # Always perform the same operations regardless of whether user exists
        user = auth_service.authenticate(email, password, org_id=org_uuid)

        # Always return the same error message to prevent enumeration
        if not user:
            # Log the attempt (but don't reveal if user exists)
            logger.warning(f"Failed login attempt for email: {email}")
            return jsonify({"error": "Invalid email or password"}), 401

        # Check if 2FA is enabled
        if user.two_factor_enabled:
            # Check for trusted device - following Google/AWS/Azure patterns
            # Verify BOTH token (from cookie) AND fingerprint match
            trusted_device_repo = TrustedDeviceRepository(db)
            device_token = request.cookies.get("trusted_device_token")
            device_fingerprint_data = data.get("device_fingerprint", {})

            # Debug logging
            logger.debug(
                f"Trusted device check - token present: {bool(device_token)}, fingerprint data present: {bool(device_fingerprint_data)}"
            )

            # Generate fingerprint from browser characteristics
            device_fingerprint = None
            if device_fingerprint_data:
                device_fingerprint = trusted_device_repo.generate_device_fingerprint(device_fingerprint_data)
                logger.debug(f"Generated device fingerprint: {device_fingerprint[:16]}...")

            # Verify trusted device: must have BOTH token and fingerprint match
            trusted_device = None
            if device_token and device_fingerprint:
                # Get device by token (hashed)
                trusted_device = trusted_device_repo.get_trusted_device_by_token(device_token)
                logger.debug(f"Found trusted device by token: {bool(trusted_device)}")

                # Verify: token exists, belongs to user, fingerprint matches, not expired
                if trusted_device:
                    logger.debug(
                        f"Verifying device - user_id match: {trusted_device.user_id == user.id}, "
                        f"fingerprint match: {trusted_device.device_fingerprint == device_fingerprint}, "
                        f"expired: {trusted_device.is_expired()}"
                    )
                    if (
                        trusted_device.user_id != user.id
                        or trusted_device.device_fingerprint != device_fingerprint
                        or trusted_device.is_expired()
                    ):
                        # Token or fingerprint mismatch, or expired - don't trust
                        logger.debug("Trusted device verification failed - mismatch or expired")
                        trusted_device = None
                    else:
                        logger.info(f"Trusted device verified for user {user.id} - skipping 2FA")
            elif not device_token:
                logger.debug("No trusted device token in cookie")
            elif not device_fingerprint:
                logger.debug("No device fingerprint data provided")

            if trusted_device:
                # Trusted device verified (both token and fingerprint match) - skip 2FA
                # Extract ALL values while user is still bound to session
                user_id = user.id
                user_org_id = user.org_id
                user_email = user.email
                user_role = user.role.value
                user_session_timeout = getattr(user, "session_timeout_minutes", None)

                trusted_device_repo.update_last_used(trusted_device)
                db.commit()

                # Rotate session ID on successful login (session fixation protection)
                rotate_session()

                # Create session - stores user_id, org_id, user_email, org_name
                session_data = auth_service.generate_session(user_id=user_id, user_email=user_email, org_id=user_org_id)
                session.update(session_data)

                # Get user's session timeout preference
                if user_session_timeout:
                    session["session_timeout_minutes"] = user_session_timeout

                # Log login (with trusted device bypass) - use extracted values
                log_action("login", "user", user_id, {"trusted_device": True}, user_org_id, user_id)

                return jsonify(
                    {
                        "message": "Login successful",
                        "user": {
                            "id": str(user_id),
                            "email": user_email,
                            "role": user_role,
                            "org_id": str(user_org_id),
                        },
                    }
                ), 200

            # No trusted device or expired - require 2FA
            # Do NOT log in yet — return partial auth state
            # CRITICAL: Only set pending_2fa_user_id, NOT user_id
            # User is NOT authenticated until 2FA is verified
            # Explicitly ensure NO authentication session data exists
            session.pop("user_id", None)
            session.pop("org_id", None)
            session.pop("user_email", None)
            session.pop("org_name", None)
            session.pop("_user_cache", None)
            # Set pending 2FA session with timestamp
            session["pending_2fa_user_id"] = str(user.id)
            session["pending_2fa_created_at"] = datetime.utcnow().isoformat()
            return jsonify({"requires_2fa": True}), 200

        # Rotate session ID on successful login (session fixation protection)
        rotate_session()

        # Create session - stores user_id, org_id, user_email, org_name
        session_data = auth_service.generate_session(user)
        session.update(session_data)

        # Extract values before any potential session issues
        user_id = str(user.id)
        user_email = user.email
        user_role = user.role.value
        user_org_id = str(user.org_id)

        # Get user's session timeout preference
        if hasattr(user, "session_timeout_minutes") and user.session_timeout_minutes:
            session["session_timeout_minutes"] = user.session_timeout_minutes

        # Log login
        log_action("login", "user", user.id, None, user.org_id, user.id)

        return jsonify(
            {
                "message": "Login successful",
                "user": {"id": user_id, "email": user_email, "role": user_role, "org_id": user_org_id},
            }
        ), 200

    except ValueError as e:
        logger.warning(f"Invalid org_id in login: {e}")
        return jsonify({"error": "Invalid request"}), 400
    except Exception:
        logger.exception("Login failed")
        return jsonify({"error": "Internal server error"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Logout and clear session

    Note: Trusted device cookies are NOT cleared on logout.
    They persist for 30 days to allow users to skip 2FA on trusted devices.
    Cookies are only cleared when:
    - Device is explicitly revoked by user
    - Device expires (30 days)
    - Password is changed
    - 2FA is disabled
    """
    user_id = session.get("user_id")
    org_id = session.get("org_id")

    # Log logout before clearing session
    if user_id and org_id:
        try:
            log_action("logout", "user", UUID(user_id), None, UUID(org_id), UUID(user_id))
        except Exception:
            pass  # Don't fail logout if logging fails

    session.clear()

    # Do NOT clear trusted device cookie - it should persist across logout/login
    # This allows "Remember this device" to work as expected
    return jsonify({"message": "Logout successful"}), 200


@auth_bp.route("/me", methods=["GET"])
def get_current_user():
    """
    Public endpoint.
    Returns authenticated user/org context if logged in.
    Returns user: null when logged out.
    Always HTTP 200.
    """

    from flask import g, jsonify

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
@limiter.limit("5 per 5 minutes")
def verify_two_factor():
    """Verify TOTP token during login

    IMPORTANT: This endpoint requires a valid pending_2fa_user_id in the session.
    The pending session is set by /auth/login after successful email/password verification.
    If the pending session doesn't exist, the user must start the login process again.

    Rate limited: 5 attempts per 5 minutes per IP
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    token = data.get("token")
    remember_device = data.get("remember_device", False)  # Optional: remember this device for 30 days
    device_fingerprint_data = data.get("device_fingerprint", {})  # Browser characteristics for fingerprinting

    if not token:
        return jsonify({"error": "token is required"}), 400

    # Check for pending 2FA session - if it doesn't exist, user must login again
    pending = session.get("pending_2fa_user_id")
    pending_created_at_str = session.get("pending_2fa_created_at")

    if not pending:
        # Clear any stale session data
        session.pop("pending_2fa_user_id", None)
        session.pop("pending_2fa_created_at", None)
        return jsonify({"error": "No pending 2FA session. Please login again."}), 401

    # Check if pending 2FA session has expired
    if pending_created_at_str:
        try:
            pending_created_at = datetime.fromisoformat(pending_created_at_str)
            time_since_creation = datetime.utcnow() - pending_created_at

            if time_since_creation > timedelta(minutes=PENDING_2FA_EXPIRY_MINUTES):
                # Session expired - clear all auth-related session state
                session.pop("pending_2fa_user_id", None)
                session.pop("pending_2fa_created_at", None)
                session.pop("user_id", None)
                session.pop("org_id", None)
                session.pop("user_email", None)
                session.pop("org_name", None)
                session.pop("_user_cache", None)
                logger.info(f"Pending 2FA session expired for user {pending}")
                return jsonify({"error": "2FA session expired. Please log in again."}), 401
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid pending_2fa_created_at format: {e}")
            # If timestamp is invalid, treat as expired
            session.pop("pending_2fa_user_id", None)
            session.pop("pending_2fa_created_at", None)
            return jsonify({"error": "2FA session expired. Please log in again."}), 401

    db = db_session()
    try:
        user_repo = UserRepository(db)
        auth_service = AuthService(db)

        user = user_repo.get_user_by_id(UUID(pending))
        if not user:
            # User not found - clear pending session
            session.pop("pending_2fa_user_id", None)
            session.pop("pending_2fa_created_at", None)
            logger.warning(f"User not found for pending 2FA: {pending}")
            return jsonify({"error": "Invalid session. Please login again."}), 401

        # Verify user still has 2FA enabled (security check)
        if not user.two_factor_enabled:
            session.pop("pending_2fa_user_id", None)
            session.pop("pending_2fa_created_at", None)
            logger.warning(f"2FA not enabled for user {pending} but pending session exists")
            return jsonify({"error": "Invalid session. Please login again."}), 401

        # Extract ALL values while user is still bound to session
        user_id = user.id
        user_org_id = user.org_id
        user_email = user.email
        user_role = user.role.value

        if not auth_service.verify_totp(user, token):
            # Log 2FA failure - use extracted values
            log_action("2fa_failure", "user", user_id, None, user_org_id, user_id)
            return jsonify({"error": "Invalid 2FA token"}), 401

        # Rotate session ID on successful 2FA verification (session fixation protection)
        # Rotate session (clears everything)
        rotate_session()

        # Now set the authenticated session data
        session_data = auth_service.generate_session(user_id=user_id, user_email=user_email, org_id=user_org_id)
        session.update(session_data)

        # Get user's session timeout preference
        if hasattr(user, "session_timeout_minutes") and user.session_timeout_minutes:
            session["session_timeout_minutes"] = user.session_timeout_minutes

        # If user wants to remember this device, create a trusted device token
        # Following Google/AWS/Azure patterns: store token in HttpOnly cookie + hash in DB
        device_token = None
        if remember_device and device_fingerprint_data:
            trusted_device_repo = TrustedDeviceRepository(db)
            device_fingerprint = trusted_device_repo.generate_device_fingerprint(device_fingerprint_data)

            # Check if device already exists (update it) or create new one
            existing_device = trusted_device_repo.get_trusted_device_by_fingerprint(user_id, device_fingerprint)

            if existing_device:
                # Update existing device - extend expiration and update last used
                from datetime import timezone

                existing_device.expires_at = TrustedDevice.get_expiration_date()
                existing_device.last_used_at = datetime.now(timezone.utc)
                # Get the original token (we need to send it in cookie)
                # Since we store hashed, we need to generate a new token or retrieve from somewhere
                # For now, generate new token and update hash
                device_token = trusted_device_repo.generate_device_token()
                existing_device.device_token = trusted_device_repo.hash_device_token(device_token)
            else:
                # Create new trusted device
                device_token = trusted_device_repo.generate_device_token()
                hashed_token = trusted_device_repo.hash_device_token(device_token)
                expires_at = TrustedDevice.get_expiration_date()
                trusted_device_repo.create_trusted_device(user_id, hashed_token, device_fingerprint, expires_at)

            db.commit()

        # Log successful 2FA verification - use extracted values
        log_action("2fa_success", "user", user_id, {"remember_device": remember_device}, user_org_id, user_id)
        log_action("login", "user", user_id, None, user_org_id, user_id)

        # Create response
        response_data = {
            "message": "Login successful",
            "user": {"id": str(user_id), "email": user_email, "role": user_role, "org_id": str(user_org_id)},
        }

        # Set trusted device cookie if device was remembered
        # Following Google/AWS/Azure patterns: HttpOnly, Secure, SameSite
        response = make_response(jsonify(response_data), 200)

        if device_token:
            # Set secure HttpOnly cookie with device token (30 days)
            # Check if request is HTTPS to determine if cookie should be secure
            # This allows it to work in both local (HTTP) and production (HTTPS)
            is_https = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
            logger.info(f"Setting trusted device cookie for user {user_id} (HTTPS: {is_https})")
            response.set_cookie(
                "trusted_device_token",
                device_token,
                max_age=30 * 24 * 60 * 60,  # 30 days in seconds
                httponly=True,
                secure=is_https,  # Secure only if HTTPS
                samesite="Lax",
                path="/",
            )
            logger.debug(f"Cookie set with token (first 10 chars): {device_token[:10]}...")

        return response

    except ValueError as e:
        logger.warning(f"Invalid user_id in 2FA verification: {e}")
        return jsonify({"error": "Invalid request"}), 400
    except Exception:
        logger.exception("2FA verification failed")
        return jsonify({"error": "Internal server error"}), 500
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

    except Exception:
        logger.exception("Failed to enroll 2FA")
        return jsonify({"error": "Internal server error"}), 500
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

    except Exception:
        logger.exception("Failed to enable 2FA")
        return jsonify({"error": "Internal server error"}), 500
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

    except Exception:
        logger.exception("Failed to disable 2FA")
        return jsonify({"error": "Internal server error"}), 500
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
    session.pop("pending_2fa_created_at", None)
    session.pop("user_id", None)  # Ensure no user_id exists
    session.pop("org_id", None)  # Ensure no org_id exists
    session.pop("user_email", None)
    session.pop("org_name", None)
    session.pop("_user_cache", None)  # Clear any cached user data

    return jsonify({"cancelled": True, "had_pending": had_pending}), 200


@auth_bp.route("/session-timeout", methods=["GET", "PUT"])
@requires_auth
def manage_session_timeout():
    """Get or update user's session timeout preference

    GET: Returns current session timeout in minutes, plus min/max bounds
    PUT: Updates session timeout (min/max from session_security constants)
    """
    user = g.current_user
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    db = db_session()
    try:
        user_repo = UserRepository(db)

        if request.method == "GET":
            # Get current timeout
            timeout = getattr(user, "session_timeout_minutes", 10)
            return jsonify(
                {
                    "session_timeout_minutes": timeout,
                    "min_session_timeout_minutes": MIN_SESSION_TIMEOUT_MINUTES,
                    "max_session_timeout_minutes": MAX_SESSION_TIMEOUT_MINUTES,
                }
            ), 200

        elif request.method == "PUT":
            # Update timeout
            data = request.get_json()
            if not data:
                return jsonify({"error": "JSON body required"}), 400

            timeout_minutes = data.get("session_timeout_minutes")
            if timeout_minutes is None:
                return jsonify({"error": "session_timeout_minutes is required"}), 400

            # Validate bounds using constants from session_security
            if (
                not isinstance(timeout_minutes, int)
                or timeout_minutes < MIN_SESSION_TIMEOUT_MINUTES
                or timeout_minutes > MAX_SESSION_TIMEOUT_MINUTES
            ):
                return jsonify(
                    {
                        "error": f"session_timeout_minutes must be between {MIN_SESSION_TIMEOUT_MINUTES} and {MAX_SESSION_TIMEOUT_MINUTES} minutes"
                    }
                ), 400

            # Update user's session timeout
            updated_user = user_repo.update_session_timeout(user.id, timeout_minutes)
            if not updated_user:
                return jsonify({"error": "Failed to update session timeout"}), 500

            # Update session with new timeout
            session["session_timeout_minutes"] = timeout_minutes

            return jsonify({"session_timeout_minutes": timeout_minutes}), 200

    except Exception:
        logger.exception("Failed to manage session timeout")
        return jsonify({"error": "Internal server error"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/change-password", methods=["POST"])
@requires_auth
@limiter.limit("5 per 15 minutes")
def change_password():
    """Change user password

    Requires authentication and current password verification.
    Rate limited: 5 attempts per 15 minutes per IP.
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    current_password = data.get("current_password")
    new_password = data.get("new_password")
    new_password_confirm = data.get("new_password_confirm")

    if not current_password or not new_password or not new_password_confirm:
        return jsonify({"error": "current_password, new_password, and new_password_confirm are required"}), 400

    # Validate passwords match
    if new_password != new_password_confirm:
        return jsonify({"error": "New passwords do not match"}), 400

    # Ensure new password is different from current
    if current_password == new_password:
        return jsonify({"error": "New password must be different from current password"}), 400

    user = g.current_user
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    db = db_session()
    try:
        auth_service = AuthService(db)
        user_repo = UserRepository(db)

        # Verify current password
        if not auth_service.verify_password(current_password, user.password_hash):
            logger.warning(f"Failed password change attempt for user {user.id} - incorrect current password")
            return jsonify({"error": "Current password is incorrect"}), 401

        # Hash new password using the same method as signup
        new_password_hash = auth_service.hash_password(new_password)

        # Update user password
        updated_user = user_repo.update_user(user_id=user.id, org_id=user.org_id, password_hash=new_password_hash)

        if not updated_user:
            return jsonify({"error": "Failed to update password"}), 500

        # Log password change
        log_action("password_change", "user", user.id, None, user.org_id, user.id)

        return jsonify({"message": "Password updated successfully"}), 200

    except Exception:
        logger.exception("Failed to change password")
        return jsonify({"error": "Internal server error"}), 500
    # Don't close session here - let middleware teardown handle it
