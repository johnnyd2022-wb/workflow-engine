"""Authentication routes"""

import io
import logging
import os
from datetime import datetime, timedelta, timezone
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

# Check if running in CI (GitLab CI sets CI=true and GITLAB_CI=true)
IS_CI = os.getenv("CI", "").lower() == "true" or os.getenv("GITLAB_CI", "").lower() == "true"


# CRITICAL: Custom rate limiting key function that combines IP + email/account
# This prevents attackers from bypassing rate limits by using different IPs
def get_rate_limit_key():
    """Generate rate limit key combining IP address and email/account identifier

    CRITICAL: Combines IP + email to prevent distributed brute force attacks
    This ensures rate limits apply per account, not just per IP
    """
    ip = get_remote_address()
    # Try to get email from request body (for login/signup endpoints)
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
            email = data.get("email", "").lower().strip()
            if email:
                # Combine IP and email for more robust rate limiting
                return f"{ip}:{email}"
    except Exception:
        pass
    # Fallback to IP-only if email not available
    return ip


# Create a limiter instance with custom key function (will be initialized with app in app_factory)
limiter = Limiter(key_func=get_rate_limit_key, default_limits=["200 per day", "50 per hour"])

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
        # CRITICAL: Normalize error messages to prevent user enumeration
        # Always return the same generic message regardless of specific error
        # This prevents attackers from determining if an email or org name exists
        if "already exists" in error_msg.lower():
            # Generic message that doesn't reveal whether email or org exists
            return jsonify({"error": "Cannot complete request. Check credentials or contact support."}), 400
        # For other validation errors, still use generic message
        return jsonify({"error": "Cannot complete request. Check credentials or contact support."}), 400
    except Exception:
        db.rollback()
        logger.exception("Failed to create organisation")
        return jsonify({"error": "Internal server error"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/login", methods=["POST"])
@limiter.limit(
    "1000 per minute" if IS_CI else "5 per 1 minute"
)  # Allow 5 attempts to trigger account lockout, then 6th attempt gets rate limited (higher limit for CI)
def login():
    """Login with email and password

    Rate limited: 5 attempts per 1 minute (allows 5 attempts to trigger account lockout)
    Account lockout: 5 failed attempts → 1 minute lockout
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
        # CRITICAL: Account Lockout - Check if account is locked before authentication
        # Get IP address and User-Agent for logging and security tracking
        ip_address = get_remote_address()
        user_agent = request.headers.get("User-Agent", "Unknown")

        # Check if this is a password reset attempt (unlocks account)
        is_password_reset = data.get("password_reset", False)

        auth_service = AuthService(db)
        org_uuid = UUID(org_id) if org_id else None

        # Try to get user by email first to check lockout status
        # This is done before authentication to check lockout status
        user_repo = UserRepository(db)
        user_by_email = user_repo.get_user_by_email(email, org_id=org_uuid)

        # CRITICAL: Account Lockout Logic
        # If account is locked and this is NOT a password reset, block login
        if user_by_email and not is_password_reset:
            if user_repo.is_account_locked(user_by_email.id):
                # Calculate remaining lockout time
                remaining_seconds = int(
                    (user_by_email.account_locked_until - datetime.now(timezone.utc)).total_seconds()
                )
                remaining_minutes = max(0, remaining_seconds // 60)

                # Log account lockout attempt with IP and User-Agent
                log_action(
                    "account_locked_login_attempt",
                    "user",
                    user_by_email.id,
                    {
                        "ip_address": ip_address,
                        "user_agent": user_agent,
                        "remaining_lockout_minutes": remaining_minutes,
                    },
                    user_by_email.org_id,
                    user_by_email.id,
                )
                logger.warning(
                    f"Login attempt blocked - account locked for user {user_by_email.id} "
                    f"from IP {ip_address} (User-Agent: {user_agent[:50]})"
                )
                return jsonify(
                    {
                        "error": "Account is temporarily locked due to multiple failed login attempts. "
                        f"Please try again in {remaining_minutes + 1} minute(s) or reset your password."
                    }
                ), 423  # 423 Locked status code

        # Normalize authentication to prevent user enumeration
        # Always perform the same operations regardless of whether user exists
        user = auth_service.authenticate(email, password, org_id=org_uuid)

        # CRITICAL: Account Lockout - Handle failed login attempts
        # If authentication failed and user exists, increment failed attempts
        if not user:
            # Log failed login attempt with IP and User-Agent
            # CRITICAL: Never log passwords or sensitive data
            logger.warning(f"Failed login attempt from IP {ip_address} (User-Agent: {user_agent[:50]})")

            # If user exists, track failed attempts for account lockout
            if user_by_email:
                # Increment failed login attempts
                user_repo.increment_failed_login_attempts(user_by_email.id)
                db.commit()

                # Refresh user to get updated failed_login_attempts count
                db.refresh(user_by_email)

                # Lock account after 5 failed attempts for 1 minute
                if user_by_email.failed_login_attempts >= 5:
                    user_repo.lock_account(user_by_email.id, lockout_duration_minutes=1)
                    db.commit()

                    # Log account lockout event with IP and User-Agent
                    log_action(
                        "account_locked",
                        "user",
                        user_by_email.id,
                        {
                            "ip_address": ip_address,
                            "user_agent": user_agent,
                            "failed_attempts": user_by_email.failed_login_attempts,
                        },
                        user_by_email.org_id,
                        user_by_email.id,
                    )
                    logger.warning(
                        f"Account locked for user {user_by_email.id} after 5 failed login attempts "
                        f"from IP {ip_address} (User-Agent: {user_agent[:50]})"
                    )

                # Log failed login attempt with IP and User-Agent
                log_action(
                    "login_failure",
                    "user",
                    user_by_email.id,
                    {
                        "ip_address": ip_address,
                        "user_agent": user_agent,
                        "failed_attempts": user_by_email.failed_login_attempts,
                    },
                    user_by_email.org_id,
                    user_by_email.id,
                )

            # Always return the same error message to prevent user enumeration
            return jsonify({"error": "Cannot complete request. Check credentials or contact support."}), 401

        # CRITICAL: Account Lockout - Reset failed attempts on successful authentication
        # If password reset flag is set, unlock the account
        if is_password_reset:
            user_repo.unlock_account(user.id)
            db.commit()
            logger.info(f"Account unlocked via password reset for user {user.id}")

        # Reset failed login attempts on successful authentication
        user_repo.reset_failed_login_attempts(user.id)
        db.commit()

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

            # CRITICAL: Generate fingerprint from browser characteristics + IP address
            # This combines User-Agent + IP + hashed device ID for robust fingerprinting
            device_fingerprint = None
            if device_fingerprint_data:
                ip_address = get_remote_address()
                device_fingerprint = trusted_device_repo.generate_device_fingerprint(
                    device_fingerprint_data, ip_address
                )
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
                # CRITICAL: Include IP address and User-Agent for security auditing
                log_action(
                    "login",
                    "user",
                    user_id,
                    {"trusted_device": True, "ip_address": ip_address, "user_agent": user_agent},
                    user_org_id,
                    user_id,
                )

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
        # CRITICAL: Include IP address and User-Agent for security auditing
        log_action("login", "user", user.id, {"ip_address": ip_address, "user_agent": user_agent}, user.org_id, user.id)

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

    CRITICAL: session.clear() ensures all authentication state is removed
    This prevents session fixation and ensures clean logout

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

    # CRITICAL: Clear ALL session data on logout to prevent session fixation
    session.clear()
    session.modified = True  # Explicitly mark session as modified to ensure cookie is cleared

    # Do NOT clear trusted device cookie - it should persist across logout/login
    # This allows "Remember this device" to work as expected
    return jsonify({"message": "Logout successful"}), 200


@auth_bp.route("/me", methods=["GET"])
@limiter.limit("120 per minute")  # Higher limit for activity tracking (2 per second max)
def get_current_user():
    """
    Public endpoint.
    Returns authenticated user/org context if logged in.
    Returns user: null when logged out.
    Always HTTP 200.

    Rate limited: 120 per minute (2 per second) to support activity tracking
    while still preventing abuse.
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
@limiter.limit(
    "1000 per minute" if IS_CI else "5 per 5 minutes"
)  # CRITICAL: Rate limit 2FA verification to prevent brute force (higher limit for CI)
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

    # CRITICAL: Validate token format server-side
    # Accept either 6-digit TOTP code or 8-character backup code
    token = token.strip()
    is_totp_code = len(token) == 6 and token.isdigit()
    is_backup_code = len(token) == 8 and token.isalnum()

    if not (is_totp_code or is_backup_code):
        return jsonify({"error": "Invalid code format. Enter a 6-digit TOTP code or 8-character backup code."}), 400

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
        # Extract session_timeout_minutes before any operations that might detach the user object
        user_session_timeout = getattr(user, "session_timeout_minutes", None)

        # Track if backup code was used (for security: don't allow trusted device with backup codes)
        backup_code_used = False
        totp_valid = False

        # Try appropriate verification based on code format
        if is_totp_code:
            # Try TOTP verification for 6-digit codes
            totp_valid = auth_service.verify_totp(user, token)
            if not totp_valid:
                # TOTP failed - log failure
                log_action("2fa_failure", "user", user_id, None, user_org_id, user_id)
                return jsonify({"error": "Invalid 2FA token or backup code"}), 401
        elif is_backup_code:
            # For 8-character codes, try backup code directly
            backup_code_valid = auth_service.verify_backup_code(user_id, token)
            if backup_code_valid:
                backup_code_used = True
                log_action("2fa_backup_code_used", "user", user_id, None, user_org_id, user_id)
            else:
                # Backup code invalid
                log_action("2fa_failure", "user", user_id, None, user_org_id, user_id)
                return jsonify({"error": "Invalid 2FA token or backup code"}), 401
        else:
            # Should not reach here due to validation above, but safety check
            log_action("2fa_failure", "user", user_id, None, user_org_id, user_id)
            return jsonify({"error": "Invalid 2FA token or backup code"}), 401

        # Rotate session ID on successful 2FA verification (session fixation protection)
        # Rotate session (clears everything)
        rotate_session()

        # Now set the authenticated session data
        session_data = auth_service.generate_session(user_id=user_id, user_email=user_email, org_id=user_org_id)
        session.update(session_data)

        # Get user's session timeout preference (use extracted value to avoid detached instance error)
        if user_session_timeout:
            session["session_timeout_minutes"] = user_session_timeout

        # If user wants to remember this device, create a trusted device token
        # Following Google/AWS/Azure patterns: store token in HttpOnly cookie + hash in DB
        # CRITICAL: Include IP address in fingerprint for robust device identification
        # SECURITY: Do NOT allow trusted device creation when using backup codes (one-time use recovery)
        device_token = None
        if remember_device and device_fingerprint_data and not backup_code_used:
            trusted_device_repo = TrustedDeviceRepository(db)
            ip_address = get_remote_address()
            device_fingerprint = trusted_device_repo.generate_device_fingerprint(device_fingerprint_data, ip_address)

            # Check if device already exists (update it) or create new one
            existing_device = trusted_device_repo.get_trusted_device_by_fingerprint(user_id, device_fingerprint)

            if existing_device:
                # Update existing device - extend expiration and update last used
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
        # CRITICAL: Never log the actual token or code
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
            # CRITICAL: Set secure HttpOnly cookie with device token (30 days)
            # Following Google/AWS/Azure patterns: Secure, HttpOnly, SameSite=Lax, Path=/
            # Always use Secure=True (HTTPS is used in both local dev and production)
            is_https = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
            secure_cookie = is_https  # Always secure when HTTPS is detected

            # CRITICAL: Never log the actual token (even partially)
            logger.info(f"Setting trusted device cookie for user {user_id}")
            response.set_cookie(
                "trusted_device_token",
                device_token,
                max_age=30 * 24 * 60 * 60,  # 30 days in seconds
                httponly=True,  # Prevent XSS attacks
                secure=secure_cookie,  # Always secure in production
                samesite="Lax",  # Balance security and usability
                path="/",  # Explicitly set path
            )

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

        # CRITICAL: Check if 2FA is already enabled
        # Refresh user to get latest state from database
        db.refresh(user)
        if user.two_factor_enabled:
            return jsonify({"error": "2FA is already enabled. Disable it first to re-enroll."}), 400

        # CRITICAL: Check if enrollment is in progress (has secret but not enabled)
        # If so, return existing secret instead of creating new one
        if user.totp_secret:
            # Enrollment in progress - return existing secret
            totp = pyotp.TOTP(user.totp_secret)
            provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="WorkflowEngine")

            # Generate QR code from existing secret
            qr = qrcode.QRCode(version=1, box_size=10, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(provisioning_uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="PNG")
            img_buffer.seek(0)
            import base64

            img_base64 = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
            qr_code_data_url = f"data:image/png;base64,{img_base64}"

            return jsonify(
                {"secret": user.totp_secret, "provisioning_uri": provisioning_uri, "qr_code": qr_code_data_url}
            ), 200

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
        # CRITICAL: Never log the secret or QR code data
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

        # CRITICAL: Idempotency check - prevent duplicate enrollment
        # Refresh user to get latest state from database
        db.refresh(user)
        if user.two_factor_enabled:
            return jsonify({"error": "2FA is already enabled. Disable it first to re-enroll."}), 400

        # CRITICAL: Check for existing backup codes and clean them up
        # This handles cases where enrollment was started but not completed
        existing_codes = auth_service.backup_code_repo.get_all_codes_for_user(user.id)
        if existing_codes:
            # Clean up any orphaned backup codes from incomplete enrollment
            # No commit - will be part of the main transaction
            auth_service.delete_backup_codes(user.id, commit=False)

        # Verify first token
        if not auth_service.verify_totp(user, token1):
            # CRITICAL: Never log the actual token
            log_action("2fa_enable_failure", "user", user.id, {"reason": "invalid_first_token"}, user.org_id, user.id)
            db.rollback()
            return jsonify({"error": "Invalid first token"}), 400

        # Verify second token
        if not auth_service.verify_totp(user, token2):
            # CRITICAL: Never log the actual token
            log_action("2fa_enable_failure", "user", user.id, {"reason": "invalid_second_token"}, user.org_id, user.id)
            db.rollback()
            return jsonify({"error": "Invalid second token"}), 400

        # CRITICAL: Wrap enable and code generation in transaction
        # Both operations must succeed together or both must fail
        try:
            # Both tokens verified - enable 2FA
            user_repo.enable_two_factor(user.id)

            # Generate backup codes (10 codes, 8 characters each)
            # CRITICAL: Never log the backup codes
            backup_codes = auth_service.generate_backup_codes(user.id, count=10)

            # Commit transaction atomically
            db.commit()

            # Log enablement (after successful commit)
            # CRITICAL: Never log tokens, secrets, or backup codes
            # CRITICAL: Include IP address and User-Agent for security auditing
            ip_address = get_remote_address()
            user_agent = request.headers.get("User-Agent", "Unknown")
            log_action(
                "2fa_enabled",
                "user",
                user.id,
                {"ip_address": ip_address, "user_agent": user_agent},
                user.org_id,
                user.id,
            )

            # Return backup codes to user (one-time display)
            # CRITICAL: These codes should be displayed once and never logged
            return jsonify({"enabled": True, "backup_codes": backup_codes}), 200

        except Exception:
            # Rollback on any error during enable/code generation
            db.rollback()
            logger.exception("Failed to enable 2FA or generate backup codes")
            raise

    except Exception:
        db.rollback()
        logger.exception("Failed to enable 2FA")
        return jsonify({"error": "Internal server error"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/2fa/disable", methods=["POST"])
@requires_auth
def disable_2fa():
    """Disable two-factor authentication

    CRITICAL: This operation is idempotent and atomic.
    If 2FA is already disabled, returns success without error.
    All operations (delete codes, disable 2FA) are wrapped in a transaction.
    """
    user = g.current_user

    db = db_session()
    try:
        user_repo = UserRepository(db)
        auth_service = AuthService(db)

        # CRITICAL: Idempotency check - refresh user to get latest state
        db.refresh(user)
        if not user.two_factor_enabled:
            # Already disabled - return success (idempotent)
            return jsonify({"disabled": True, "already_disabled": True}), 200

        # CRITICAL: Wrap disable and code deletion in transaction for atomicity
        # Both operations must succeed together or both must fail
        try:
            # Delete all backup codes for this user (no commit - transaction controlled by caller)
            deleted_count = auth_service.backup_code_repo.delete_all_codes_for_user(user.id, commit=False)

            # Disable 2FA
            user_repo.disable_two_factor(user.id)

            # Commit transaction atomically
            db.commit()

            # Log disablement (after successful commit)
            # CRITICAL: Never log sensitive data
            # CRITICAL: Include IP address and User-Agent for security auditing
            ip_address = get_remote_address()
            user_agent = request.headers.get("User-Agent", "Unknown")
            log_action(
                "2fa_disabled",
                "user",
                user.id,
                {"ip_address": ip_address, "user_agent": user_agent, "backup_codes_deleted": deleted_count},
                user.org_id,
                user.id,
            )

            return jsonify({"disabled": True}), 200

        except Exception:
            # Rollback on any error during disable/code deletion
            db.rollback()
            logger.exception("Failed to disable 2FA or delete backup codes")
            raise

    except Exception:
        db.rollback()
        logger.exception("Failed to disable 2FA")
        return jsonify({"error": "Internal server error"}), 500
    # Don't close session here - let middleware teardown handle it


@auth_bp.route("/2fa/cancel", methods=["POST"])
def cancel_2fa():
    """Cancel pending 2FA verification and clear the session

    CRITICAL: session.clear() ensures all authentication state is removed
    This prevents session fixation and ensures clean cancellation

    This endpoint clears any pending_2fa_user_id from the session.
    After calling this, the user must complete the full login flow again
    (email/password + 2FA if enabled).
    """
    # CRITICAL: Clear ALL authentication-related session data
    # Use session.clear() instead of individual pops for complete cleanup
    had_pending = "pending_2fa_user_id" in session
    session.clear()
    session.modified = True  # Explicitly mark session as modified to ensure cookie is cleared

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


@auth_bp.route("/password-policy-check", methods=["POST"])
def check_password_policy():
    """Check password against policy and return warnings (does not block)

    This endpoint provides password policy warnings to help users create stronger passwords.
    It does NOT block users from proceeding - it only provides warnings.
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    password = data.get("password", "")

    if not password:
        return jsonify({"warnings": [], "is_valid": True}), 200

    warnings = []

    # Check password length (warn if < 8 characters)
    if len(password) < 8:
        warnings.append("Password should be at least 8 characters long")

    # Check for uppercase letter
    if not any(c.isupper() for c in password):
        warnings.append("Password should contain at least one uppercase letter")

    # Check for lowercase letter
    if not any(c.islower() for c in password):
        warnings.append("Password should contain at least one lowercase letter")

    # Check for number
    if not any(c.isdigit() for c in password):
        warnings.append("Password should contain at least one number")

    # Check for special character
    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        warnings.append("Password should contain at least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)")

    # Return warnings (user can still proceed)
    return jsonify({"warnings": warnings, "is_valid": len(warnings) == 0}), 200


@auth_bp.route("/change-password", methods=["POST"])
@requires_auth
@limiter.limit("1000 per minute" if IS_CI else "5 per 15 minutes")
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
            # CRITICAL: Never log passwords or sensitive data
            logger.warning(f"Failed password change attempt for user {user.id}")
            return jsonify({"error": "Current password is incorrect"}), 401

        # Hash new password using bcrypt (production-ready)
        new_password_hash = auth_service.hash_password(new_password)

        # Update user password
        updated_user = user_repo.update_user(user_id=user.id, org_id=user.org_id, password_hash=new_password_hash)

        if not updated_user:
            return jsonify({"error": "Failed to update password"}), 500

        # CRITICAL: Clear ALL trusted devices on password change
        # This ensures that if password was compromised, trusted devices are invalidated
        trusted_device_repo = TrustedDeviceRepository(db)
        trusted_device_repo.delete_user_devices(user.id)
        db.commit()

        # CRITICAL: Clear session and force re-authentication after password change
        # This prevents session fixation and ensures user must login again
        session.clear()
        session.modified = True

        # Log password change
        # CRITICAL: Never log passwords
        # CRITICAL: Include IP address and User-Agent for security auditing
        ip_address = get_remote_address()
        user_agent = request.headers.get("User-Agent", "Unknown")
        log_action(
            "password_change",
            "user",
            user.id,
            {"ip_address": ip_address, "user_agent": user_agent},
            user.org_id,
            user.id,
        )

        return jsonify({"message": "Password updated successfully"}), 200

    except Exception:
        logger.exception("Failed to change password")
        return jsonify({"error": "Internal server error"}), 500
    # Don't close session here - let middleware teardown handle it
