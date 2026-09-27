"""Core backend API routes for process execution platform"""

import base64
import functools
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.routes.auth_routes import limiter
from app.core.backend import (
    changes_feed,
    corechecks,
    execution_routes,
    inventory_routes,
    inventory_upload_routes,
    process_design_routes,
    reconciliation_routes,
    suppliers,
    tasks,
    traceability_routes,
)
from app.core.backend.evidence import evidence_routes
from app.core.backend.process_docs import process_docs_routes
from app.core.backend.static_assets import core_asset_directory, iter_core_assets
from app.core.db import db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.wastage_repo import WastageRepository
from app.core.domain.expiry_rules import assert_warning_within_expiry
from app.core.domain.inventory_quantity_guard import (
    InventoryQuantityWriteReason,
    allow_inventory_quantity_write,
)
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
from app.features.activity_log.routes import activity_routes
from app.features.dashboard.routes import dashboard_routes
from app.features.demo_data.routes import api_routes as demo_data_routes
from app.features.demo_data.services.resetdb import DEMO_USER_EMAIL
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)
_EXECUTION_DATA_TRACE_KEYS = execution_routes._EXECUTION_DATA_TRACE_KEYS


def _product_available(feature: str) -> bool:
    """Whether an optional product completed registration in this app instance."""
    return bool(current_app.extensions.get("product_availability", {}).get(feature, False))


# Guardrail: batch size caps row-lock duration under concurrent SELECT ... FOR UPDATE.
MAX_WASTAGE_BATCH_ENTRIES = 100

# Opt-in keyset pagination for the big list endpoints (executions, inventory). A caller
# that passes no ?limit gets the full list exactly as before -- every existing consumer
# (process pickers, sourcemap, reconciliation, the dispose flow) is unchanged. Only the
# /core hub tabs pass a limit. Cursor is an opaque base64url("<created_at_iso>|<id>") of
# the last row returned; the sort is (created_at DESC, id DESC).
LIST_PAGE_MAX = 50

# Upper bound on the (id, name) process list embedded in /api/core/hub/overview for the
# active-batches picker. A real manufacturer has tens of processes; this only stops the
# payload ballooning on a pathological catalogue.
HUB_PROCESSES_MIN_CAP = 500


def _encode_list_cursor(created_at: datetime, row_id) -> str:
    raw = f"{created_at.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_list_cursor(token: str) -> tuple[datetime, UUID]:
    """Parse a cursor token. Raises ValueError on anything malformed -- the caller turns
    that into a 400 rather than a 500."""
    pad = "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode(token + pad).decode()
    ts_str, id_str = raw.split("|", 1)
    return datetime.fromisoformat(ts_str), UUID(id_str)


def _parse_page_params(args) -> tuple[int | None, tuple[datetime, UUID] | None]:
    """(limit, cursor) from request args. limit is None when the caller wants the full
    list; otherwise it is clamped to [1, LIST_PAGE_MAX]. Raises ValueError for a bad
    limit or cursor."""
    limit_str = args.get("limit")
    if limit_str is None or limit_str == "":
        return None, None
    limit = int(limit_str)  # ValueError -> 400
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, LIST_PAGE_MAX)
    cursor_str = args.get("cursor")
    cursor = _decode_list_cursor(cursor_str) if cursor_str else None
    return limit, cursor


# Create core blueprint
core_bp = Blueprint(
    "core",
    __name__,
    template_folder="../frontend",
    static_folder="../frontend",
    static_url_path="/static",
)


@functools.lru_cache(maxsize=1)
def _asset_version() -> str:
    """Short digest of the bundled JS/CSS files (name + mtime + size), computed once per
    process. Appended as ``?v=`` to serve_core_js / serve_core_css URLs so a deploy that
    ships changed assets busts the browser and CDN cache -- these routes send
    ``Cache-Control: public, max-age=3600`` on otherwise-stable paths, so without this a
    freshly rendered page can run hour-old JS that predates the endpoints it calls."""
    h = hashlib.blake2b(digest_size=8)
    frontend = os.path.join(os.path.dirname(__file__), "..", "frontend")
    for kind, name, directory in iter_core_assets():
        try:
            st = (directory / name).stat()
        except OSError:
            continue
        h.update(f"{kind}/{name}:{int(st.st_mtime)}:{st.st_size}\n".encode())
    for sub in ("inventory_static", "img"):
        directory = os.path.join(frontend, sub)
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            try:
                st = os.stat(os.path.join(directory, name))
            except OSError:
                continue
            h.update(f"{name}:{int(st.st_mtime)}:{st.st_size}\n".encode())
    return h.hexdigest()


_VERSIONED_STATIC_ENDPOINTS = frozenset(
    {
        "core.serve_core_js",
        "core.serve_core_css",
        "core.serve_core_inventory_static",
        "core.serve_core_img",
    }
)


@core_bp.url_defaults
def _core_static_asset_version(endpoint: str, values: dict) -> None:
    if endpoint in _VERSIONED_STATIC_ENDPOINTS and "v" not in values:
        values["v"] = _asset_version()


# --- Flow wizard safety helpers (query filtering + step integrity) ---


def validate_custom_expiry_warning_not_exceed_duration(
    output_name: str,
    duration_value: int | None,
    duration_unit: str,
    warning_value: int | None,
    warning_unit: str,
) -> list[str]:
    """
    Validate that warning period does not exceed expiry period for custom output expiry.
    Delegates to domain rule (single source of truth). Used at execution step completion;
    tests call this to safeguard the validation.
    """
    return assert_warning_within_expiry(output_name, duration_value, duration_unit, warning_value, warning_unit)


# Keys in execution_data that are system/audit (execution_trace), not user prompts


def _to_iso_timestamp(ts) -> str | None:
    """Normalize a timestamp to ISO format string for consistent API output."""
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _split_execution_data(execution_data: dict | None, completed_at=None):
    """
    Split execution_data into user prompts and system trace. Single place for prompt/trace split logic.
    Returns (prompts_dict, trace_dict). Use for extra_data.execution_prompts and extra_data.execution_trace.

    Audit keys (completed_by, completed_by_email, …) are mirrored from persisted execution_data. For HTTP step
    completion, ``_strip_incoming_execution_trace_keys`` drops client-supplied trace keys before merge; identity is
    then set from the authenticated session. Other persistence paths must enforce the same contract.
    """
    if not execution_data:
        return {}, {}
    prompts = {
        k: v for k, v in execution_data.items() if k not in _EXECUTION_DATA_TRACE_KEYS and v is not None and v != ""
    }
    trace = {}
    if execution_data.get("completed_by") is not None:
        trace["completed_by"] = execution_data["completed_by"]
    if execution_data.get("completed_by_email") is not None:
        trace["completed_by_email"] = execution_data["completed_by_email"]
    completed_ts = execution_data.get("completed_at")
    if completed_ts is not None:
        trace["completed_at"] = _to_iso_timestamp(completed_ts)
    elif completed_at is not None:
        trace["completed_at"] = _to_iso_timestamp(completed_at)
    if execution_data.get("entered_at") is not None:
        trace["entered_at"] = _to_iso_timestamp(execution_data["entered_at"])
    if execution_data.get("execution_errors") is not None:
        trace["execution_errors"] = execution_data["execution_errors"]
    if execution_data.get("execution_warnings") is not None:
        trace["execution_warnings"] = execution_data["execution_warnings"]
    return prompts, trace


@core_bp.route("/core", methods=["GET"])
@requires_auth
def core():
    """Serve the core2.html frontend page"""
    user_email = getattr(g, "user_email", None)
    show_reset_db = config.environment in ("test", "local") and user_email == DEMO_USER_EMAIL
    return render_template("core/core2.html", active_page="core", show_reset_db=show_reset_db)


@core_bp.route("/core/integrations", methods=["GET"])
@requires_auth
def integrations():
    if _product_available("crm"):
        return redirect("/crm/configuration")
    return render_template("integrations/integrations.html", active_page="integrations")


@core_bp.route("/core/settings", methods=["GET"])
@requires_auth
def settings():
    return render_template("settings/settings.html", active_page="settings")


@core_bp.route("/core/inventory/dispose", methods=["GET"])
@requires_auth
def inventory_dispose():
    """Full-page disposal flow for recording inventory wastage."""
    item_ids_param = (request.args.get("item_ids") or "").strip()
    item_ids = [v.strip() for v in item_ids_param.split(",") if v and v.strip()] if item_ids_param else []
    return render_template("inventory/dispose.html", active_page="core", initial_item_ids=item_ids)


@core_bp.route("/core/inventory/dispose/confirm", methods=["GET"])
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


@core_bp.route("/core/notifications", methods=["GET"])
@requires_auth
def notifications_page():
    """Serve system notifications (system findings) as a card list."""
    return render_template("notifications/notifications.html", active_page="core")


@core_bp.route("/core/tasks", methods=["GET"])
@requires_auth
def tasks_page():
    """Keep historical notification links working after Tasks moved into Core."""
    query = request.query_string.decode("utf-8")
    return redirect("/core?tab=tasks" + ("&" + query if query else ""))


@core_bp.route("/core/tasks/configuration", methods=["GET"])
@requires_auth
def tasks_configuration_page():
    return render_template("tasks/configuration.html", active_page="core")


@core_bp.route("/static/js/<filename>")
@limiter.exempt
def serve_core_js(filename):
    """Serve JavaScript files from core frontend (no auth so they load reliably; pages that include them are protected)."""
    from werkzeug.security import safe_join

    # Path traversal protection: reject filenames with .. or /
    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400, "Invalid filename")

    # Extension whitelist for security
    if not filename.lower().endswith(".js"):
        abort(400, "Invalid file type")

    core_frontend_dir = core_asset_directory("js", filename)
    if core_frontend_dir is None:
        abort(404, "File not found")
    # Use safe_join for validation only (not for file access)
    safe_path = safe_join(core_frontend_dir, filename)
    if safe_path is None:
        abort(400, "Invalid filename")

    # File serving must be done exclusively via send_from_directory
    from werkzeug.exceptions import NotFound

    try:
        response = send_from_directory(core_frontend_dir, filename)
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=60"
        # X-Content-Type-Options is set globally in after_request handler
        return response
    except (FileNotFoundError, NotFound):
        # Missing static file - log at info level (not error). On this Werkzeug pin,
        # send_from_directory raises NotFound (an HTTPException), not FileNotFoundError,
        # for a missing file — both are caught here so a missing asset 404s instead of
        # falling into the generic 500 handler below (shell review, security-audit.md).
        logger.info(f"Static JS file not found: {filename} from {core_frontend_dir}")
        # Return 404 - do not fall back to Flask's global static handler
        abort(404, "File not found")
    except Exception:
        # Unexpected exception - log at exception level
        logger.exception(f"Unexpected error serving static JS file: {filename}")
        abort(500, "Internal server error")


@core_bp.route("/static/css/<filename>")
@limiter.exempt
def serve_core_css(filename):
    """Serve CSS files from core frontend (no auth so they load reliably; pages that include them are protected)."""
    from werkzeug.security import safe_join

    # Path traversal protection: reject filenames with .. or /
    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400, "Invalid filename")

    # Extension whitelist for security
    if not filename.lower().endswith(".css"):
        abort(400, "Invalid file type")

    core_frontend_dir = core_asset_directory("css", filename)
    if core_frontend_dir is None:
        abort(404, "File not found")
    # Use safe_join for validation only (not for file access)
    safe_path = safe_join(core_frontend_dir, filename)
    if safe_path is None:
        abort(400, "Invalid filename")

    # File serving must be done exclusively via send_from_directory
    from werkzeug.exceptions import NotFound

    try:
        response = send_from_directory(core_frontend_dir, filename)
        response.headers["Content-Type"] = "text/css; charset=utf-8"
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=60"
        # X-Content-Type-Options is set globally in after_request handler
        return response
    except (FileNotFoundError, NotFound):
        # Missing static file - log at info level (not error). On this Werkzeug pin,
        # send_from_directory raises NotFound (an HTTPException), not FileNotFoundError,
        # for a missing file — both are caught here so a missing asset 404s instead of
        # falling into the generic 500 handler below (shell review, security-audit.md).
        logger.info(f"Static CSS file not found: {filename} from {core_frontend_dir}")
        # Return 404 - do not fall back to Flask's global static handler
        abort(404, "File not found")
    except Exception:
        # Unexpected exception - log at exception level
        logger.exception(f"Unexpected error serving static CSS file: {filename}")
        abort(500, "Internal server error")


_INVENTORY_STATIC_ALLOWLIST = frozenset({"inventory-icon.svg", "inventory-spa-header.css"})
_IMG_STATIC_ALLOWLIST = frozenset({"hero-wave.jpg"})


@core_bp.route("/static/inventory/<filename>")
@limiter.exempt
def serve_core_inventory_static(filename):
    """Serve the two public SVG/CSS assets from core frontend inventory_static/ (used by
    the inventory SPA header partial). That directory holds public assets only -- the
    server-rendered inventory templates live in the sibling inventory/ dir and are never
    reachable through this route or the WhiteNoise layer that fronts it."""
    from werkzeug.security import safe_join

    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400, "Invalid filename")
    if filename not in _INVENTORY_STATIC_ALLOWLIST:
        abort(400, "Invalid file")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".svg", ".css"):
        abort(400, "Invalid file type")

    inventory_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "inventory_static")
    safe_path = safe_join(inventory_dir, filename)
    if safe_path is None:
        abort(400, "Invalid filename")

    from werkzeug.exceptions import NotFound

    try:
        response = send_from_directory(inventory_dir, filename)
        if ext == ".svg":
            response.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
        else:
            response.headers["Content-Type"] = "text/css; charset=utf-8"
        return response
    except (FileNotFoundError, NotFound):
        logger.info("Inventory static file not found: %s", filename)
        abort(404, "File not found")
    except Exception:
        logger.exception("Error serving inventory static: %s", filename)
        abort(500, "Internal server error")


@core_bp.route("/static/img/<filename>")
@limiter.exempt
def serve_core_img(filename):
    """Serve images from core frontend img/ (no auth; used by unauthenticated landing page)."""
    from werkzeug.security import safe_join

    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400, "Invalid filename")
    if filename not in _IMG_STATIC_ALLOWLIST:
        abort(400, "Invalid file")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        abort(400, "Invalid file type")

    img_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "img")
    safe_path = safe_join(img_dir, filename)
    if safe_path is None:
        abort(400, "Invalid filename")

    from werkzeug.exceptions import NotFound

    try:
        response = send_from_directory(img_dir, filename)
        if ext in (".jpg", ".jpeg"):
            response.headers["Content-Type"] = "image/jpeg"
        elif ext == ".png":
            response.headers["Content-Type"] = "image/png"
        elif ext == ".webp":
            response.headers["Content-Type"] = "image/webp"
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    except (FileNotFoundError, NotFound):
        logger.info("Image static file not found: %s", filename)
        abort(404, "File not found")
    except Exception:
        logger.exception("Error serving image static: %s", filename)
        abort(500, "Internal server error")


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


@core_bp.route("/api/core/inventory/wastage", methods=["POST"])
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


@core_bp.route("/api/core/inventory/wastage", methods=["GET"])
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


activity_routes.register_routes(core_bp)
dashboard_routes.register_routes(core_bp)
changes_feed.register_routes(core_bp)
corechecks.register_routes(core_bp)
reconciliation_routes.register_routes(core_bp)
inventory_upload_routes.register_routes(core_bp)
evidence_routes.register_routes(core_bp)
process_docs_routes.register_routes(core_bp)
tasks.register_routes(core_bp)
process_design_routes.register_routes(core_bp)
execution_routes.register_routes(
    core_bp,
    parse_page_params=_parse_page_params,
    encode_list_cursor=_encode_list_cursor,
    split_execution_data=_split_execution_data,
    product_available=_product_available,
    validate_custom_expiry_warning_not_exceed_duration=validate_custom_expiry_warning_not_exceed_duration,
)
inventory_routes.register_routes(
    core_bp,
    parse_page_params=_parse_page_params,
    encode_list_cursor=_encode_list_cursor,
    split_execution_data=_split_execution_data,
)
traceability_routes.register_routes(core_bp)
suppliers.register_routes(core_bp)
demo_data_routes.register_routes(core_bp)


# The app runs in NZ local time (container TZ = Pacific/Auckland) but Postgres sessions
# are UTC, so a naive local-midnight datetime bound into a query is read as UTC midnight --
# which hid the current NZ day's rows from the "today"/"this week" dashboard widgets until
# noon NZ. Boundaries are built tz-aware in this zone so SQLAlchemy binds timestamptz and
# the comparison is correct. Matches system_findings_cache._LOCAL_TZ.


def _hub_active_execution_payload(execution) -> dict:
    """Slim projection of one active execution for /api/core/hub/overview.

    Deliberately a fraction of what /api/core/executions returns: no actual_inputs/outputs,
    no execution_data, no evidence, no event summary -- just what the hub's Active Batches
    pipeline and workflow-readiness widgets read. `current_step` mirrors list_executions:
    the first READY step, numbered by 1-based position within the execution.
    """
    steps = sorted(
        execution.execution_steps or [], key=lambda es: es.step_number
    )  # nosemgrep: orm-relationship-access-in-loop
    ready = [es for es in steps if es.status.value == "ready"]
    completed = sum(1 for es in steps if es.status.value == "completed")
    total_steps = execution.total_steps or (len(steps) if steps else 0)

    current_step = None
    if ready:
        nxt = ready[0]
        try:
            display_index = 1 + next(i for i, es in enumerate(steps) if es.id == nxt.id)
        except StopIteration:
            display_index = nxt.step_number
        current_step = {
            "step_number": display_index,
            "name": nxt.step.name if nxt.step else None,
        }

    return {
        "id": str(execution.id),
        "process_id": str(execution.process_id),
        "process_name": (execution.process.name if execution.process else None) or "Untitled process",
        "status": execution.status.value,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "current_step": current_step,
        "steps": [{"step_number": es.step_number, "status": es.status.value} for es in steps],
        "total_steps": total_steps,
        "progress": (completed / total_steps * 100) if total_steps > 0 else 0,
    }


@core_bp.route("/api/core/hub/overview", methods=["GET"])
@requires_auth
def get_hub_overview():
    """One org-scoped payload for the /core hub's above-the-fold Overview.

    Exists so initial /core navigation makes a single small API call instead of the old
    four-call fan-out (metrics + full processes + fully-enriched inventory + full execution
    history) plus a duplicate processes?include_steps=true from the active-batches graph.
    Every number is an aggregate computed in SQL; the only rows returned are <=20 active
    executions and <=6 traceability-gap items. The Inventory and Workflows tabs still load
    their detailed data lazily on first open -- this endpoint does not replace them.

    See docs/core-load-performance-design.md.
    """
    org_id = UUID(g.org_id)
    now = datetime.now(UTC)
    today = now.date()
    week_ago = now - timedelta(days=7)
    day_ago = now - timedelta(days=1)

    process_repo = ProcessRepository(db_session)
    execution_repo = ExecutionRepository(db_session)
    inventory_repo = InventoryRepository(db_session)

    process_count = process_repo.count_processes(org_id)
    exec_by_status = execution_repo.count_executions_by_status(org_id)
    in_progress = exec_by_status.get(ExecutionStatus.IN_PROGRESS.value, 0)
    pending = exec_by_status.get(ExecutionStatus.PENDING.value, 0)
    completed_total = exec_by_status.get(ExecutionStatus.COMPLETED.value, 0)

    items_by_type = inventory_repo.count_inventory_items_by_type(org_id)
    inv_total = sum(items_by_type.values())

    inv_agg = inventory_repo.hub_overview_aggregates(org_id, today)
    gap_items = inventory_repo.list_traceability_gap_items(org_id, limit=6)
    movement = inventory_repo.movement_totals_since(org_id, day_ago)

    active_execs = execution_repo.list_active_execution_summaries(org_id, limit=20)
    throughput = execution_repo.count_completed_by_process_since(org_id, week_ago)

    # processes_min feeds the active-batches picker. Every process that owns one of the
    # returned active executions MUST be selectable, even if it is older than the newest
    # HUB_PROCESSES_MIN_CAP processes -- otherwise the panel shows an active batch the user
    # cannot open. Seed with those, then fill the rest of the cap with newest processes.
    processes_min: list[dict] = []
    seen_pids: set[str] = set()
    for e in active_execs:
        if e.process and str(e.process.id) not in seen_pids:
            seen_pids.add(str(e.process.id))
            processes_min.append({"id": str(e.process.id), "name": e.process.name or "Untitled process"})
    # One query, evaluated before the loop -- not a per-iteration repository lookup.
    newest_process_names = process_repo.list_process_names(org_id, limit=HUB_PROCESSES_MIN_CAP)
    for pid, name in newest_process_names:
        if str(pid) in seen_pids:
            continue
        if len(processes_min) >= HUB_PROCESSES_MIN_CAP:
            break
        seen_pids.add(str(pid))
        processes_min.append({"id": str(pid), "name": name})
    _pmin_ids = {p["id"] for p in processes_min}

    payload = {
        "generated_at": now.isoformat(),
        "metrics": {
            "total_processes": process_count,
            "active_executions": in_progress,
            "completed_executions": completed_total,
            "inventory_items": {
                "total": inv_total,
                "raw_materials": items_by_type.get(InventoryType.RAW_MATERIAL.value, 0),
                "work_in_progress": items_by_type.get(InventoryType.WORK_IN_PROGRESS.value, 0),
                "final_products": items_by_type.get(InventoryType.FINAL_PRODUCT.value, 0),
            },
        },
        "journey": {
            "has_inventory": inv_total > 0,
            "has_process": process_count > 0,
            "has_execution": (
                in_progress
                + pending
                + completed_total
                + exec_by_status.get("failed", 0)
                + exec_by_status.get("cancelled", 0)
            )
            > 0,
        },
        "inventory": {
            "nonzero_lines": inv_agg["nonzero_lines"],
            "allocated": inv_agg["allocated"],
            "linked": inv_agg["linked"],
            "low_stock": inv_agg["low_stock"],
            "expiry": inv_agg["expiry"],
            "traceability_gaps": [
                {
                    "name": it.name or "Inventory item",
                    "quantity": str(it.quantity),
                    "unit": it.unit or "",
                }
                for it in gap_items
            ],
            "movement_24h": movement,
        },
        "workflows": {
            "in_flight": in_progress + pending,
            "pending": pending,
            # completed_7d is the scalar total over ALL processes (unbounded input, bounded
            # output) -- what the Workflows summary card shows.
            "completed_7d": sum(count for _pid, _name, count in throughput),
            "process_count": process_count,
            # Bounded (HUB_PROCESSES_MIN_CAP) but always contains every active-execution
            # process -- built above.
            "processes_min": processes_min,
            "active_executions": [_hub_active_execution_payload(e) for e in active_execs],
            # Per-process throughput, keyed by process_id (names aren't unique). Its only
            # consumer is the active-batches graph, which looks up the selected process's
            # row -- so it is restricted to the processes actually in the (capped) picker.
            # This keeps the first-paint payload bounded on an org with a huge recipe/SKU
            # catalogue where many processes have a recent completion.
            "throughput_7d": [
                {"process_id": str(pid), "name": name, "count": count}
                for pid, name, count in throughput
                if str(pid) in _pmin_ids
            ],
        },
    }
    return jsonify(payload), 200


def _is_valid_uuid(v: str) -> bool:
    try:
        UUID(v)
        return True
    except (ValueError, AttributeError):
        return False
