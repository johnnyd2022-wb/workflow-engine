"""GL-P03: recall API. Case lifecycle (acknowledge, start, resolve, verify) stays on the
operational-case routes; these carry the recall's own record."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.security.permissions import requires_auth, requires_org_scope
from app.core.utils.log_action import log_action
from app.core.utils.time import utc_now
from app.features.recalls import service
from app.features.recalls.models import Recall

bp = Blueprint("recalls", __name__)


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _when(value, field: str) -> datetime:
    if value in (None, ""):
        return utc_now()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise service.RecallError(f"{field} must be a date and time") from None
    if parsed.tzinfo is None:
        raise service.RecallError(f"{field} needs a time zone")
    return parsed


def _fail(exc: service.RecallError):
    db_session().rollback()
    return jsonify({"error": str(exc)}), exc.status


def _recall(recall_id):
    rid = _uuid(recall_id)
    found = (
        db_session().query(Recall).filter(Recall.org_id == g.current_org_id, Recall.id == rid).one_or_none()
        if rid
        else None
    )
    if found is None:
        raise service.RecallError("Recall not found", 404)
    return found


@bp.post("/api/core/recalls")
@requires_auth
@requires_org_scope
def open_recall():
    body = _body()
    session = db_session()
    try:
        lot_id, owner_id = _uuid(body.get("lot_id")), _uuid(body.get("owner_id") or g.current_user.id)
        if lot_id is None:
            raise service.RecallError("Lot not found", 404)
        if owner_id is None:
            raise service.RecallError("Choose an owner from your team")
        recall = service.open_recall(
            session,
            g.current_org_id,
            g.current_user,
            lot_id=lot_id,
            reason=body.get("reason"),
            risk=str(body.get("risk") or ""),
            owner_id=owner_id,
            due_at=_when(body.get("due_at"), "Due date"),
            is_drill=body.get("is_drill") is True,
        )
        session.commit()
    except service.RecallError as exc:
        return _fail(exc)
    log_action(
        "recall_drill_opened" if recall.is_drill else "recall_opened",
        "operational_case",
        recall.case_id,
        {"recall_id": str(recall.id), "lot_id": str(recall.root_lot_id), "holds": len(recall.hold_ids or [])},
    )
    return jsonify({"recall": service.serialise(session, g.current_org_id, recall)}), 201


@bp.get("/api/core/recalls")
@requires_auth
@requires_org_scope
def list_recalls():
    session = db_session()
    rows = service.list_recalls(session, g.current_org_id)
    return jsonify({"recalls": [service.serialise(session, g.current_org_id, r) for r in rows]})


@bp.get("/api/core/recalls/<recall_id>")
@requires_auth
@requires_org_scope
def get_recall(recall_id):
    try:
        recall = _recall(recall_id)
    except service.RecallError as exc:
        return _fail(exc)
    return jsonify({"recall": service.serialise(db_session(), g.current_org_id, recall)})


@bp.get("/api/core/recalls/<recall_id>/contacts/<contact_id>/notice")
@requires_auth
@requires_org_scope
def draft_notice(recall_id, contact_id):
    """The customer's notice, drafted for a person to send. Biz-E never sends it."""
    from app.features.recalls.models import RecallContact

    try:
        recall = _recall(recall_id)
        cid = _uuid(contact_id)
        contact = (
            db_session()
            .query(RecallContact)
            .filter(
                RecallContact.org_id == g.current_org_id, RecallContact.recall_id == recall.id, RecallContact.id == cid
            )
            .one_or_none()
            if cid
            else None
        )
        if contact is None:
            raise service.RecallError("Customer not found on this recall", 404)
    except service.RecallError as exc:
        return _fail(exc)
    org = db_session().get(Organisation, g.current_org_id)
    return jsonify({"notice": service.draft_notice(org.name if org else "", recall, contact), "sent": False})


def _contact_action(recall_id, contact_id, action):
    session = db_session()
    try:
        recall = _recall(recall_id)
        cid = _uuid(contact_id)
        if cid is None:
            raise service.RecallError("Customer not found on this recall", 404)
        contact = action(session, recall.id, cid, _body())
        session.commit()
    except service.RecallError as exc:
        return _fail(exc)
    return jsonify({"contact": service.serialise_contact(contact)})


@bp.post("/api/core/recalls/<recall_id>/contacts/<contact_id>/notice-sent")
@requires_auth
@requires_org_scope
def notice_sent(recall_id, contact_id):
    return _contact_action(
        recall_id,
        contact_id,
        lambda s, rid, cid, b: service.record_notice_sent(
            s,
            g.current_org_id,
            g.current_user.id,
            rid,
            cid,
            channel=b.get("channel"),
            sent_at=_when(b.get("sent_at"), "Sent"),
        ),
    )


@bp.post("/api/core/recalls/<recall_id>/contacts/<contact_id>/acknowledged")
@requires_auth
@requires_org_scope
def acknowledged(recall_id, contact_id):
    return _contact_action(
        recall_id,
        contact_id,
        lambda s, rid, cid, b: service.record_acknowledgement(
            s,
            g.current_org_id,
            g.current_user.id,
            rid,
            cid,
            by=b.get("by"),
            note=b.get("note"),
            at=_when(b.get("at"), "Acknowledged"),
        ),
    )


@bp.post("/api/core/recalls/<recall_id>/contacts/<contact_id>/unreachable")
@requires_auth
@requires_org_scope
def unreachable(recall_id, contact_id):
    return _contact_action(
        recall_id,
        contact_id,
        lambda s, rid, cid, b: service.record_unreachable(
            s, g.current_org_id, g.current_user.id, rid, cid, note=b.get("note")
        ),
    )


@bp.post("/api/core/recalls/<recall_id>/contacts/<contact_id>/quantities")
@requires_auth
@requires_org_scope
def quantities(recall_id, contact_id):
    return _contact_action(
        recall_id,
        contact_id,
        lambda s, rid, cid, b: service.record_quantities(
            s,
            g.current_org_id,
            g.current_user.id,
            rid,
            cid,
            recovered=b.get("recovered", 0),
            disposed=b.get("disposed", 0),
        ),
    )
