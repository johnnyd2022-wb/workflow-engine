"""Copy only explicitly shared facts; customer reads never serialize operational records."""

import copy
import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from app.core.db.models.organisation import Organisation
from app.features.contract_manufacturing.models.portal import PortalDocument, PortalPublication
from app.features.contract_manufacturing.services.orders import (
    ContractOrderService,
    OrderError,
    identifier,
    object_body,
    text_value,
)
from app.features.contract_manufacturing.services.portal_auth import audit

UNAVAILABLE = {"available": False, "reason": "Not shared yet"}
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


def measurement(value, name):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise OrderError(f"{name} must be a number between 0 and 100")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= 100 or number.as_tuple().exponent < -4:
            raise ValueError
    except (ValueError, InvalidOperation):
        raise OrderError(f"{name} must be a number between 0 and 100 (up to four decimal places)") from None
    return format(number, "f")


def share_document(db, org_id, actor_id, order_id, title, upload):
    order = ContractOrderService(db, org_id).order(order_id, lock=True)
    title = text_value(title, "title", 255)
    if upload is None:
        raise OrderError("A document file is required")
    content = upload.stream.read(MAX_DOCUMENT_BYTES + 1)
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise OrderError("Documents must be between 1 byte and 5 MB")
    mime = upload.mimetype
    valid = (
        (mime == "application/pdf" and content.startswith(b"%PDF-"))
        or (mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
    )
    if mime == "text/plain":
        try:
            content.decode("utf-8")
            valid = b"\x00" not in content
        except UnicodeDecodeError:
            valid = False
    if not valid:
        raise OrderError("Use PDF, PNG, JPEG or UTF-8 plain text")
    row = PortalDocument(
        org_id=org_id,
        order_id=order.id,
        customer_id=order.customer_id,
        title=title,
        content_type=mime,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by=actor_id,
    )
    db.add(row)
    db.flush()
    audit(db, org_id, "document_uploaded", row)
    return row


def document_dto(row):
    return {"id": str(row.id), "title": row.title, "content_type": row.content_type, "sha256": row.sha256}


def publish_order(db, org_id, actor_id, order_id, data):
    object_body(
        data,
        {"stage_label", "step_label", "progress_percent", "actual_abv", "spec_abv", "document_ids", "bottling_dates"},
    )
    order = ContractOrderService(db, org_id).order(order_id, lock=True)
    stage = text_value(data.get("stage_label"), "stage_label", 100, False)
    step = text_value(data.get("step_label"), "step_label", 100, False)
    progress = measurement(data.get("progress_percent"), "progress_percent")
    actual_abv = measurement(data.get("actual_abv"), "actual_abv")
    spec_abv = measurement(data.get("spec_abv"), "spec_abv")
    document_ids = data.get("document_ids", [])
    if not isinstance(document_ids, list) or len(document_ids) > 50:
        raise OrderError("document_ids must be a list of up to 50 shared documents")
    requested_ids = list(dict.fromkeys(identifier(v, "document_id") for v in document_ids))
    document_rows = (
        db.query(PortalDocument)
        .filter_by(org_id=org_id, order_id=order.id, customer_id=order.customer_id, revoked_at=None)
        .filter(PortalDocument.id.in_(requested_ids))
        .all()
    )
    documents_by_id = {row.id: row for row in document_rows}
    documents = []
    for document_id in requested_ids:
        row = documents_by_id.get(document_id)
        if row is None:
            raise OrderError("Shared document not found for this order", 404)
        documents.append(document_dto(row))
    batches = {str(link.execution_id) for line in order.lines for link in line.batches}
    bottling_dates = data.get("bottling_dates", {})
    if not isinstance(bottling_dates, dict) or set(bottling_dates) - batches:
        raise OrderError("Bottling dates must refer only to this order's linked batches")
    dates = {}
    for batch_id, value in bottling_dates.items():
        try:
            dates[batch_id] = date.fromisoformat(value).isoformat()
        except (TypeError, ValueError):
            raise OrderError("Bottling dates must be YYYY-MM-DD") from None
    now = datetime.now(UTC)
    # Organisation is the tenant root: its primary key is the org ID, not an org_id column.
    organisation = db.query(Organisation).filter_by(id=org_id).one()  # nosemgrep: filter-by-missing-org-id
    revision = (
        db.query(func.max(PortalPublication.revision)).filter_by(org_id=org_id, order_id=order.id).scalar() or 0
    ) + 1
    payload = {
        "schema_version": 1,
        "order_id": str(order.id),
        "reference": order.reference,
        "customer_name": order.customer.name,
        "producer_name": organisation.name,
        "status": order.status,
        "due_date": order.due_date.isoformat(),
        "shared_at": now.isoformat(),
        "revision": revision,
        "progress": {
            "available": bool(stage or step or progress is not None),
            "stage_label": stage,
            "step_label": step,
            "percent": progress,
        },
        "timing": {
            "available": False,
            "planned_ready_date": None,
            "forecast_ready_date": None,
            "reason": "Ready dates have not been shared",
        },
        "quantities": {
            "available": True,
            "lines": [
                {
                    "product_name": line.product_name,
                    "ordered": format(line.quantity, "f"),
                    "unit": line.unit,
                    "in_production": None,
                    "finished": None,
                    "dispatched": None,
                    "still_to_come": None,
                }
                for line in order.lines
            ],
            "reason": "Production and dispatch quantities have not been shared",
        },
        "batches": {
            "available": bool(batches),
            "items": [{"batch_id": batch_id, "bottling_date": dates.get(batch_id)} for batch_id in sorted(batches)],
        },
        "quality": {
            "available": actual_abv is not None or spec_abv is not None,
            "actual_abv": actual_abv,
            "spec_abv": spec_abv,
            "qc_passed": None,
            "reason": "QC status has not been shared",
        },
        "materials": copy.deepcopy(UNAVAILABLE),
        "yield": copy.deepcopy(UNAVAILABLE),
        "delivery": copy.deepcopy(UNAVAILABLE),
        "documents": {"available": bool(documents), "items": documents},
        "waiting_on_you": {
            "available": False,
            "approvals": [],
            "messages": [],
            "reason": "Approvals and messages are not available yet",
        },
    }
    row = PortalPublication(
        org_id=org_id,
        order_id=order.id,
        customer_id=order.customer_id,
        revision=revision,
        payload=payload,
        published_by=actor_id,
        created_at=now,
    )
    db.add(row)
    db.flush()
    audit(db, org_id, "order_published", row)
    return row


def publication_dto(payload):
    """A second allowlist at the customer boundary, independent of the writer.

    New internal snapshot fields never become customer-visible by accident.
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise OrderError("Published order is unavailable", 404)
    base = (
        "schema_version",
        "order_id",
        "reference",
        "customer_name",
        "producer_name",
        "status",
        "due_date",
        "shared_at",
        "revision",
    )
    fields = {
        "progress": ("available", "stage_label", "step_label", "percent"),
        "timing": ("available", "planned_ready_date", "forecast_ready_date", "reason"),
        "quantities": ("available", "reason"),
        "batches": ("available",),
        "quality": ("available", "actual_abv", "spec_abv", "qc_passed", "reason"),
        "materials": ("available", "reason"),
        "yield": ("available", "reason"),
        "delivery": ("available", "reason"),
        "documents": ("available",),
        "waiting_on_you": ("available", "reason"),
    }
    result = {key: copy.deepcopy(payload.get(key)) for key in base}
    for section, keys in fields.items():
        source = payload.get(section, {})
        if not isinstance(source, dict):
            raise OrderError("Published order is unavailable", 404)
        result[section] = {key: copy.deepcopy(source.get(key)) for key in keys}
    for section, container, keys in (
        (
            "quantities",
            "lines",
            ("product_name", "ordered", "unit", "in_production", "finished", "dispatched", "still_to_come"),
        ),
        ("batches", "items", ("batch_id", "bottling_date")),
        ("documents", "items", ("id", "title", "content_type", "sha256")),
    ):
        items = payload.get(section, {}).get(container, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise OrderError("Published order is unavailable", 404)
        result[section][container] = [{key: copy.deepcopy(item.get(key)) for key in keys} for item in items]
    # Pending approval/message integrations cannot expose arbitrary internal threads.
    result["waiting_on_you"].update(approvals=[], messages=[])
    return result


def shared_orders(db, principal):
    # Include revoked latest revisions in selection: never resurrect an older publication.
    rows = (
        db.query(PortalPublication)
        .filter_by(org_id=principal.org_id, customer_id=principal.customer_id)
        .order_by(PortalPublication.order_id, PortalPublication.revision.desc())
        .all()
    )
    latest = {}
    for row in rows:
        latest.setdefault(row.order_id, row)
    return [publication_dto(row.payload) for row in latest.values() if row.revoked_at is None]


def shared_order(db, principal, order_id):
    row = (
        db.query(PortalPublication)
        .filter_by(
            org_id=principal.org_id, customer_id=principal.customer_id, order_id=identifier(order_id, "order_id")
        )
        .order_by(PortalPublication.revision.desc())
        .first()
    )
    if row is None or row.revoked_at:
        raise OrderError("Order not found", 404)
    return publication_dto(row.payload)


def shared_document(db, principal, order_id, document_id):
    payload = shared_order(db, principal, order_id)
    doc_id = identifier(document_id, "document_id")
    if not any(item["id"] == str(doc_id) for item in payload["documents"]["items"]):
        raise OrderError("Document not found", 404)
    row = (
        db.query(PortalDocument)
        .filter_by(
            org_id=principal.org_id,
            customer_id=principal.customer_id,
            order_id=identifier(order_id, "order_id"),
            id=doc_id,
            revoked_at=None,
        )
        .first()
    )
    if row is None:
        raise OrderError("Document not found", 404)
    return row


def revoke_publication(db, org_id, order_id):
    order = ContractOrderService(db, org_id).order(order_id, lock=True)
    row = (
        db.query(PortalPublication)
        .filter_by(org_id=org_id, order_id=order.id)
        .order_by(PortalPublication.revision.desc())
        .first()
    )
    if row is None:
        raise OrderError("Publication not found", 404)
    row.revoked_at = datetime.now(UTC)
    audit(db, org_id, "publication_revoked", row)
    return row
