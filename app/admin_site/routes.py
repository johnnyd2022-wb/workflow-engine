"""Admin pages. Server-rendered forms, no scripts; every route is behind `require_admin`."""

from __future__ import annotations

import os

from flask import Blueprint, g, redirect, render_template, request, send_file, url_for

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
            overview=ops.organisation_overview(db, org.id),
            notes=ops.list_notes(db, org.id),
            documents=ops.list_documents(db, org.id),
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


def _person_page(
    org_id, user_id, *, notice=None, error=None, secret=None, secret_label=None, codes=None, status_code=200
):
    db = db_session()
    org = ops.get_organisation(db, org_id)
    person = ops.get_user(db, org.id, user_id)
    overview = ops.organisation_overview(db, org.id)
    return (
        render_template(
            "admin/person.html",
            org=org,
            person=person,
            locked=ops.is_locked(person),
            invited=bool(not person.is_active and person.invite_token_hash),
            last_sign_in=overview["last_sign_ins"].get(person.id),
            devices=ops.remembered_devices(db, person),
            history=ops.list_audit(db, org.id, user_id=person.id, limit=10)[0],
            google_linked=person.id in overview["google_linked"],
            codes=codes,
            notice=notice,
            error=error,
            secret=secret,
            secret_label=secret_label,
        ),
        status_code,
    )


def _act(org_id, action, user_id=None):
    """Run one change and show the page it was made from again, with the outcome: the
    person's page when ``user_id`` is given, otherwise the organisation's."""
    db = db_session()
    org = ops.get_organisation(db, org_id)

    def page(**outcome):
        if user_id is not None:
            return _person_page(org.id, user_id, **outcome)
        return _organisation_page(org.id, **outcome)

    if user_id is not None:
        ops.get_user(db, org.id, user_id)  # not this organisation's person: 404 before anything runs
    try:
        outcome = action(db, org) or {}
    except ops.AdminOperationError as exc:
        db.rollback()
        return page(error=str(exc), status_code=400)
    return page(**outcome)


@admin_bp.route("/organisations/<org_id>/name", methods=["POST"])
def rename_organisation(org_id):
    def action(db, org):
        before = org.name
        renamed = ops.rename_organisation(db, org.id, _field("name"), actor=g.admin_email)
        return {"notice": f"{before} is now called {renamed.name}."}

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/audit", methods=["GET"])
def audit(org_id):
    db = db_session()
    org = ops.get_organisation(db, org_id)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    person = ops.get_user(db, org.id, request.args["user"]) if request.args.get("user") else None
    entries, total = ops.list_audit(
        db, org.id, user_id=person.id if person else None, offset=(page - 1) * ops.PAGE_SIZE
    )
    return render_template(
        "admin/audit.html",
        org=org,
        person=person,
        entries=entries,
        total=total,
        page=page,
        pages=max(1, -(-total // ops.PAGE_SIZE)),
    )


@admin_bp.route("/organisations/<org_id>/xero", methods=["POST"])
def disconnect_xero(org_id):
    def action(db, org):
        ops.disconnect_xero(db, org.id, actor=g.admin_email)
        return {"notice": f"Xero disconnected for {org.name}. They can connect again from Sales."}

    return _act(org_id, action)


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

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/reset-password", methods=["POST"])
def reset_password(org_id, user_id):
    def action(db, org):
        user, password = ops.reset_password(db, org.id, user_id=user_id, actor=g.admin_email)
        return {
            "notice": f"Password reset for {user.email} and any lockout cleared. It is shown once.",
            "secret": password,
            "secret_label": f"Temporary password for {user.email}. Ask them to change it after signing in.",
        }

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/unlock", methods=["POST"])
def unlock_user(org_id, user_id):
    def action(db, org):
        user = ops.unlock_user(db, org.id, user_id, actor=g.admin_email)
        return {"notice": f"{user.email} unlocked."}

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>", methods=["GET"])
def person(org_id, user_id):
    return _person_page(org_id, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/role", methods=["POST"])
def set_role(org_id, user_id):
    def action(db, org):
        user = ops.set_user_role(db, org.id, user_id, _field("role"), actor=g.admin_email)
        return {"notice": f"{user.email} is now {'an admin' if user.role.value == 'admin' else 'a member'}."}

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/active", methods=["POST"])
def set_active(org_id, user_id):
    def action(db, org):
        active = _field("active") == "yes"
        user = ops.set_user_active(db, org.id, user_id, active, actor=g.admin_email)
        return {"notice": f"{user.email} {'can sign in again' if active else 'can no longer sign in'}."}

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/email", methods=["POST"])
def change_email(org_id, user_id):
    def action(db, org):
        user = ops.change_user_email(db, org.id, user_id, _field("email"), actor=g.admin_email)
        return {"notice": f"Email changed to {user.email}. They sign in with the new address from now on."}

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/two-factor", methods=["POST"])
def reset_two_factor(org_id, user_id):
    def action(db, org):
        user = ops.reset_two_factor(db, org.id, user_id, actor=g.admin_email)
        return {"notice": f"2FA switched off for {user.email}. Their backup codes and remembered devices are gone."}

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/access", methods=["POST"])
def set_access(org_id, user_id):
    def action(db, org):
        user = ops.set_access_expiry(db, org.id, user_id, _field("until"), actor=g.admin_email)
        if user.access_expires_at:
            return {"notice": f"{user.email} has access until {user.access_expires_at:%-d %b %Y}."}
        return {"notice": f"{user.email}'s access no longer has an end date."}

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/google", methods=["POST"])
def unlink_google(org_id, user_id):
    def action(db, org):
        user = ops.unlink_google(db, org.id, user_id, actor=g.admin_email)
        return {"notice": f"Google sign-in unlinked for {user.email}. They sign in with their password."}

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/devices", methods=["POST"])
def forget_devices(org_id, user_id):
    def action(db, org):
        user, removed = ops.forget_devices(db, org.id, user_id, actor=g.admin_email)
        return {"notice": f"Forgot {removed} remembered device{'' if removed == 1 else 's'} for {user.email}."}

    return _act(org_id, action, user_id)


@admin_bp.route("/organisations/<org_id>/users/<user_id>/backup-codes", methods=["POST"])
def backup_codes(org_id, user_id):
    def action(db, org):
        user, codes = ops.get_backup_codes(db, org.id, user_id, actor=g.admin_email)
        return {"notice": f"Backup codes for {user.email}. Shown once; this look is recorded.", "codes": codes}

    return _act(org_id, action, user_id)


# ── Notes and documents ────────────────────────────────────────────────────────


@admin_bp.route("/organisations/<org_id>/notes", methods=["POST"])
def add_note(org_id):
    def action(db, org):
        ops.add_note(db, org.id, request.form.get("body", ""), actor=g.admin_email)
        return {"notice": "Note added."}

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/notes/<note_id>/delete", methods=["POST"])
def delete_note(org_id, note_id):
    def action(db, org):
        ops.delete_note(db, org.id, note_id, actor=g.admin_email)
        return {"notice": "Note deleted."}

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/documents", methods=["POST"])
def upload_document(org_id):
    def action(db, org):
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise ops.AdminOperationError("Choose a file to upload.")
        document = ops.add_document(
            db, org.id, upload.stream, upload.filename, title=_field("title"), actor=g.admin_email
        )
        return {"notice": f"{document.title} uploaded."}

    return _act(org_id, action)


@admin_bp.route("/organisations/<org_id>/documents/<document_id>", methods=["GET"])
def download_document(org_id, document_id):
    document, path = ops.get_document(db_session(), org_id, document_id)
    # Always a download, never rendered: an uploaded file must not run in this site's origin.
    return send_file(
        path, mimetype="application/octet-stream", as_attachment=True, download_name=document.original_filename
    )


@admin_bp.route("/organisations/<org_id>/documents/<document_id>/delete", methods=["POST"])
def delete_document(org_id, document_id):
    def action(db, org):
        title = ops.delete_document(db, org.id, document_id, actor=g.admin_email)
        return {"notice": f"{title} deleted."}

    return _act(org_id, action)


@admin_bp.route("/attention", methods=["GET"])
def attention():
    return render_template("admin/attention.html", attention=ops.needs_attention(db_session()))


@admin_bp.route("/people", methods=["GET"])
def people():
    search = request.args.get("q", "").strip()[:255]
    return render_template("admin/people.html", search=search, results=ops.find_people(db_session(), search))


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
