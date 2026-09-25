"""Wastage disposal pages and API routes registered on Core's blueprint."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import g, jsonify, render_template, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.wastage_repo import WastageRepository
from app.core.domain.inventory_quantity_guard import InventoryQuantityWriteReason, allow_inventory_quantity_write
from app.core.security.permissions import requires_auth
from app.core.utils.inventory_quantity import (
    assert_movement_unit_matches_item_canonical,
    coerce_stored_quantity,
    parse_stored_quantity_to_decimal,
)
from app.core.utils.inventory_wastage_quantity import (
    parse_wastage_quantity,
    parse_wastage_unit_field,
    wastage_entries_payload_hash,
)
from app.core.utils.unit_conversion import are_units_compatible, convert_to_inventory_unit_decimal
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

# Guardrail: batch size caps row-lock duration under concurrent SELECT ... FOR UPDATE.
MAX_WASTAGE_BATCH_ENTRIES = 100

@requires_auth
def inventory_dispose():
    """Full-page disposal flow for recording inventory wastage."""
    item_ids_param = (request.args.get("item_ids") or "").strip()
    item_ids = [v.strip() for v in item_ids_param.split(",") if v and v.strip()] if item_ids_param else []
    return render_template("inventory/dispose.html", active_page="core", initial_item_ids=item_ids)


@requires_auth
def inventory_dispose_confirm():
    """Confirmation page for disposing a single selected quantity (no modals)."""
    inventory_item_id = (request.args.get("inventory_item_id") or "").strip()
    quantity_wasted_raw = (request.args.get("quantity_wasted") or "").strip()

    quantity_wasted = None
    quantity_wasted_dec = None
    error = None
    try:
        if quantity_wasted_raw:
            from decimal import Decimal

            quantity_wasted_dec = Decimal(quantity_wasted_raw)
            if quantity_wasted_dec <= 0:
                error = "Quantity must be greater than 0."
            else:
                # Use float for JSON/JS submission; keep Decimal for remaining calculations.
                quantity_wasted = float(quantity_wasted_dec)
                # Fixed-point + trimmed trailing zeros
                s = format(quantity_wasted_dec, "f")
                if "." in s:
                    s = s.rstrip("0").rstrip(".")
    except (TypeError, ValueError, InvalidOperation):
        # InvalidOperation matters here: `?quantity_wasted=nan` parses to Decimal("NaN"),
        # and the `<= 0` above then raises InvalidOperation — which is NOT a ValueError,
        # so without this the dispose-confirm page 500s on a malformed query string.
        error = "Invalid quantity."

    if not inventory_item_id:
        error = error or "Missing inventory item id."

    inventory_item_name = "item"
    inventory_item_unit = ""
    remaining_quantity_display = ""
    org_id = getattr(g, "org_id", None)
    if org_id and inventory_item_id:
        try:
            item_uuid = UUID(inventory_item_id)
            item = (
                db_session.query(InventoryItem)
                .filter(InventoryItem.id == item_uuid, InventoryItem.org_id == org_id)
                .first()
            )
            if item and getattr(item, "name", None):
                inventory_item_name = str(item.name)
            if item and getattr(item, "unit", None):
                inventory_item_unit = str(item.unit)
            if not error and item and quantity_wasted_dec is not None:
                from decimal import Decimal

                current_qty_dec = Decimal(str(item.quantity))
                remaining_dec = current_qty_dec - quantity_wasted_dec
                if remaining_dec < 0:
                    remaining_dec = Decimal("0")
                rs = format(remaining_dec, "f")
                if "." in rs:
                    rs = rs.rstrip("0").rstrip(".")
                remaining_quantity_display = rs
            elif not error:
                # Same rationale as record_wastage's access_denied log above: this branch
                # covers both a genuinely nonexistent id and a cross-org one indistinguishably
                # (by design — the page must not leak which), so without a log a repeated
                # probe of this preview page leaves no trace at all.
                logger.warning(
                    "access_denied",
                    reason="inventory_item_not_found_or_cross_org",
                    feature="wastage",
                    org_id=str(org_id),
                    inventory_item_id=str(item_uuid),
                    path=request.path,
                )
                error = "Inventory item was not found."
        except (ValueError, TypeError):
            if not error:
                error = "Invalid inventory item id."

    return render_template(
        "inventory/dispose_confirm.html",
        active_page="core",
        inventory_item_id=inventory_item_id,
        inventory_item_name=inventory_item_name,
        inventory_item_unit=inventory_item_unit,
        remaining_quantity_display=remaining_quantity_display,
        quantity_wasted=quantity_wasted,
        error=error,
    )


def _pg_advisory_lock_wastage_idempotency(session, org_id: UUID, idem_key: str) -> None:
    """
    Serialize idempotent wastage retries for the same org+key (PostgreSQL transaction-scoped lock).

    On non-PostgreSQL dialects this is a no-op: idempotency still relies on the unique (org_id, key)
    row and payload hash, but concurrent duplicate requests may race until commit (acceptable tradeoff).
    """
    bind = session.get_bind()
    if not bind or getattr(bind.dialect, "name", None) != "postgresql":
        return
    digest = hashlib.sha256(f"{org_id}:{idem_key}".encode()).digest()
    k1 = int.from_bytes(digest[0:4], "big") & 0x7FFFFFFF
    k2 = int.from_bytes(digest[4:8], "big") & 0x7FFFFFFF
    session.execute(text("SELECT pg_advisory_xact_lock(:k1, :k2)"), {"k1": k1, "k2": k2})


@requires_auth
def record_wastage():
    """
    Record wastage for one or more inventory items.

    Dual-write (same transaction): updates inventory_items.quantity, inserts inventory_wastage and
    inventory_movements. Consistency relies on PostgreSQL transaction atomicity—do not add external I/O,
    message publishing, or async work inside this handler's transaction; future refactors must keep all
    three writes here or introduce explicit reconciliation.

    Transaction: SessionLocal uses autocommit=False; this handler commits once at the end (success path)
    or rollbacks on validation/exception paths. inventory_items.quantity, inventory_wastage, and
    inventory_movements rows for the batch are persisted in that single commit (no partial apply).

    Not event-sourced: inventory_items.quantity remains authoritative (mutable cache). Movements are an
    append-only audit log alongside that state, not a derived projection that replaces quantity.

    Hybrid model (Option B): ledger rows use canonical item.unit; optional converted_from_unit in metadata
    when the client sent quantity_unit. WASTAGE movements link source_wastage_id -> inventory_wastage.id
    (unique) to prevent double ledger rows.

    Drift between quantity and SUM(movements) is not enforced by the DB; see scripts/inventory_quantity_drift_check.sql
    and future jobs/triggers/repository-only writes if you need hard invariants.

    Optional idempotency_key with canonical payload hash prevents duplicate disposal on client retries.
    Confirm/dispose UI pages are not a security boundary; validation and tenancy are enforced only here.

    quantity_wasted is in InventoryItem.unit unless optional quantity_unit (or unit) is sent; then it is
    converted with are_units_compatible / convert_to_inventory_unit_decimal.

    On-hand quantity is stored as NUMERIC(18,4). Each line also appends an inventory_movements row
    (WASTAGE, signed quantity) for replay and reconciliation; InventoryWastage remains the wastage slice.
    """
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    entries = data.get("entries")
    if not entries or not isinstance(entries, list):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "entries (array of {inventory_item_id, quantity_wasted}) required",
                    "error_code": "ENTRIES_REQUIRED",
                    "errors": [],
                    "wastage_records": [],
                }
            ),
            400,
        )

    if len(entries) > MAX_WASTAGE_BATCH_ENTRIES:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"At most {MAX_WASTAGE_BATCH_ENTRIES} entries per request",
                    "error_code": "BATCH_TOO_LARGE",
                    "errors": [],
                    "wastage_records": [],
                }
            ),
            400,
        )

    idem_key_raw = data.get("idempotency_key")
    idem_key: str | None = None
    if idem_key_raw is not None:
        if not isinstance(idem_key_raw, str) or not idem_key_raw.strip() or len(idem_key_raw) > 128:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "idempotency_key must be a non-empty string at most 128 characters",
                        "error_code": "IDEMPOTENCY_KEY_INVALID",
                        "errors": [],
                        "wastage_records": [],
                    }
                ),
                400,
            )
        idem_key = idem_key_raw.strip()

    parse_errors: list[str] = []
    lines: list[tuple[int, UUID, Decimal, str | None, str]] = []
    seen_ids: set[UUID] = set()

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            parse_errors.append(f"Entry {idx + 1}: must be an object")
            continue
        item_id_str = entry.get("inventory_item_id")
        qty_wasted = entry.get("quantity_wasted")
        if not item_id_str:
            parse_errors.append(f"Entry {idx + 1}: inventory_item_id required")
            continue
        try:
            item_id = UUID(item_id_str)
        except (ValueError, TypeError):
            parse_errors.append(f"Entry {idx + 1}: invalid inventory_item_id")
            continue
        if item_id in seen_ids:
            parse_errors.append(f"Entry {idx + 1}: duplicate inventory_item_id in the same request")
            continue
        seen_ids.add(item_id)
        waste_decimal, qty_err = parse_wastage_quantity(qty_wasted)
        if qty_err:
            parse_errors.append(f"Entry {idx + 1}: {qty_err}")
            continue
        raw_unit = entry.get("quantity_unit")
        if raw_unit is None:
            raw_unit = entry.get("unit")
        parsed_unit, u_err = parse_wastage_unit_field(raw_unit)
        if u_err:
            parse_errors.append(f"Entry {idx + 1}: {u_err}")
            continue
        reason = (entry.get("reason") or "").replace("\x00", "").strip()
        if not reason:
            parse_errors.append(f"Entry {idx + 1}: reason is required")
            continue
        if len(reason) > 500:
            parse_errors.append(f"Entry {idx + 1}: reason must be 500 characters or fewer")
            continue
        lines.append((idx + 1, item_id, waste_decimal, parsed_unit, reason))

    if parse_errors:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Validation failed",
                    "error_code": "VALIDATION_FAILED",
                    "errors": parse_errors,
                    "wastage_records": [],
                }
            ),
            400,
        )

    lines.sort(key=lambda t: t[1])
    hash_for_idem = wastage_entries_payload_hash(
        [
            {"inventory_item_id": item_id, "quantity_wasted": w, "quantity_unit": u or "", "reason": r}
            for _i, item_id, w, u, r in lines
        ]
    )

    inventory_repo = InventoryRepository(db_session)
    recorded_by = getattr(g, "user_email", None) or getattr(g, "username", None)

    try:
        if idem_key:
            _pg_advisory_lock_wastage_idempotency(db_session, org_id, idem_key)
            existing = (
                db_session.query(ApiIdempotencyKey)
                .filter(ApiIdempotencyKey.org_id == org_id, ApiIdempotencyKey.key == idem_key)
                .one_or_none()
            )
            if existing:
                if existing.payload_hash != hash_for_idem:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Idempotency key already used with a different payload",
                                "error_code": "IDEMPOTENCY_PAYLOAD_MISMATCH",
                                "errors": [],
                                "wastage_records": [],
                            }
                        ),
                        409,
                    )
                stored = json.loads(existing.response_json)
                if isinstance(stored, dict):
                    stored = {**stored, "idempotent_replay": True}
                return jsonify(stored), existing.http_status

        validation_errors: list[str] = []
        staged: list[tuple[InventoryItem, Decimal, int, str | None, str]] = []

        # Per-item FOR UPDATE lock with per-entry error accumulation (validation_errors
        # above); batching would change lock-acquisition order and continue-on-error
        # semantics for a small, bounded per-request wastage batch.
        for entry_idx, item_id, waste_decimal, req_unit, reason in lines:
            # nosemgrep: repository-get-in-for-loop
            item = inventory_repo.get_inventory_item_by_id_for_update(item_id, org_id)
            if not item:
                # A rejected lookup here is a tenant-boundary probe as much as a stale/
                # mistyped id, and the response is an ordinary 400 either way (AC15: never
                # distinguishable) — so without this it leaves no trace at all. Same
                # `access_denied` event name as inventory_repo.py/permissions.py so one
                # query covers all of them.
                logger.warning(
                    "access_denied",
                    reason="inventory_item_not_found_or_cross_org",
                    feature="wastage",
                    org_id=str(org_id),
                    inventory_item_id=str(item_id),
                    path=request.path,
                )
                validation_errors.append(f"Entry {entry_idx}: inventory item not found or access denied")
                continue
            current_qty = parse_stored_quantity_to_decimal(item.quantity)
            if current_qty <= 0:
                validation_errors.append(f"Entry {entry_idx}: item has no quantity to waste")
                continue
            inv_unit = (item.unit or "units").strip() or "units"
            if req_unit:
                if not are_units_compatible(req_unit, inv_unit):
                    validation_errors.append(
                        f"Entry {entry_idx}: quantity_unit is not compatible with inventory unit ({inv_unit})"
                    )
                    continue
                try:
                    waste_in_inv = convert_to_inventory_unit_decimal(waste_decimal, req_unit, inv_unit)
                except ValueError as exc:
                    validation_errors.append(f"Entry {entry_idx}: {exc}")
                    continue
            else:
                waste_in_inv = waste_decimal
            if waste_in_inv > current_qty:
                validation_errors.append(
                    f"Entry {entry_idx}: quantity_wasted exceeds available quantity ({current_qty} {inv_unit} on hand)"
                )
                continue
            staged.append((item, waste_in_inv, entry_idx, req_unit, reason))

        if validation_errors:
            db_session.rollback()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Validation failed",
                        "error_code": "VALIDATION_FAILED",
                        "errors": validation_errors,
                        "wastage_records": [],
                    }
                ),
                400,
            )

        result_records = []
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.WASTAGE_RECORD):
            for item, waste_decimal, _entry_idx, request_unit, reason in staged:
                actual_waste = waste_decimal
                current_qty = parse_stored_quantity_to_decimal(item.quantity)
                new_qty = current_qty - actual_waste
                unit = (item.unit or "units").strip() or "units"
                item.quantity = coerce_stored_quantity(new_qty)
                record = InventoryWastage(
                    org_id=org_id,
                    inventory_item_id=item.id,
                    quantity_wasted=str(actual_waste),
                    unit=unit,
                    reason=reason,
                    recorded_by=recorded_by,
                )
                db_session.add(record)
                db_session.flush()
                movement_meta: dict = {"wastage_record_id": str(record.id)}
                if idem_key:
                    movement_meta["idempotency_key"] = idem_key
                if request_unit:
                    movement_meta["converted_from_unit"] = request_unit
                    movement_meta["canonical_unit"] = unit
                assert_movement_unit_matches_item_canonical(unit, item.unit or "units")
                db_session.add(
                    InventoryMovement(
                        org_id=org_id,
                        inventory_item_id=item.id,
                        source_wastage_id=record.id,
                        movement_type=InventoryMovementType.WASTAGE.value,
                        quantity=coerce_stored_quantity(-actual_waste),
                        unit=unit,
                        movement_metadata=movement_meta,
                    )
                )
                result_records.append(
                    {
                        "id": str(record.id),
                        "inventory_item_id": str(item.id),
                        "item_name": item.name,
                        "quantity_wasted": str(actual_waste),
                        "unit": unit,
                        "reason": reason,
                        "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
                    }
                )

        response_body = {
            "success": True,
            "wastage_records": result_records,
            "errors": [],
            "idempotent_replay": False,
        }
        http_status = 201
        if idem_key:
            db_session.add(
                ApiIdempotencyKey(
                    org_id=org_id,
                    key=idem_key,
                    payload_hash=hash_for_idem,
                    response_json=json.dumps(response_body),
                    http_status=http_status,
                )
            )

        try:
            db_session.commit()
        except IntegrityError:
            db_session.rollback()
            if idem_key:
                existing = (
                    db_session.query(ApiIdempotencyKey)
                    .filter(ApiIdempotencyKey.org_id == org_id, ApiIdempotencyKey.key == idem_key)
                    .one_or_none()
                )
                if existing and existing.payload_hash == hash_for_idem:
                    stored = json.loads(existing.response_json)
                    if isinstance(stored, dict):
                        stored = {**stored, "idempotent_replay": True}
                    return jsonify(stored), existing.http_status
            logger.warning("inventory_wastage commit conflict org_id=%s", org_id)
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Conflict recording wastage",
                        "error_code": "CONFLICT_RECORDING_WASTAGE",
                        "errors": [],
                        "wastage_records": [],
                    }
                ),
                409,
            )

        audit_payload = {
            "event": "inventory_wastage_recorded",
            "org_id": str(org_id),
            "inventory_item_ids": [r["inventory_item_id"] for r in result_records],
            "quantities_wasted": [r["quantity_wasted"] for r in result_records],
            "units": [r["unit"] for r in result_records],
            "recorded_by": recorded_by,
            "idempotency_key": idem_key,
            "entry_count": len(result_records),
        }
        logger.info("inventory_wastage_recorded %s", json.dumps(audit_payload, separators=(",", ":")))

        return jsonify(response_body), http_status

    except Exception as e:
        db_session.rollback()
        logger.exception("inventory_wastage failed: %s", e)
        payload = {
            "success": False,
            "error": "Failed to record wastage",
            "error_code": "INTERNAL_ERROR",
            "errors": [],
            "wastage_records": [],
        }
        if not config.is_production:
            payload["details"] = str(e)
        return jsonify(payload), 500


@requires_auth
def list_wastage():
    """List wastage records for sourcemap/trace. Optional ?inventory_item_id= for single item."""
    org_id = UUID(g.org_id)
    item_id_str = request.args.get("inventory_item_id")
    inventory_item_id = None
    if item_id_str:
        try:
            inventory_item_id = UUID(item_id_str)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid inventory_item_id"}), 400
    repo = WastageRepository(db_session)
    records = repo.list_wastage_records(org_id=org_id, inventory_item_id=inventory_item_id)
    items_by_id = {}
    if records:
        item_ids = {r.inventory_item_id for r in records}
        fetched = (
            db_session.query(InventoryItem).filter(InventoryItem.id.in_(item_ids), InventoryItem.org_id == org_id).all()
        )
        items_by_id = {str(item.id): {"name": item.name, "unit": item.unit} for item in fetched}
    result = []
    for r in records:
        info = items_by_id.get(str(r.inventory_item_id)) or {}
        result.append(
            {
                "id": str(r.id),
                "inventory_item_id": str(r.inventory_item_id),
                "item_name": info.get("name") or "Unknown",
                "quantity_wasted": r.quantity_wasted,
                "unit": r.unit,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                "recorded_by": r.recorded_by,
                "reason": r.reason,
            }
        )
    return jsonify({"wastage_records": result}), 200

def register_routes(bp):
    """Keep Core URLs and endpoint names while the wastage code lives in its slice."""
    bp.add_url_rule("/core/inventory/dispose", view_func=inventory_dispose, methods=["GET"])
    bp.add_url_rule("/core/inventory/dispose/confirm", view_func=inventory_dispose_confirm, methods=["GET"])
    bp.add_url_rule("/api/core/inventory/wastage", view_func=record_wastage, methods=["POST"])
    bp.add_url_rule("/api/core/inventory/wastage", view_func=list_wastage, methods=["GET"])
