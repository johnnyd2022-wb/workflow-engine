"""Organisation routes"""

import secrets
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request

from app.core.db import db_session
from app.core.db.models.org_role import OrgRole
from app.core.db.models.organisation import OrganisationStatus
from app.core.db.models.site import Site
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import EmailConflictError, UserRepository
from app.core.security.auth_service import AuthService
from app.core.security.people import (
    PeopleError,
    check_change,
    invite_is_pending,
    issue_invite,
    parse_access_expiry,
    parse_role_choice,
    permission_catalogue,
    role_options,
    role_value,
    serialize_person,
    validate_custom_role,
    validate_new_password,
)
from app.core.security.permissions import requires_auth, requires_org_scope, requires_role
from app.core.security.staff_site_roles import (
    lock_role_administration,
    replace_site_config,
    role_site_ids,
    validate_site_config,
)
from app.core.utils.emit_event import emit_event
from app.core.utils.log_action import log_action
from app.observability import get_logger

logger = get_logger(__name__)

org_bp = Blueprint("org", __name__, url_prefix="/org")

# The People page lives with the org API (identity stays in app/api/routes per the
# feature-slicing plan). It extends the Core shell, so it reads Core's templates.
people_pages = Blueprint("people_pages", __name__, template_folder="../../core/frontend")


@people_pages.route("/core/people", methods=["GET"])
@requires_auth
def people_page():
    return render_template("people/people.html", active_page="settings")


@org_bp.route("", methods=["GET"])
@requires_auth
@requires_org_scope
def get_current_org():
    """Get current organisation"""
    if not g.current_org:
        return jsonify({"error": "Organisation not found"}), 404

    return jsonify(
        {
            "organisation": {
                "id": str(g.current_org.id),
                "name": g.current_org.name,
                "status": g.current_org.status.value,
                "created_at": g.current_org.created_at.isoformat(),
                "updated_at": g.current_org.updated_at.isoformat(),
            }
        }
    ), 200


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

        # Capture before-state for diff
        before_name = g.current_org.name
        before_status = g.current_org.status.value if g.current_org.status else None

        org = org_repo.update_org(g.current_org.id, name=name, status=status)

        if not org:
            return jsonify({"error": "Failed to update organisation"}), 500

        # Extract values immediately after update (while object is still bound to session)
        org_id = str(org.id)
        org_name_val = org.name
        org_status = org.status.value

        # Log update (using extracted values)
        log_action("update", "organisation", org.id, {"name": name, "status": status_str}, org.id, g.current_user.id)

        # Emit audit event
        diff: dict = {}
        if name is not None and name != before_name:
            diff["name"] = {"before": before_name, "after": org_name_val}
        if status is not None and org_status != before_status:
            diff["status"] = {"before": before_status, "after": org_status}
        if diff:
            actor_id = UUID(g.user_id) if getattr(g, "user_id", None) else None
            emit_event(
                event_type="org.settings_updated",
                entity_type="org",
                entity_id=org.id,
                payload={"name": org_name_val, "status": org_status},
                org_id=org.id,
                actor_id=actor_id,
                actor_label=getattr(g, "user_email", None),
                diff=diff,
            )

        return jsonify(
            {
                "message": "Organisation updated successfully",
                "organisation": {"id": org_id, "name": org_name_val, "status": org_status},
            }
        ), 200

    except Exception:
        db.rollback()
        logger.exception("Error updating organisation")
        return jsonify({"error": "Failed to update organisation"}), 500
    # Don't close session here - let middleware teardown handle it


@org_bp.route("/users", methods=["GET"])
@requires_auth
@requires_org_scope
def list_users():
    """People in this organisation. Every role can read it (assignee pickers); roles,
    invite status and 2FA state are what the People page shows admins."""
    db = db_session()
    try:
        users = UserRepository(db).list_users_for_org(g.current_org_id, active_only=False)
        people = sorted((serialize_person(u) for u in users), key=lambda p: p["display_name"].lower())
        return jsonify({"users": people, "roles": role_options(_custom_roles(db))}), 200
    except Exception:
        logger.exception("Error listing users")
        return jsonify({"error": "Failed to list users"}), 500


def _invite_url(token: str) -> str:
    return request.host_url.rstrip("/") + "/invite/" + token


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


@org_bp.route("/users", methods=["POST"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def create_user():
    """Add a person (admin only).

    Without a password this sends back a one-time invite link (valid 7 days) for the admin
    to pass on; the person sets their own password. With a password (the scripted path the
    Whistlebird replay and tests use) the account is active straight away.
    """
    data = _json_body()
    if data is None:
        return jsonify({"error": "JSON body required"}), 400

    email = (data.get("email") or "").strip().lower()
    password = data.get("password")
    if not email:
        return jsonify({"error": "email is required"}), 400

    db = db_session()
    try:
        lock_role_administration(db, g.current_org_id)
        role, custom = parse_role_choice(data.get("role", "member"), _custom_roles(db))
        expires = parse_access_expiry(data.get("access_expires_at"), role)
        if password:
            validate_new_password(password)

        user_repo = UserRepository(db)
        # An invited person stays inactive, with an unusable password, until they accept.
        secret = password or secrets.token_urlsafe(48)
        try:
            user = user_repo.create_user(
                org_id=g.current_org_id,
                email=email,
                password_hash=AuthService.hash_password(secret),
                role=role,
                is_active=bool(password),
                first_name=(data.get("first_name") or "").strip() or None,
                last_name=(data.get("last_name") or "").strip() or None,
            )
        except EmailConflictError as e:
            db.rollback()
            return jsonify({"error": str(e)}), 400

        user.access_expires_at = expires
        user.custom_role_id = custom.id if custom is not None else None
        token = None if password else issue_invite(user)
        db.commit()

        log_action(
            "create",
            "user",
            user.id,
            {"email": email, "role": role_value(user), "invited": token is not None},
            g.current_org_id,
            g.current_user.id,
        )
        body = {"message": "User created successfully", "user": serialize_person(user)}
        if token:
            body["invite_url"] = _invite_url(token)
        return jsonify(body), 201

    except PeopleError as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception:
        db.rollback()
        logger.exception("Error creating user")
        return jsonify({"error": "Failed to create user"}), 500


def _parse_user_id(user_id: str) -> UUID | None:
    try:
        return UUID(user_id)
    except ValueError:
        return None


def _load_target(db, user_uuid: UUID):
    return UserRepository(db).get_user_by_id(user_uuid, org_id=g.current_org_id)


@org_bp.route("/users/<user_id>", methods=["PATCH"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def update_user(user_id: str):
    """Change someone's role, access end date, or active state (admin only)."""
    data = _json_body()
    if data is None:
        return jsonify({"error": "JSON body required"}), 400

    user_uuid = _parse_user_id(user_id)
    if user_uuid is None:
        return jsonify({"error": "Invalid user_id"}), 400

    db = db_session()
    try:
        lock_role_administration(db, g.current_org_id)
        target = _load_target(db, user_uuid)
        if not target:
            return jsonify({"error": "User not found"}), 404

        role, custom = parse_role_choice(data["role"], _custom_roles(db)) if "role" in data else (None, None)
        if "role" in data and target.id == g.current_user.id and str(data["role"]).strip() != role_value(target):
            raise PeopleError("You can't change your own role. Ask another admin.")
        is_active = data.get("is_active") if "is_active" in data else None
        if is_active is not None and not isinstance(is_active, bool):
            return jsonify({"error": "is_active must be true or false"}), 400
        if is_active is True and invite_is_pending(target):
            return jsonify({"error": "This person hasn't accepted their invite yet."}), 400

        org_users = UserRepository(db).list_users_for_org(g.current_org_id)
        check_change(g.current_user, target, org_users, role=role, is_active=is_active)

        effective_role = role or target.role
        before = {
            "role": role_value(target),
            "is_active": target.is_active,
            "access_expires_at": target.access_expires_at.isoformat() if target.access_expires_at else None,
        }
        if "access_expires_at" in data or (role == UserRole.AUDITOR and target.role != UserRole.AUDITOR):
            target.access_expires_at = parse_access_expiry(data.get("access_expires_at"), effective_role)
        if role is not None:
            target.role = role
            target.custom_role_id = custom.id if custom is not None else None
        if is_active is not None:
            target.is_active = is_active
        db.commit()

        after = serialize_person(target)
        log_action(
            "update",
            "user",
            target.id,
            {"before": before, "after": {k: after[k] for k in before}},
            g.current_org_id,
            g.current_user.id,
        )
        return jsonify({"user": after}), 200

    except PeopleError as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception:
        db.rollback()
        logger.exception("Error updating user")
        return jsonify({"error": "Failed to update user"}), 500


@org_bp.route("/users/<user_id>/invite", methods=["POST"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def reissue_invite(user_id: str):
    """A new invite link for someone who hasn't accepted yet; the old link stops working."""
    user_uuid = _parse_user_id(user_id)
    if user_uuid is None:
        return jsonify({"error": "Invalid user_id"}), 400

    db = db_session()
    try:
        lock_role_administration(db, g.current_org_id)
        target = _load_target(db, user_uuid)
        if not target:
            return jsonify({"error": "User not found"}), 404
        if target.is_active:
            return jsonify({"error": "This person has already set up their account."}), 400
        token = issue_invite(target)
        db.commit()
        log_action("reissue_invite", "user", target.id, {"email": target.email}, g.current_org_id, g.current_user.id)
        return jsonify({"user": serialize_person(target), "invite_url": _invite_url(token)}), 200
    except Exception:
        db.rollback()
        logger.exception("Error reissuing invite")
        return jsonify({"error": "Failed to create a new invite link"}), 500


@org_bp.route("/users/<user_id>", methods=["DELETE"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def delete_user(user_id: str):
    """Deactivate a person (admin only). History is kept; they can't sign in."""
    user_uuid = _parse_user_id(user_id)
    if user_uuid is None:
        return jsonify({"error": "Invalid user_id"}), 400

    db = db_session()
    try:
        lock_role_administration(db, g.current_org_id)
        target = _load_target(db, user_uuid)
        if not target:
            return jsonify({"error": "User not found"}), 404
        if target.id == g.current_user.id:
            return jsonify({"error": "Cannot delete your own account"}), 400
        org_users = UserRepository(db).list_users_for_org(g.current_org_id)
        check_change(g.current_user, target, org_users, role=None, is_active=False)

        target_id, target_email = target.id, target.email
        target.invite_token_hash = None
        target.invite_expires_at = None
        # Soft delete through the repository (it commits): history is kept, sign-in stops.
        if not UserRepository(db).delete_user(target_id, g.current_org_id):
            return jsonify({"error": "Failed to delete user"}), 500
        log_action("delete", "user", target_id, {"email": target_email}, g.current_org_id, g.current_user.id)
        return jsonify({"message": "User deleted successfully"}), 200

    except PeopleError as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception:
        db.rollback()
        logger.exception("Error deleting user")
        return jsonify({"error": "Failed to delete user"}), 500


# --- custom roles (plan 0.4c) ---------------------------------------------------------------


def _custom_roles(db) -> list:
    return db.query(OrgRole).filter(OrgRole.org_id == g.current_org_id).order_by(OrgRole.name.asc()).limit(100).all()


def _serialize_role(role: OrgRole, holders: int, site_ids=()) -> dict:
    return {
        "id": str(role.id),
        "value": f"custom:{role.id}",
        "name": role.name,
        "description": role.description,
        "base_role": role.base_role,
        "permissions": list(role.permissions or []),
        "holders": holders,
        "site_access_mode": role.site_access_mode,
        "site_ids": [str(site_id) for site_id in site_ids],
        "assignable": role.site_access_mode == "all",
    }


def _roles_body(db) -> dict:
    from sqlalchemy import func

    from app.core.security.access_policy import CUSTOM_ROLE_BASES, GRANTABLE, ROLE_LABELS, ROLE_PERMISSIONS

    customs = _custom_roles(db)
    counts = dict(
        db.query(User.custom_role_id, func.count(User.id))
        .filter(User.org_id == g.current_org_id, User.custom_role_id.isnot(None))
        .group_by(User.custom_role_id)
        .all()
    )
    return {
        "custom_roles": [
            _serialize_role(r, counts.get(r.id, 0), role_site_ids(db, g.current_org_id, r.id)) for r in customs
        ],
        "built_in": [
            {
                "value": role.value,
                "label": ROLE_LABELS[role],
                "permissions": sorted(ROLE_PERMISSIONS[role]),
                "can_clone": role in CUSTOM_ROLE_BASES,
                "clone_permissions": sorted(ROLE_PERMISSIONS[role] & GRANTABLE),
            }
            for role in UserRole
        ],
        "permissions": permission_catalogue(),
        "site_roles_assignable": False,
        "sites": [
            {"id": str(s.id), "name": s.name, "is_active": s.is_active}
            for s in db.query(Site).filter(Site.org_id == g.current_org_id).order_by(Site.name).all()
        ],
    }


@org_bp.route("/roles", methods=["GET"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def list_roles():
    return jsonify(_roles_body(db_session())), 200


@org_bp.route("/roles", methods=["POST"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def create_role():
    """Clone a built-in role and tick its permissions (admin only)."""
    data = _json_body()
    if data is None:
        return jsonify({"error": "JSON body required"}), 400
    db = db_session()
    try:
        lock_role_administration(db, g.current_org_id)
        mode, ids = validate_site_config(db, g.current_org_id, data)
        values = validate_custom_role(data, {r.name.casefold() for r in _custom_roles(db)})
        role = OrgRole(org_id=g.current_org_id, created_by_user_id=g.current_user.id, **values)
        db.add(role)
        db.flush()
        replace_site_config(db, role, mode, ids)
        db.commit()
    except PeopleError as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400
    log_action(
        "create",
        "org_role",
        role.id,
        {**values, "site_access_mode": mode, "site_ids": [str(x) for x in sorted(ids)]},
        g.current_org_id,
        g.current_user.id,
    )
    return jsonify(_roles_body(db)), 201


def _load_role(db, role_id: str):
    try:
        rid = UUID(role_id)
    except ValueError:
        return None
    return db.query(OrgRole).filter(OrgRole.id == rid, OrgRole.org_id == g.current_org_id).one_or_none()


@org_bp.route("/roles/<role_id>", methods=["PATCH"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def update_role(role_id: str):
    """Rename a custom role or change its permissions; everyone holding it changes at once."""
    data = _json_body()
    if data is None:
        return jsonify({"error": "JSON body required"}), 400
    db = db_session()
    lock_role_administration(db, g.current_org_id)
    role = _load_role(db, role_id)
    if role is None:
        return jsonify({"error": "Role not found"}), 404
    try:
        mode, ids = validate_site_config(
            db,
            g.current_org_id,
            data,
            default_mode=role.site_access_mode,
            default_ids=[str(x) for x in role_site_ids(db, g.current_org_id, role.id)],
        )
        others = {r.name.casefold() for r in _custom_roles(db) if r.id != role.id}
        values = validate_custom_role(
            {
                "name": data.get("name", role.name),
                "base_role": role.base_role,  # the base can't change: it's what holders carry
                "permissions": data.get("permissions", role.permissions),
                "description": data.get("description", role.description),
            },
            others,
        )
        before = {
            "name": role.name,
            "permissions": list(role.permissions or []),
            "site_access_mode": role.site_access_mode,
            "site_ids": [str(x) for x in role_site_ids(db, g.current_org_id, role.id)],
        }
        replace_site_config(db, role, mode, ids)
        role.name, role.permissions, role.description = values["name"], values["permissions"], values["description"]
        db.commit()
    except PeopleError as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400
    log_action(
        "update",
        "org_role",
        role.id,
        {
            "before": before,
            "after": {
                "name": role.name,
                "permissions": role.permissions,
                "site_access_mode": mode,
                "site_ids": [str(x) for x in sorted(ids)],
            },
        },
        g.current_org_id,
        g.current_user.id,
    )
    return jsonify(_roles_body(db)), 200


@org_bp.route("/roles/<role_id>", methods=["DELETE"])
@requires_auth
@requires_role(UserRole.ADMIN)
@requires_org_scope
def delete_role(role_id: str):
    db = db_session()
    lock_role_administration(db, g.current_org_id)
    role = _load_role(db, role_id)
    if role is None:
        return jsonify({"error": "Role not found"}), 404
    holders = db.query(User.id).filter(User.org_id == g.current_org_id, User.custom_role_id == role.id).count()
    if holders:
        return jsonify({"error": f"{holders} person(s) still have this role. Give them another role first."}), 409
    name = role.name
    db.delete(role)
    db.commit()
    log_action("delete", "org_role", UUID(role_id), {"name": name}, g.current_org_id, g.current_user.id)
    return jsonify(_roles_body(db)), 200
