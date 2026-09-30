"""Staff explicitly choose what to share; invitations require people management."""

from datetime import UTC, datetime
from uuid import UUID

from flask import g, jsonify, render_template, request
from flask_limiter.util import get_remote_address

from app.api.routes.auth_routes import limiter
from app.core.db import db_session
from app.core.security.permissions import requires_auth
from app.features.contract_manufacturing.models.portal import PortalDocument, PortalInvite, PortalPublication
from app.features.contract_manufacturing.routes.orders import bp, handled, service
from app.features.contract_manufacturing.services.orders import OrderError
from app.features.contract_manufacturing.services.portal_auth import audit, issue_invite, portal_people, revoke_access
from app.features.contract_manufacturing.services.portal_progress import step_candidates
from app.features.contract_manufacturing.services.portal_sharing import (
    document_dto,
    publish_order,
    revoke_publication,
    share_document,
)


@bp.get("/core/contracts/<uuid:order_id>/portal-sharing")
@requires_auth
@handled
def portal_sharing_page(order_id):
    svc = service()
    order = svc.order(order_id)
    documents = (
        db_session().query(PortalDocument).filter_by(org_id=UUID(g.org_id), order_id=order.id, revoked_at=None).all()
    )
    publication = (
        db_session()
        .query(PortalPublication)
        .filter_by(org_id=UUID(g.org_id), order_id=order.id)
        .order_by(PortalPublication.revision.desc())
        .first()
    )
    return render_template(
        "contracts/sharing.html",
        active_page="contracts",
        order=order,
        documents=[document_dto(d) for d in documents],
        publication=publication,
        step_candidates=step_candidates(db_session(), UUID(g.org_id), order) if _can_record() else [],
        selected_steps={
            item["execution_step_id"]: item["label"]
            for item in ((publication.payload.get("progress") or {}).get("selection") or [])
        }
        if publication and _can_record()
        else {},
        people=portal_people(db_session(), UUID(g.org_id), order.customer_id)
        if g.current_user and _manage_people()
        else None,
    )


def _manage_people():
    from app.core.security.access_policy import has_permission

    return has_permission(g.current_user, "users.manage")


def _can_record():
    from app.core.security.access_policy import has_permission

    return has_permission(g.current_user, "production.record")


@bp.get("/api/core/contract-customers/<uuid:customer_id>/portal-people")
@requires_auth
@handled
def portal_list_people(customer_id):
    return jsonify(portal_people(db_session(), UUID(g.org_id), customer_id))


@bp.post("/api/core/contract-customers/<uuid:customer_id>/portal-invites")
@requires_auth
@limiter.limit("20 per hour", key_func=get_remote_address)
@handled
def portal_issue_invite(customer_id):
    invite, token = issue_invite(
        db_session(), UUID(g.org_id), g.current_user.id, customer_id, request.get_json(silent=True)
    )
    db_session().commit()
    return jsonify(
        {
            "invite_id": str(invite.id),
            "expires_at": invite.expires_at.isoformat(),
            "invite_link": f"/portal/invite#{token}",
        }
    ), 201


@bp.delete("/api/core/contract-customers/<uuid:customer_id>/portal-invites/<uuid:invite_id>")
@requires_auth
@handled
def portal_revoke_invite(customer_id, invite_id):
    service().customer(customer_id)
    row = (
        db_session()
        .query(PortalInvite)
        .filter_by(org_id=UUID(g.org_id), customer_id=customer_id, id=invite_id)
        .with_for_update()
        .first()
    )
    if row is None:
        raise OrderError("Invitation not found", 404)
    row.revoked_at = datetime.now(UTC)
    audit(db_session(), UUID(g.org_id), "invitation_revoked", row)
    db_session().commit()
    return "", 204


@bp.delete("/api/core/contract-customers/<uuid:customer_id>/portal-people/<uuid:principal_id>")
@requires_auth
@handled
def portal_revoke_person(customer_id, principal_id):
    revoke_access(db_session(), UUID(g.org_id), customer_id, principal_id)
    db_session().commit()
    return "", 204


@bp.post("/api/core/contract-orders/<uuid:order_id>/portal-publications")
@requires_auth
@handled
def portal_publish_order(order_id):
    row = publish_order(db_session(), UUID(g.org_id), g.current_user.id, order_id, request.get_json(silent=True))
    db_session().commit()
    return jsonify({"publication_id": str(row.id), "revision": row.revision}), 201


@bp.delete("/api/core/contract-orders/<uuid:order_id>/portal-publications")
@requires_auth
@handled
def portal_unpublish_order(order_id):
    revoke_publication(db_session(), UUID(g.org_id), order_id)
    db_session().commit()
    return "", 204


@bp.post("/api/core/contract-orders/<uuid:order_id>/portal-documents")
@requires_auth
@handled
def portal_upload_document(order_id):
    if set(request.form) - {"title", "csrf_token"} or set(request.files) != {"document"}:
        raise OrderError("Provide a title and one document")
    row = share_document(
        db_session(),
        UUID(g.org_id),
        g.current_user.id,
        order_id,
        request.form.get("title"),
        request.files.get("document"),
    )
    db_session().commit()
    return jsonify({"document": document_dto(row)}), 201


@bp.delete("/api/core/contract-orders/<uuid:order_id>/portal-documents/<uuid:document_id>")
@requires_auth
@handled
def portal_revoke_document(order_id, document_id):
    order = service().order(order_id, lock=True)
    row = (
        db_session()
        .query(PortalDocument)
        .filter_by(org_id=UUID(g.org_id), order_id=order.id, customer_id=order.customer_id, id=document_id)
        .first()
    )
    if row is None:
        raise OrderError("Document not found", 404)
    row.revoked_at = datetime.now(UTC)
    audit(db_session(), UUID(g.org_id), "document_revoked", row)
    db_session().commit()
    return "", 204
