"""Routes for inventory upload: config/units, CSV validate/commit, barcode decode.

Design (no float, single unit path, preserve quantity string):
- Quantity: validated with Decimal only; sanitized original string is stored (no str(float(...))).
- Unit: single gate _unit_to_canonical(); no separate allowed-unit predicate.
- Validation: _validate_row() used for both preview and commit; returns (status, message, canonical_unit, quantity_str_for_storage).
"""

import csv
import io
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import g, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.security.permissions import requires_auth
from app.core.utils.unit_conversion import CONVERSION_FACTORS, UNIT_DISPLAY_LABELS

logger = logging.getLogger(__name__)

# Max CSV file size (2MB)
CSV_MAX_BYTES = 2 * 1024 * 1024
# Max rows per CSV (validation and commit)
CSV_MAX_ROWS = 500


def _allowed_units_list():
    """Return list of { value, label } for dropdown from unit_conversion (single source of truth)."""
    # Prefer display form for common units (L, mL)
    display_prefer = {"l": "L", "ml": "mL"}
    out = []
    for key in sorted(CONVERSION_FACTORS.keys()):
        value = display_prefer.get(key, key)
        label = UNIT_DISPLAY_LABELS.get(key, value)
        out.append({"value": value, "label": label})
    return out


def _normalize_unit(u: str) -> str:
    if not u:
        return ""
    return (u or "").strip().lower()


def _unit_to_canonical(unit: str) -> str | None:
    """Single authoritative unit validator: raw unit → normalize → canonical mapping or None (reject)."""
    u = _normalize_unit(unit)
    if not u or u not in CONVERSION_FACTORS:
        if unit and unit.strip() in ("L", "mL"):
            return unit.strip()
        return None
    display_prefer = {"l": "L", "ml": "mL"}
    return display_prefer.get(u, u)


def _parse_quantity(qty_str: str) -> tuple[bool, str | None]:
    """Validate quantity with Decimal; return (ok, sanitized_original_str or None). Preserves precision."""
    s = (qty_str or "").strip()
    if not s:
        return False, None
    try:
        d = Decimal(s)
        if d <= 0:
            return False, None
        return True, s
    except InvalidOperation:
        return False, None


def _validate_row(name: str, qty_str: str, unit_raw: str) -> tuple[str, str, str | None, str | None]:
    """Shared validation for preview and commit. Returns (status, message, canonical_unit, quantity_str_for_storage)."""
    if not name:
        return "error", "Item name is required", None, None
    ok, quantity_str = _parse_quantity(qty_str)
    if not ok:
        if not (qty_str or "").strip():
            return "error", "Quantity is required", None, None
        return "error", "Invalid quantity (must be a positive number)", None, None
    if not (unit_raw or "").strip():
        return "error", "Unit is required", None, None
    canonical_unit = _unit_to_canonical(unit_raw)
    if canonical_unit is None:
        return "error", "Unit not allowed", None, None
    return "ok", "", canonical_unit, quantity_str


def _parse_date(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _sanitize(s: str, max_len: int = 500) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    return s[:max_len] if len(s) > max_len else s


def register_routes(bp):
    @bp.route("/api/core/config/units", methods=["GET"])
    @requires_auth
    def get_allowed_units():
        """Return allowed units for inventory (for dropdowns)."""
        return jsonify({"units": _allowed_units_list()})

    @bp.route("/api/core/inventory/csv-validate", methods=["POST"])
    @requires_auth
    def csv_validate():
        """Parse and validate CSV; return rows and per-row validation. No commit.

        Validation checks:
        - File: max 2MB, UTF-8 encoding.
        - Required columns: Item Name, Quantity, Unit (case-insensitive headers).
        - Item Name: required, sanitized (control chars removed), max 255 chars.
        - Quantity: required, must be numeric, must be > 0.
        - Unit: required, must be in allowed list (see unit_conversion.CONVERSION_FACTORS).
        - Optional columns: Supplier Name, Purchase Date, Batch Number, Expiry Date.
        - Dates: parsed as YYYY-MM-DD, DD/MM/YYYY, or MM/DD/YYYY; invalid dates left empty.
        - On commit (csv_commit): same checks re-applied; duplicate batch (same org + name + batch number) rejected.
        """
        file = request.files.get("file")
        raw = request.get_data(as_text=True) if not file else None
        if file:
            content = file.read()
            if len(content) > CSV_MAX_BYTES:
                return jsonify({"error": "File too large. Maximum size is 2MB."}), 400
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                return jsonify({"error": "File must be UTF-8 encoded."}), 400
        elif raw is not None:
            text = raw
        else:
            return jsonify({"error": "Provide 'file' (multipart) or request body as CSV text."}), 400

        reader = csv.DictReader(io.StringIO(text))
        # Normalize headers: strip and case-insensitive match
        required = {"item name": "name", "quantity": "qty", "unit": "unit"}
        optional = {
            "supplier name": "supplier",
            "purchase date": "purchase_date",
            "batch number": "batch_number",
            "expiry date": "expiry_date",
        }
        col_map = {}
        for h in reader.fieldnames or []:
            key = (h or "").strip().lower()
            if key in required:
                col_map[required[key]] = h
            elif key in optional:
                col_map[optional[key]] = h

        missing = [k for k in required if required[k] not in col_map]
        if missing:
            return jsonify({"error": f"Missing required columns: {', '.join(missing)}"}), 400

        rows = []
        validation = []
        truncated = False
        for i, row in enumerate(reader):
            if i >= CSV_MAX_ROWS:
                truncated = True
                break
            row_index = i + 2  # 1-based + header
            name = _sanitize(row.get(col_map["name"], ""), 255)
            qty_str = (row.get(col_map["qty"], "") or "").strip()
            unit_raw = (row.get(col_map["unit"], "") or "").strip()
            supplier = _sanitize(row.get(col_map.get("supplier") or "", ""), 255) or None
            purchase_date = _parse_date(row.get(col_map.get("purchase_date") or ""))
            batch_number = _sanitize(row.get(col_map.get("batch_number") or "", ""), 255) or None
            expiry_date = _parse_date(row.get(col_map.get("expiry_date") or ""))

            status, message, canonical_unit, quantity_str_for_storage = _validate_row(name, qty_str, unit_raw)
            unit = canonical_unit if canonical_unit else unit_raw

            validation.append({"row_index": row_index, "status": status, "message": message})
            rows.append(
                {
                    "row_index": row_index,
                    "name": name,
                    "quantity": quantity_str_for_storage or qty_str,
                    "unit": unit,
                    "supplier": supplier,
                    "purchase_date": purchase_date.isoformat() if purchase_date else None,
                    "batch_number": batch_number,
                    "expiry_date": expiry_date.isoformat() if expiry_date else None,
                }
            )

        return jsonify(
            {
                "rows": rows,
                "validation": validation,
                "allowed_units": _allowed_units_list(),
                "validated_count": len(rows),
                "truncated": truncated,
                "max_rows_allowed": CSV_MAX_ROWS,
            }
        )

    @bp.route("/api/core/inventory/csv-commit", methods=["POST"])
    @requires_auth
    def csv_commit():
        """Commit validated CSV rows as inventory items. Re-validates on backend."""
        org_id = UUID(g.org_id)
        data = request.get_json()
        if not data or not isinstance(data.get("rows"), list):
            return jsonify({"error": "Expected JSON body with 'rows' array."}), 400

        rows = data["rows"]
        if len(rows) > CSV_MAX_ROWS:
            return jsonify({"error": f"Maximum {CSV_MAX_ROWS} rows per upload."}), 400

        repo = InventoryRepository(db_session)
        errors = []
        # Phase 1: validate all rows with shared logic; do not create yet
        validated = []
        for r in rows:
            name = _sanitize(r.get("name"), 255)
            qty_str = (r.get("quantity") or "").strip()
            unit_raw = (r.get("unit") or "").strip()
            status, message, canonical_unit, quantity_str_for_storage = _validate_row(name, qty_str, unit_raw)
            if status != "ok":
                errors.append({"row_index": r.get("row_index"), "error": message or "Validation failed"})
                continue
            validated.append(
                {
                    "row": r,
                    "name": name,
                    "quantity_str": quantity_str_for_storage,
                    "canonical_unit": canonical_unit,
                }
            )

        if errors:
            return jsonify({"error": "Validation failed.", "created": [], "errors": errors}), 400

        # Optional pre-commit duplicate detection for clearer UX (DB constraint remains authoritative)
        for v in validated:
            batch_number = _sanitize(v["row"].get("batch_number"), 255) or None
            if batch_number:
                exists = (
                    db_session.query(InventoryItem.id)
                    .filter(
                        InventoryItem.org_id == org_id,
                        InventoryItem.name == v["name"],
                        InventoryItem.supplier_batch_number == batch_number,
                    )
                    .limit(1)
                    .first()
                )
                if exists:
                    return jsonify(
                        {
                            "error": "Duplicate batch number (org + name + batch already exists). No rows committed.",
                            "created": [],
                            "errors": [
                                {
                                    "row_index": v["row"].get("row_index"),
                                    "error": "Duplicate batch (org + name + batch already exists)",
                                }
                            ],
                        }
                    ), 409

        logger.info(
            "CSV commit batch start org_id=%s source=csv_upload rows=%d",
            org_id,
            len(validated),
        )
        created = []
        for v in validated:
            r = v["row"]
            name = v["name"]
            quantity_str = v["quantity_str"]
            canonical_unit = v["canonical_unit"]
            purchase_date = _parse_date(r.get("purchase_date") or "")
            expiry_date = _parse_date(r.get("expiry_date") or "")
            supplier = _sanitize(r.get("supplier"), 255) or None
            batch_number = _sanitize(r.get("batch_number"), 255) or None

            extra_data = {
                "inventory_audit_history": [
                    {
                        "user_id": str(g.user_id) if getattr(g, "user_id", None) else None,
                        "timestamp_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "source_method": "csv_upload",
                        "csv_row_index": r.get("row_index"),
                    }
                ]
            }

            item = repo.create_inventory_item(
                org_id=org_id,
                name=name,
                quantity=quantity_str,
                unit=canonical_unit,
                inventory_type=InventoryType.RAW_MATERIAL.value,
                supplier=supplier,
                purchase_date=purchase_date,
                supplier_batch_number=batch_number,
                expiry_date=expiry_date,
                extra_data=extra_data,
                commit=False,
            )
            created.append(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "row_index": r.get("row_index"),
                }
            )

        try:
            db_session.commit()
            logger.info(
                "CSV commit batch success org_id=%s source=csv_upload created=%d",
                org_id,
                len(created),
            )
        except IntegrityError:
            db_session.rollback()
            logger.warning(
                "CSV commit batch rollback (duplicate) org_id=%s source=csv_upload",
                org_id,
            )
            return jsonify(
                {
                    "error": "Duplicate batch number (org + name + batch already exists). No rows committed.",
                    "created": [],
                    "errors": [{"error": "Duplicate batch (unique constraint)"}],
                }
            ), 409
        except Exception:
            db_session.rollback()
            logger.exception("CSV commit batch rollback (exception) org_id=%s source=csv_upload", org_id)
            return jsonify({"error": "Commit failed; no rows committed.", "created": [], "errors": []}), 500

        return jsonify({"created": created, "errors": []})

    @bp.route("/api/core/inventory/decode-barcode", methods=["POST"])
    @requires_auth
    def decode_barcode():
        """Barcode decoding is done in the browser (BarcodeDetector + ZXing). This endpoint is deprecated."""
        logger.warning(
            "Deprecated decode-barcode endpoint accessed; client should use scanner UI (user_id=%s)",
            getattr(g, "user_id", None),
        )
        return (
            jsonify(
                {
                    "error": "Barcode decoding is performed in the browser. Use the scanner UI; no server-side decoding.",
                }
            ),
            410,
        )
