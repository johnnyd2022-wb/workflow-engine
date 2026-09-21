"""Core suppliers: a small per-organisation address book with an audited history.

Every create, edit and delete writes an entity event (the feed the dashboard audit list
and entity stories read) and an ``audit_logs`` row, carrying the supplier's details and, for
an edit, exactly what changed. Suppliers already named on inventory items can be pulled in.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from flask import g, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.supplier import Supplier
from app.core.security.permissions import requires_auth
from app.core.utils.log_action import log_action
from app.core.utils.time import utc_now
from app.observability import get_logger

logger = get_logger(__name__)

FIELDS = ("name", "contact_name", "phone", "email", "address", "notes")
_MAX_LENGTH = {"name": 255, "contact_name": 255, "phone": 50, "email": 255, "address": 2000, "notes": 4000}


class SupplierError(ValueError):
    """The request is invalid; the message is safe to show the user."""


def clean_fields(data: dict[str, Any]) -> dict[str, str | None]:
    """Validate the supplier fields present in `data`; a blank optional field is stored as null."""
    cleaned: dict[str, str | None] = {}
    for key in FIELDS:
        if key not in data:
            continue
        raw = data[key]
        if raw is not None and not isinstance(raw, str):
            raise SupplierError(f"{key.replace('_', ' ').capitalize()} must be text")
        value = (raw or "").strip()
        if len(value) > _MAX_LENGTH[key]:
            raise SupplierError(f"{key.replace('_', ' ').capitalize()} must be at most {_MAX_LENGTH[key]} characters")
        cleaned[key] = value or None
    if "name" in cleaned and not cleaned["name"]:
        raise SupplierError("Supplier name is required")
    if cleaned.get("email") and ("@" not in cleaned["email"] or " " in cleaned["email"]):
        raise SupplierError("Email must be a valid address")
    return cleaned


def serialise(supplier: Supplier) -> dict[str, Any]:
    return {
        "id": str(supplier.id),
        **{key: getattr(supplier, key) for key in FIELDS},
        "created_at": supplier.created_at.isoformat() if supplier.created_at else None,
        "updated_at": supplier.updated_at.isoformat() if supplier.updated_at else None,
    }


def _snapshot(supplier: Supplier) -> dict[str, Any]:
    return {key: getattr(supplier, key) for key in FIELDS}


def _record(
    session: Session,
    org_id: UUID,
    actor_id: UUID | None,
    action: str,
    supplier: Supplier,
    payload: dict[str, Any],
    diff: dict[str, Any] | None = None,
    **extra: Any,
) -> None:
    EventWriter(session, org_id).emit(
        event_type=f"supplier.{action}",
        entity_type="supplier",
        entity_id=supplier.id,
        payload={**payload, **extra},
        diff=diff,
        actor_id=actor_id,
    )
    log_action(
        {"created": "create", "updated": "update", "deleted": "delete"}[action],
        "supplier",
        supplier.id,
        {"name": payload.get("name"), **({"changes": diff} if diff else {}), **extra},
        org_id=org_id,
        user_id=actor_id,
    )


def list_suppliers(session: Session, org_id: UUID) -> list[dict[str, Any]]:
    rows = session.query(Supplier).filter(Supplier.org_id == org_id).order_by(func.lower(Supplier.name)).all()
    return [serialise(row) for row in rows]


def _add(session: Session, org_id: UUID, actor_id: UUID | None, values: dict[str, Any], **extra: Any) -> Supplier:
    name = values.get("name")
    if not name:
        raise SupplierError("Supplier name is required")
    exists = (
        session.query(Supplier.id).filter(Supplier.org_id == org_id, func.lower(Supplier.name) == name.lower()).first()
    )
    if exists:
        raise SupplierError(f"A supplier called {name!r} already exists")
    supplier = Supplier(org_id=org_id, created_by_user_id=actor_id, **values)
    session.add(supplier)
    session.flush()
    _record(session, org_id, actor_id, "created", supplier, _snapshot(supplier), **extra)
    return supplier


def create_supplier(session: Session, org_id: UUID, actor_id: UUID | None, data: dict[str, Any]) -> dict[str, Any]:
    values = clean_fields(data)
    try:
        supplier = _add(session, org_id, actor_id, {key: values.get(key) for key in FIELDS}, source="manual")
        session.commit()
    except IntegrityError:  # a concurrent create of the same name
        session.rollback()
        raise SupplierError(f"A supplier called {values.get('name')!r} already exists") from None
    return serialise(supplier)


def update_supplier(
    session: Session, org_id: UUID, actor_id: UUID | None, supplier_id: UUID, data: dict[str, Any]
) -> dict[str, Any] | None:
    supplier = session.query(Supplier).filter(Supplier.org_id == org_id, Supplier.id == supplier_id).first()
    if supplier is None:
        logger.warning("access_denied", reason="supplier_not_found_or_cross_org", org_id=str(org_id))
        return None
    values = clean_fields(data)
    if values.get("name") and values["name"].lower() != supplier.name.lower():
        clash = (
            session.query(Supplier.id)
            .filter(Supplier.org_id == org_id, func.lower(Supplier.name) == values["name"].lower())
            .first()
        )
        if clash:
            raise SupplierError(f"A supplier called {values['name']!r} already exists")
    before = _snapshot(supplier)
    for key, value in values.items():
        setattr(supplier, key, value)
    after = _snapshot(supplier)
    diff = {key: {"before": before[key], "after": after[key]} for key in FIELDS if before[key] != after[key]}
    if diff:
        supplier.updated_at = utc_now()
        _record(session, org_id, actor_id, "updated", supplier, after, diff)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise SupplierError(f"A supplier called {values.get('name')!r} already exists") from None
    return serialise(supplier)


def delete_supplier(session: Session, org_id: UUID, actor_id: UUID | None, supplier_id: UUID) -> bool:
    supplier = session.query(Supplier).filter(Supplier.org_id == org_id, Supplier.id == supplier_id).first()
    if supplier is None:
        logger.warning("access_denied", reason="supplier_not_found_or_cross_org", org_id=str(org_id))
        return False
    _record(session, org_id, actor_id, "deleted", supplier, _snapshot(supplier))
    session.delete(supplier)
    session.commit()
    return True


def import_from_inventory(session: Session, org_id: UUID, actor_id: UUID | None) -> dict[str, Any]:
    """Create a supplier for each name on inventory items that has no supplier record yet."""
    known = {name.lower() for (name,) in session.query(Supplier.name).filter(Supplier.org_id == org_id)}
    named = (
        session.query(InventoryItem.supplier, func.count(InventoryItem.id))
        .filter(InventoryItem.org_id == org_id, InventoryItem.supplier.isnot(None))
        .group_by(InventoryItem.supplier)
        .all()
    )
    created: list[str] = []
    for raw_name, item_count in sorted(named, key=lambda row: (row[0] or "").lower()):
        name = (raw_name or "").strip()
        if not name or name.lower() in known:
            continue
        _add(session, org_id, actor_id, {"name": name}, source="inventory", inventory_items=int(item_count))
        known.add(name.lower())
        created.append(name)
    session.commit()
    return {"created": created, "suppliers": list_suppliers(session, org_id)}


def register_routes(bp) -> None:
    """Attach the supplier JSON routes to the always-mounted Core blueprint."""

    def org_id() -> UUID:
        return UUID(g.org_id)

    def actor_id() -> UUID | None:
        return UUID(g.user_id) if g.user_id else None

    @bp.route("/api/core/suppliers", methods=["GET"])
    @requires_auth
    def list_core_suppliers():
        return jsonify({"suppliers": list_suppliers(db_session(), org_id())})

    @bp.route("/api/core/suppliers", methods=["POST"])
    @requires_auth
    def create_core_supplier():
        try:
            supplier = create_supplier(db_session(), org_id(), actor_id(), request.get_json(silent=True) or {})
            return jsonify({"supplier": supplier}), 201
        except SupplierError as exc:
            db_session().rollback()
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/core/suppliers/<supplier_id>", methods=["PUT"])
    @requires_auth
    def update_core_supplier(supplier_id: str):
        try:
            supplier = update_supplier(
                db_session(), org_id(), actor_id(), UUID(supplier_id), request.get_json(silent=True) or {}
            )
        except SupplierError as exc:
            db_session().rollback()
            return jsonify({"error": str(exc)}), 400
        except ValueError:
            return jsonify({"error": "supplier_id must be a UUID"}), 400
        if supplier is None:
            return jsonify({"error": "Supplier not found"}), 404
        return jsonify({"supplier": supplier})

    @bp.route("/api/core/suppliers/<supplier_id>", methods=["DELETE"])
    @requires_auth
    def delete_core_supplier(supplier_id: str):
        try:
            deleted = delete_supplier(db_session(), org_id(), actor_id(), UUID(supplier_id))
        except ValueError:
            return jsonify({"error": "supplier_id must be a UUID"}), 400
        if not deleted:
            return jsonify({"error": "Supplier not found"}), 404
        return jsonify({"ok": True})

    @bp.route("/api/core/suppliers/import-from-inventory", methods=["POST"])
    @requires_auth
    def import_core_suppliers_from_inventory():
        return jsonify(import_from_inventory(db_session(), org_id(), actor_id()))
