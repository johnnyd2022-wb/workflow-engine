"""Organisation routes"""

from flask import Blueprint, request, jsonify, g
from uuid import UUID

from app.core.db import db_session
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.db.models.organisation import OrganisationStatus
from app.core.db.models.user import UserRole
from app.core.security.auth_service import AuthService
from app.core.security.permissions import requires_auth, requires_role, requires_org_scope
from app.core.utils.log_action import log_action

org_bp = Blueprint("org", __name__, url_prefix="/org")


@org_bp.route("", methods=["GET"])
@requires_auth
@requires_org_scope
def get_current_org():
    """Get current organisation"""
    if not g.current_org:
        return jsonify({"error": "Organisation not found"}), 404

    return jsonify({
        "organisation": {
            "id": str(g.current_org.id),
            "name": g.current_org.name,
            "status": g.current_org.status.value,
            "created_at": g.current_org.created_at.isoformat(),
            "updated_at": g.current_org.updated_at.isoformat()
        }
    }), 200


@org_bp.route("", methods=["PATCH"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def update_org():
    """Update current organisation (admin only)"""
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    if not g.current_org:
        return jsonify({"error": "Organisation not found"}), 404

    db = db_session()
    try:
        org_repo = OrganisationRepository(db)

        name = data.get("name")
        status_str = data.get("status")

        status = None
        if status_str:
            try:
                status = OrganisationStatus(status_str)
            except ValueError:
                return jsonify({"error": f"Invalid status: {status_str}"}), 400

        org = org_repo.update_org(g.current_org.id, name=name, status=status)

        if not org:
            return jsonify({"error": "Failed to update organisation"}), 500

        # Log update
        log_action(
            "update",
            "organisation",
            org.id,
            {"name": name, "status": status_str},
            org.id,
            g.current_user.id
        )

        return jsonify({
            "message": "Organisation updated successfully",
            "organisation": {
                "id": str(org.id),
                "name": org.name,
                "status": org.status.value
            }
        }), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Failed to update organisation: {str(e)}"}), 500
    finally:
        db.close()


@org_bp.route("/users", methods=["GET"])
@requires_auth
@requires_org_scope
def list_users():
    """List users in current organisation"""
    db = db_session()
    try:
        user_repo = UserRepository(db)
        users = user_repo.list_users_for_org(g.current_org_id, active_only=False)

        return jsonify({
            "users": [
                {
                    "id": str(user.id),
                    "email": user.email,
                    "role": user.role.value,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat()
                }
                for user in users
            ]
        }), 200

    except Exception as e:
        return jsonify({"error": f"Failed to list users: {str(e)}"}), 500
    finally:
        db.close()


@org_bp.route("/users", methods=["POST"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def create_user():
    """Create a new user in current organisation (admin only)"""
    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    email = data.get("email")
    password = data.get("password")
    role_str = data.get("role", "member")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    db = db_session()
    try:
        user_repo = UserRepository(db)
        auth_service = AuthService(db)

        # Check if user already exists
        existing_user = user_repo.get_user_by_email(email)
        if existing_user:
            return jsonify({"error": f"User with email '{email}' already exists"}), 400

        # Parse role
        try:
            role = UserRole(role_str.lower())
        except ValueError:
            return jsonify({"error": f"Invalid role: {role_str}"}), 400

        # Create user
        password_hash = auth_service.hash_password(password)
        user = user_repo.create_user(
            org_id=g.current_org_id,
            email=email,
            password_hash=password_hash,
            role=role,
            is_active=True
        )

        # Log creation
        log_action("create", "user", user.id, {"email": email, "role": role_str}, g.current_org_id, g.current_user.id)

        return jsonify({
            "message": "User created successfully",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "role": user.role.value,
                "is_active": user.is_active
            }
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Failed to create user: {str(e)}"}), 500
    finally:
        db.close()


@org_bp.route("/users/<user_id>", methods=["DELETE"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def delete_user(user_id: str):
    """Delete a user in current organisation (admin only, soft delete)"""
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        return jsonify({"error": "Invalid user_id"}), 400

    db = db_session()
    try:
        user_repo = UserRepository(db)

        # Ensure user belongs to current org (tenancy enforcement)
        user = user_repo.get_user_by_id(user_uuid, org_id=g.current_org_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Don't allow deleting yourself
        if user.id == g.current_user.id:
            return jsonify({"error": "Cannot delete your own account"}), 400

        # Soft delete
        success = user_repo.delete_user(user_uuid, g.current_org_id)

        if not success:
            return jsonify({"error": "Failed to delete user"}), 500

        # Log deletion
        log_action("delete", "user", user.id, {"email": user.email}, g.current_org_id, g.current_user.id)

        return jsonify({"message": "User deleted successfully"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Failed to delete user: {str(e)}"}), 500
    finally:
        db.close()

