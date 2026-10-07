"""Admin pages. Server-rendered forms, no scripts; every route is behind `require_admin`."""

from __future__ import annotations

import os

from flask import Blueprint, g, redirect, render_template, request, url_for

from app.admin_site import operations as ops
from app.admin_site.auth import settings
from app.admin_site.settings import IDLE_MINUTES, SESSION_HOURS
from app.core.db import db_session
from app.core.db.models.organisation import OrganisationStatus

admin_bp = Blueprint("admin", __name__)

_STATUS = {"active": OrganisationStatus.ACTIVE, "suspended": OrganisationStatus.SUSPENDED}


@admin_bp.app_context_processor
def _layout_context():
    return {"admin_email": getattr(g, "admin_email", None), "environment": settings().environment}


def _field(name: str) -> str:
    value = request.form.get(name, "")
    return value.strip() if isinstance(value, str) else ""


def _invite_link(token: str | None) -> str | None:
    return f"{settings().customer_app_url}/invite/{token}" if token else None


@admin_bp.route("/")
def home():
    return redirect(url_for("admin.organisations"))


# ── Organisations ──────────────────────────────────────────────────────────────


def _organisations_page(*, error=None, form=None, status_code=200):
    search = request.args.get("q", "").strip()[:255]
    status = request.args.get("status", "all")
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    orgs, total = ops.list_organisations(
        db_session(), search=search, status=_STATUS.get(status), offset=(page - 1) * ops.PAGE_SIZE
    )
    return (
        render_template(
            "admin/organisations.html",
            organisations=orgs,
            total=total,
            search=search,
            status=status if status in _STATUS else "all",
            page=page,
            pages=max(1, -(-total // ops.PAGE_SIZE)),
            error=error,
            form=form or {},
        ),
        status_code,
    )


@admin_bp.route("/organisations", methods=["GET"])
def organisations():
    return _organisations_page()


@admin_bp.route("/organisations", methods=["POST"])
def create_organisation():
    form = {"name": _field("name"), "admin_email": _field("admin_email")}
    try:
        org, user, token = ops.create_organisation(db_session(), **form, actor=g.admin_email)
    except ops.AdminOperationError as exc:
        db_session().rollback()
        return _organisations_page(error=str(exc), form=form, status_code=400)
    return _organisation_page(
        org.id,
        notice=f"{org.name} created. Send {user.email} the setup link below; it is shown once.",
        secret=_invite_link(token),
        secret_label=f"Setup link for {user.email} (valid for 7 days)",
    )


def _organisation_page(org_id, *, notice=None, error=None, secret=None, secret_label=None, status_code=200):
    db = db_session()
    org = ops.get_organisation(db, org_id)
    features = {row.feature_key: row for row in ops.list_features(db, org.id)}
    return (
        render_template(
            "admin/organisation.html",
            org=org,
            users=ops.list_users(db, org.id),
            is_locked=ops.is_locked,
            features=features,
            feature_keys=sorted(set(ops.KNOWN_FEATURES) | set(features)),
            notice=notice,
            error=error,
            secret=secret,
            secret_label=secret_label,
        ),
        status_code,
    )


@admin_bp.errorhandler(ops.AdminOperationError)
def _operation_failed(exc):
    db_session().rollback()
    return render_template("admin/error.html", message=str(exc)), 404


@admin_bp.route("/organisations/<org_id>", methods=["GET"])
def organisation(org_id):
    return _organisation_page(org_id)


def _act(org_id, action):
    """Run one change against an organisation and show its page again with the outcome."""
    db = db_session()
    org = ops.get_organisation(db, org_id)
    try:
        outcome = action(db, org) or {}
    except ops.AdminOperationError as exc:
        db.rollback()
        return _organisation_page(org.id, error=str(exc), status_code=400)
    return _organisation_page(org.id, **outcome)


@admin_bp.route("/organisations/<org_id>/status", methods=["POST"])
def set_status(org_id):
    def action(db, org):
        status = _STATUS.get(_field("status"))
        if status is None:
            raise ops.AdminOperationError("Choose active or suspended.")
        # Suspending locks a whole business out, so it takes typing the name to confirm.
        if status is OrganisationStatus.SUSPENDED and _field("confirm_name") != org.name:
            raise ops.AdminOperationError("Type the organisation's name exactly to suspend it.")
        ops.set_organisation_status(db, org.id, status, actor=g.admin_email)
        return {"notice": f"{org.name} is now {status.value}."}

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/features", methods=["POST"])
def set_feature(org_id):
    def action(db, org):
        feature = _field("feature")
        if _field("state") == "on":
            ops.grant_feature(db, org.id, feature, note=f"Granted by {g.admin_email}", actor=g.admin_email)
            return {"notice": f"{feature} switched on."}
        ops.revoke_feature(db, org.id, feature, actor=g.admin_email)
        return {"notice": f"{feature} switched off."}

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/users", methods=["POST"])
def invite_user(org_id):
    def action(db, org):
        user, token = ops.create_user(db, org.id, email=_field("email"), role=_field("role"), actor=g.admin_email)
        return {
            "notice": f"{user.email} invited. Send them the setup link below; it is shown once.",
            "secret": _invite_link(token),
            "secret_label": f"Setup link for {user.email} (valid for 7 days)",
        }

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/invite", methods=["POST"])
def reissue_invite(org_id, user_id):
    def action(db, org):
        user, token = ops.reissue_invite(db, org.id, user_id, actor=g.admin_email)
        return {
            "notice": f"New setup link for {user.email}. The old link no longer works.",
            "secret": _invite_link(token),
            "secret_label": f"Setup link for {user.email} (valid for 7 days)",
        }

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/reset-password", methods=["POST"])
def reset_password(org_id, user_id):
    def action(db, org):
        user, password = ops.reset_password(db, org.id, user_id=user_id, actor=g.admin_email)
        return {
            "notice": f"Password reset for {user.email} and any lockout cleared. It is shown once.",
            "secret": password,
            "secret_label": f"Temporary password for {user.email}. Ask them to change it after signing in.",
        }

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/unlock", methods=["POST"])
def unlock_user(org_id, user_id):
    def action(db, org):
        user = ops.unlock_user(db, org.id, user_id, actor=g.admin_email)
        return {"notice": f"{user.email} unlocked."}

    return _act(org_id, action)


# ── Demo and system ────────────────────────────────────────────────────────────


@admin_bp.route("/demo")
def demo():
    return render_template("admin/demo.html")


@admin_bp.route("/system")
def system():
    admin_settings = settings()
    return render_template(
        "admin/system.html",
        status=ops.system_status(db_session()),
        version=os.getenv("APP_VERSION", "not recorded"),
        admins=sorted(admin_settings.allowed_emails),
        customer_app_url=admin_settings.customer_app_url,
        session_hours=SESSION_HOURS,
        idle_minutes=IDLE_MINUTES,
    )
