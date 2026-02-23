"""Routes for inventory upload: config/units, CSV validate/commit, barcode decode."""

import csv
import io
import re
from datetime import datetime
from uuid import UUID

from flask import g, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.core.db import db_session
from app.core.db.models.inventory_item import InventoryType
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.security.permissions import requires_auth
from app.core.utils.unit_conversion import CONVERSION_FACTORS

# Max CSV file size (2MB)
CSV_MAX_BYTES = 2 * 1024 * 1024
# Max rows per CSV (validation and commit)
CSV_MAX_ROWS = 500

# Display labels for dropdown (value -> label); keys match CONVERSION_FACTORS where applicable
UNIT_LABELS = {
    "kg": "Kilograms (kg)",
    "g": "Grams (g)",
    "mg": "Milligrams (mg)",
    "lb": "Pounds (lb)",
    "oz": "Ounces (oz)",
    "ton": "Ton (ton)",
    "tonne": "Tonne",
    "L": "Liters (L)",
    "l": "Liters (L)",
    "mL": "Milliliters (mL)",
    "ml": "Milliliters (mL)",
    "gal": "Gallons (gal)",
    "m3": "Cubic meters (m³)",
    "ft3": "Cubic feet (ft³)",
    "m": "Meters (m)",
    "cm": "Centimeters (cm)",
    "mm": "Millimeters (mm)",
    "ft": "Feet (ft)",
    "in": "Inches (in)",
    "units": "Units",
    "pcs": "Pieces",
    "pieces": "Pieces",
    "boxes": "Boxes",
    "pallets": "Pallets",
    "containers": "Containers",
}


def _allowed_units_list():
    """Return list of { value, label } for dropdown from CONVERSION_FACTORS (unit_conversion.py)."""
    # Prefer display form for common units (L, mL)
    display_prefer = {"l": "L", "ml": "mL"}
    out = []
    for key in sorted(CONVERSION_FACTORS.keys()):
        value = display_prefer.get(key, key)
        label = UNIT_LABELS.get(value) or UNIT_LABELS.get(key) or value
        out.append({"value": value, "label": label})
    return out


def _is_allowed_unit(unit: str) -> bool:
    u = _normalize_unit(unit)
    if u in CONVERSION_FACTORS:
        return True
    if unit and unit.strip() in ("L", "mL"):
        return True
    return False


def _normalize_unit(u: str) -> str:
    if not u:
        return ""
    return (u or "").strip().lower()


def _unit_to_canonical(unit: str) -> str | None:
    """Map normalized unit to a canonical display value from allowed list, or None if not allowed."""
    u = _normalize_unit(unit)
    if not u or u not in CONVERSION_FACTORS:
        if unit and unit.strip() in ("L", "mL"):
            return unit.strip()
        return None
    display_prefer = {"l": "L", "ml": "mL"}
    return display_prefer.get(u, u)


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
        org_id = UUID(g.org_id)
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
        fieldnames = reader.fieldnames or []
        # Normalize headers: strip and case-insensitive match
        required = {"item name": "name", "quantity": "qty", "unit": "unit"}
        optional = {
            "supplier name": "supplier",
            "purchase date": "purchase_date",
            "batch number": "batch_number",
            "expiry date": "expiry_date",
        }
        col_map = {}
        for h in fieldnames:
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
            supplier = (_sanitize(row.get(col_map.get("supplier") or "", "") or "", 255) or None)
            purchase_date = _parse_date(row.get(col_map.get("purchase_date") or "", "") or "")
            batch_number = (_sanitize(row.get(col_map.get("batch_number") or "", "") or "", 255) or None)
            expiry_date = _parse_date((row.get(col_map.get("expiry_date")) or ""))

            status = "ok"
            message = ""
            if not name:
                status = "error"
                message = "Item name is required"
            try:
                qty = float(qty_str)
                if qty <= 0:
                    status = "error"
                    message = "Quantity must be greater than 0"
            except (TypeError, ValueError):
                status = "error"
                message = "Invalid quantity"

            if not unit_raw:
                status = "error"
                message = message or "Unit is required"
            elif not _is_allowed_unit(unit_raw):
                status = "error"
                message = message or "Unit not allowed"

            # Normalize unit for storage (match an allowed value from full list)
            unit = unit_raw
            if unit_raw and status == "ok":
                ul = _normalize_unit(unit_raw)
                for item in _allowed_units_list():
                    v = item["value"]
                    if (v.lower() == ul) or (v == unit_raw) or (v == unit_raw.strip()):
                        unit = v
                        break

            validation.append({"row_index": row_index, "status": status, "message": message})
            rows.append({
                "row_index": row_index,
                "name": name,
                "quantity": qty_str,
                "unit": unit,
                "supplier": supplier,
                "purchase_date": purchase_date.isoformat() if purchase_date else None,
                "batch_number": batch_number,
                "expiry_date": expiry_date.isoformat() if expiry_date else None,
            })

        return jsonify({
            "rows": rows,
            "validation": validation,
            "allowed_units": _allowed_units_list(),
            "truncated": truncated,
        })

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
        # Phase 1: validate all rows; do not create yet
        for r in rows:
            name = _sanitize(r.get("name"), 255)
            qty_str = (r.get("quantity") or "").strip()
            unit_raw = (r.get("unit") or "").strip()
            if not name or not unit_raw:
                errors.append({"row_index": r.get("row_index"), "error": "Missing name or unit"})
                continue
            canonical_unit = _unit_to_canonical(unit_raw)
            if not _is_allowed_unit(unit_raw) or canonical_unit is None:
                errors.append({"row_index": r.get("row_index"), "error": "Invalid unit"})
                continue
            try:
                qty = float(qty_str)
                if qty <= 0:
                    errors.append({"row_index": r.get("row_index"), "error": "Quantity must be > 0"})
                    continue
            except (TypeError, ValueError):
                errors.append({"row_index": r.get("row_index"), "error": "Invalid quantity"})
                continue

        if errors:
            return jsonify({"error": "Validation failed.", "created": [], "errors": errors}), 400

        # Phase 2: all rows valid — create all in one transaction (atomic batch)
        created = []
        for r in rows:
            name = _sanitize(r.get("name"), 255)
            qty_str = (r.get("quantity") or "").strip()
            unit_raw = (r.get("unit") or "").strip()
            canonical_unit = _unit_to_canonical(unit_raw)
            try:
                qty = float(qty_str)
            except (TypeError, ValueError):
                qty = 0
            purchase_date = _parse_date(r.get("purchase_date") or "")
            expiry_date = _parse_date(r.get("expiry_date") or "")
            supplier = _sanitize(r.get("supplier"), 255) or None
            batch_number = _sanitize(r.get("batch_number"), 255) or None

            # Quantity stored as string per InventoryItem model (preserves precision).
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
                quantity=str(qty),
                unit=canonical_unit,
                inventory_type=InventoryType.RAW_MATERIAL.value,
                supplier=supplier,
                purchase_date=purchase_date,
                supplier_batch_number=batch_number,
                expiry_date=expiry_date,
                extra_data=extra_data,
                commit=False,
            )
            created.append({
                "id": str(item.id),
                "name": item.name,
                "quantity": item.quantity,
                "unit": item.unit,
                "row_index": r.get("row_index"),
            })

        try:
            db_session.commit()
        except IntegrityError:
            db_session.rollback()
            return jsonify({
                "error": "Duplicate batch number (org + name + batch already exists). No rows committed.",
                "created": [],
                "errors": [{"error": "Duplicate batch (unique constraint)"}],
            }), 409
        except Exception as e:
            db_session.rollback()
            return jsonify({"error": "Commit failed; no rows committed.", "created": [], "errors": []}), 500

        return jsonify({"created": created, "errors": []})

    @bp.route("/api/core/inventory/decode-barcode", methods=["POST"])
    @requires_auth
    def decode_barcode():
        """Barcode decoding is done in the browser (BarcodeDetector + ZXing). This endpoint is deprecated."""
        return (
            jsonify({
                "error": "Barcode decoding is performed in the browser. Use the scanner UI; no server-side decoding.",
            }),
            410,
        )
