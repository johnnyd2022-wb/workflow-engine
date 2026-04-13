"""Core backend API routes for process execution platform"""

import hashlib
import json
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, send_from_directory, session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.routes.auth_routes import limiter
from app.core.backend import corechecks, inventory_upload_routes, reconciliation_routes
from app.core.backend.checks.output_ready_date_check import is_inventory_item_ready_for_consumption
from app.core.backend.evidence import evidence_routes
from app.core.backend.evidence.evidence_service import list_evidence_for_execution
from app.core.backend.process_docs import process_docs_routes
from app.core.backend.reconciliation_service import _find_producing_step
from app.core.db import db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.process import ProcessCategory
from app.core.db.models.step import Step
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.wastage_repo import WastageRepository
from app.core.domain.expiry_ready_date_rules import assert_expiry_after_ready_dates, assert_expiry_after_ready_duration
from app.core.domain.expiry_rules import VALID_EXPIRY_UNITS, assert_warning_within_expiry
from app.core.domain.expiry_rules import duration_to_timedelta as expiry_duration_to_timedelta
from app.core.domain.inventory_quantity_guard import (
    InventoryQuantityWriteReason,
    allow_inventory_quantity_write,
)
from app.core.security.permissions import requires_auth
from app.core.utils.inventory_quantity import (
    assert_movement_unit_matches_item_canonical,
    coerce_stored_quantity,
    parse_stored_quantity_to_decimal,
    quantity_to_api_str,
)
from app.core.utils.inventory_wastage_quantity import (
    parse_wastage_quantity,
    parse_wastage_unit_field,
    wastage_entries_payload_hash,
)
from app.core.utils.log_action import log_action
from app.core.utils.mock_data import DEMO_USER_EMAIL
from app.core.utils.unit_conversion import are_units_compatible, convert_to_inventory_unit_decimal
from app.utils.config_loader import config

logger = logging.getLogger(__name__)

# Guardrail: batch size caps row-lock duration under concurrent SELECT ... FOR UPDATE.
MAX_WASTAGE_BATCH_ENTRIES = 100

# Create core blueprint
core_bp = Blueprint(
    "core",
    __name__,
    template_folder="../frontend",
    static_folder="../frontend",
    static_url_path="/static",
)


# --- Flow wizard safety helpers (query filtering + step integrity) ---
_FLOW_ALLOWED_QUERY_PARAMS = {"id", "fresh"}

_FLOW_WIZARD_PAGE_TO_STEP = {
    "process-overview": 1,
    "step-name": 2,
    "inputs": 3,
    "outputs": 4,
    "evidence-and-prompts": 5,
    "summary": 6,
    "next-steps": 7,
}

_FLOW_WIZARD_STEP_TO_PATH = {
    1: "/core/flows/create/process-overview",
    2: "/core/flows/create/step-name",
    3: "/core/flows/create/inputs",
    4: "/core/flows/create/outputs",
    5: "/core/flows/create/evidence-and-prompts",
    6: "/core/flows/create/summary",
    7: "/core/flows/create/next-steps",
}


def _flow_process_id_from_request() -> UUID | None:
    """Parse and validate ?id= as a UUID. If present but invalid, abort 400."""
    raw = request.args.get("id")
    if raw is None or raw == "":
        return None
    try:
        return UUID(str(raw))
    except Exception:
        abort(400)


def _assert_flow_process_access(process_id: UUID) -> None:
    """
    Object-level authorization for flow pages.
    We scope access to the current tenant org; return 404 when not found to avoid ID enumeration.
    """
    org_raw = getattr(g, "org_id", None)
    if not org_raw:
        abort(400)
    org_id = UUID(str(org_raw))
    repo = ProcessRepository(db_session)
    proc = repo.get_process_by_id(process_id, org_id=org_id)
    if not proc:
        abort(404)


def _get_process_or_404(process_id: UUID):
    """Shared helper for API endpoints: org-scoped process fetch with 404 on miss."""
    org_raw = getattr(g, "org_id", None)
    if not org_raw:
        abort(400)
    org_id = UUID(str(org_raw))
    repo = ProcessRepository(db_session)
    proc = repo.get_process_by_id(process_id, org_id=org_id)
    if not proc:
        abort(404)
    return proc


def _assert_valid_step_write(process_id: UUID, requested_step_number: int | None, step_id: UUID | None = None) -> None:
    """
    Enforce basic flow integrity at the mutation boundary.
    This is not a security boundary (tenancy is handled by org-scoped process lookup),
    but it prevents inconsistent state caused by skipping ahead or colliding step numbers.
    """
    if requested_step_number is None:
        return
    if not isinstance(requested_step_number, int) or requested_step_number < 1:
        abort(400)

    # Ensure process exists in current org (prevents IDOR & guarantees scope).
    _ = _get_process_or_404(process_id)

    q = db_session.query(Step).filter(Step.process_id == process_id)
    if step_id is not None:
        q = q.filter(Step.id != step_id)

    existing_numbers = [n for (n,) in q.with_entities(Step.step_number).all() if isinstance(n, int)]
    # Option B: step_number is not canonical ordering. No uniqueness enforcement here.
    return None


def _coerce_step_position(value):
    if value is None:
        return None
    from decimal import Decimal

    try:
        pos = Decimal(str(value))
    except Exception:
        abort(400)
    # Defensive bounds: reject NaN/Inf and negative/zero positions.
    if not pos.is_finite() or pos <= 0:
        abort(400)
    # Guard against pathological magnitudes (prevents log spam / abuse).
    if pos.copy_abs() > Decimal("1e30"):
        abort(400)
    # Hard invariant: always store positions on the 1000-grid.
    if (pos % Decimal("1000")) != 0:
        abort(400)
    return pos


def _next_step_position(process_id: UUID) -> "Decimal":
    from decimal import Decimal

    max_pos = (
        db_session.query(Step.position)
        .filter(Step.process_id == process_id)
        .order_by(Step.position.desc())
        .limit(1)
        .scalar()
    )
    if max_pos is None:
        return Decimal("1000")
    grid = Decimal("1000")
    mp = Decimal(str(max_pos))
    rem = mp % grid
    if rem != 0:
        mp = mp + (grid - rem)
    return mp + grid


def _flow_state_key(process_id: UUID | None) -> str:
    # "new" wizard (no process yet) gets its own bucket, and existing processes
    # get per-process state keyed by UUID string.
    return str(process_id) if process_id is not None else "new"


def _flow_state_get(process_id: UUID | None) -> dict:
    state = session.get("flow_state")
    if not isinstance(state, dict):
        state = {}
    # Treat session values as immutable: always reassign.
    state = dict(state)
    key = _flow_state_key(process_id)
    bucket = state.get(key)
    if not isinstance(bucket, dict):
        bucket = {"started": False, "max_step": 1}
        state[key] = bucket
    session["flow_state"] = state
    session.modified = True
    return bucket


def _flow_state_reset(process_id: UUID | None) -> None:
    state = session.get("flow_state")
    if not isinstance(state, dict):
        state = {}
    state = dict(state)
    state[_flow_state_key(process_id)] = {"started": True, "max_step": 1}
    session["flow_state"] = state
    session.modified = True


def _filtered_flow_query_args() -> dict[str, str]:
    """Return a safe allowlisted query dict for flow routes."""
    args: dict[str, str] = {}

    pid = _flow_process_id_from_request()
    if pid is not None:
        _assert_flow_process_access(pid)
        args["id"] = str(pid)

    if request.args.get("fresh") is not None:
        # Treat "fresh" as a boolean flag; normalize to "1" when present.
        args["fresh"] = "1"

    return {k: v for k, v in args.items() if k in _FLOW_ALLOWED_QUERY_PARAMS}


def _flow_qs() -> str:
    """Safe query string for flows/create pages, including leading '?' or empty string."""
    from urllib.parse import urlencode

    args = _filtered_flow_query_args()
    return ("?" + urlencode(sorted(args.items()))) if args else ""


def _maybe_enforce_flow_wizard_step(flow_wizard_page: str, process_id: int | None):
    """
    Enforce basic wizard sequencing for *new* wizards (no ?id=).
    This is intentionally lightweight: it prevents skipping ahead into later steps
    when there's no persisted server-side object to anchor state.
    """
    requested = _FLOW_WIZARD_PAGE_TO_STEP.get(flow_wizard_page)
    if not requested:
        return None

    bucket = _flow_state_get(process_id)
    started = bool(bucket.get("started"))
    if not started:
        return redirect("/core/flows/create" + _flow_qs())

    max_step = int(bucket.get("max_step") or 1)
    if requested > max_step + 1:
        dest = _FLOW_WIZARD_STEP_TO_PATH.get(max_step, _FLOW_WIZARD_STEP_TO_PATH[1])
        return redirect(dest + _flow_qs())

    if requested > max_step:
        bucket["max_step"] = requested
        session.modified = True

    return None


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
_EXECUTION_DATA_TRACE_KEYS = {
    "completed_by",
    "completed_by_email",
    "completed_by_user_id",
    "completed_at",
    "execution_errors",
    "execution_warnings",
}


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
    """
    if not execution_data:
        return {}, {}
    prompts = {
        k: v for k, v in execution_data.items() if k not in _EXECUTION_DATA_TRACE_KEYS and v is not None and v != ""
    }
    trace = {}
    if execution_data.get("completed_by") is not None:
        trace["completed_by"] = execution_data["completed_by"]
    completed_ts = execution_data.get("completed_at")
    if completed_ts is not None:
        trace["completed_at"] = _to_iso_timestamp(completed_ts)
    elif completed_at is not None:
        trace["completed_at"] = _to_iso_timestamp(completed_at)
    if execution_data.get("execution_errors") is not None:
        trace["execution_errors"] = execution_data["execution_errors"]
    if execution_data.get("execution_warnings") is not None:
        trace["execution_warnings"] = execution_data["execution_warnings"]
    return prompts, trace


def _validate_step_outputs_expiry_after_ready(outputs: list) -> list[str]:
    """Validate that for any output with both expiry and ready date (fixed duration), expiry >= ready. Returns list of error messages."""
    errors: list[str] = []
    for out in outputs or []:
        if not isinstance(out, dict):
            continue
        extra = out.get("extra_data") or {}
        ce = extra.get("custom_expiry")
        rd = extra.get("ready_date")
        if not ce or not ce.get("enabled") or (ce.get("mode") or "").strip() != "fixed_duration":
            continue
        if not rd or not rd.get("enabled") or (rd.get("mode") or "").strip() != "fixed_duration":
            continue
        out_name = (out.get("name") or "").strip() or "output"
        try:
            rv = int(rd.get("duration_value") or 0)
            ru = (rd.get("duration_unit") or "days").strip().lower()
            ev = int(ce.get("duration_value") or 0)
            eu = (ce.get("duration_unit") or "days").strip().lower()
        except (TypeError, ValueError):
            continue
        errors.extend(assert_expiry_after_ready_duration(out_name, rv, ru, ev, eu))
    return errors


@core_bp.route("/core", methods=["GET"])
@requires_auth
def core():
    """Serve the core2.html frontend page"""
    user_email = getattr(g, "user_email", None)
    show_reset_db = config.environment in ("test", "local") and user_email == DEMO_USER_EMAIL
    return render_template("core2.html", active_page="core", show_reset_db=show_reset_db)


@core_bp.route("/core/inventory/add", methods=["GET"])
@requires_auth
def inventory_add_hub():
    """Inventory entry hub: choose manual / CSV / barcode."""
    return render_template("inventory/add.html", active_page="core")


@core_bp.route("/core/inventory/add/manual", methods=["GET"])
@requires_auth
def inventory_add_manual():
    """Add inventory via manual single-item form."""
    return render_template("inventory/add_manual.html", active_page="core")


@core_bp.route("/core/inventory/add/csv", methods=["GET"])
@requires_auth
def inventory_add_csv():
    """Add or update inventory in bulk via CSV upload."""
    return render_template("inventory/add_csv.html", active_page="core")


@core_bp.route("/core/inventory/add/barcode", methods=["GET"])
@requires_auth
def inventory_add_barcode():
    """Add inventory via barcode / camera scan."""
    return render_template("inventory/add_barcode.html", active_page="core")


@core_bp.route("/core/inventory/view", methods=["GET"])
@requires_auth
def inventory_view():
    """Full-page inventory list with filtering."""
    return render_template("inventory/view.html", active_page="core")


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
    except (TypeError, ValueError):
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


@core_bp.route("/core/flows", methods=["GET"])
@requires_auth
def flows():
    """Serve the process workspace page (processes/flows2.html)."""
    process_id = _flow_process_id_from_request()
    if process_id is not None:
        _assert_flow_process_access(process_id)
    return render_template("processes/flows2.html", active_page="core", process_id=process_id)


@core_bp.route("/core/flows/create", methods=["GET"])
@requires_auth
def flows_create():
    """Start the wizard at step 1. Anonymous entry (no process id) sets fresh=1 so session wizard state resets."""
    base = "/core/flows/create/process-overview"

    args = _filtered_flow_query_args()
    if "id" not in args and "fresh" not in args:
        args["fresh"] = "1"

    # Initialize sequencing state (keyed by process id or "new").
    pid = _flow_process_id_from_request()
    if args.get("fresh") == "1" or not _flow_state_get(pid).get("started"):
        _flow_state_reset(pid)

    from urllib.parse import urlencode

    q = urlencode(sorted(args.items())) if args else ""
    dest = base + (f"?{q}" if q else "")
    return redirect(dest)


@core_bp.route("/core/flows/create/step/<int:step>", methods=["GET"])
@requires_auth
def flows_create_step(step):
    """Legacy /step/N URLs redirect to the current wizard URLs (one route per page)."""
    qs = _flow_qs()
    if step == 1:
        dest = "/core/flows/create/process-overview"
    elif step == 2:
        dest = "/core/flows/create/inputs"
    elif step == 3:
        dest = "/core/flows/create/outputs"
    elif step == 4:
        dest = "/core/flows/create/evidence-and-prompts"
    else:
        dest = "/core/flows/create/process-overview"
    return redirect(dest + qs)


@core_bp.route("/core/flows/create/process-overview", methods=["GET"])
@requires_auth
def flows_create_process_overview_page():
    """First wizard screen: process name + what a workflow is; then step-name."""
    process_id = _flow_process_id_from_request()
    if process_id is not None:
        _assert_flow_process_access(process_id)
    maybe_redirect = _maybe_enforce_flow_wizard_step("process-overview", process_id)
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "processes/process-flow-process-overview.html",
        active_page="core",
        process_id=process_id,
        flow_qs=_flow_qs(),
        flow_wizard_page="process-overview",
    )


@core_bp.route("/core/flows/create/step-name", methods=["GET"])
@requires_auth
def flows_create_step_name_page():
    process_id = _flow_process_id_from_request()
    if process_id is not None:
        _assert_flow_process_access(process_id)
    maybe_redirect = _maybe_enforce_flow_wizard_step("step-name", process_id)
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "processes/process-flow-step-name.html",
        active_page="core",
        process_id=process_id,
        flow_qs=_flow_qs(),
        flow_wizard_page="step-name",
    )


@core_bp.route("/core/flows/create/inputs", methods=["GET"])
@requires_auth
def flows_create_inputs_page():
    process_id = _flow_process_id_from_request()
    if process_id is not None:
        _assert_flow_process_access(process_id)
    maybe_redirect = _maybe_enforce_flow_wizard_step("inputs", process_id)
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "processes/process-flow-inputs.html",
        active_page="core",
        process_id=process_id,
        flow_qs=_flow_qs(),
        flow_wizard_page="inputs",
    )


@core_bp.route("/core/flows/create/outputs", methods=["GET"])
@requires_auth
def flows_create_outputs_page():
    process_id = _flow_process_id_from_request()
    if process_id is not None:
        _assert_flow_process_access(process_id)
    maybe_redirect = _maybe_enforce_flow_wizard_step("outputs", process_id)
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "processes/process-flow-outputs.html",
        active_page="core",
        process_id=process_id,
        flow_qs=_flow_qs(),
        flow_wizard_page="outputs",
    )


@core_bp.route("/core/flows/create/evidence-and-prompts", methods=["GET"])
@requires_auth
def flows_create_evidence_and_prompts_page():
    process_id = _flow_process_id_from_request()
    if process_id is not None:
        _assert_flow_process_access(process_id)
    maybe_redirect = _maybe_enforce_flow_wizard_step("evidence-and-prompts", process_id)
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "processes/process-flow-evidence-and-prompts.html",
        active_page="core",
        process_id=process_id,
        flow_qs=_flow_qs(),
        flow_wizard_page="evidence-and-prompts",
    )


@core_bp.route("/core/flows/create/summary", methods=["GET"])
@requires_auth
def flows_create_summary_page():
    process_id = _flow_process_id_from_request()
    if process_id is not None:
        _assert_flow_process_access(process_id)
    maybe_redirect = _maybe_enforce_flow_wizard_step("summary", process_id)
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "processes/process-flow-summary.html",
        active_page="core",
        process_id=process_id,
        flow_qs=_flow_qs(),
        flow_wizard_page="summary",
    )


@core_bp.route("/core/flows/create/next-steps", methods=["GET"])
@requires_auth
def flows_create_next_steps_page():
    """After saving a step: choose add another step or finish the process."""
    process_id = _flow_process_id_from_request()
    if process_id is not None:
        _assert_flow_process_access(process_id)
    maybe_redirect = _maybe_enforce_flow_wizard_step("next-steps", process_id)
    if maybe_redirect is not None:
        return maybe_redirect
    return render_template(
        "processes/process-flow-next-steps.html",
        active_page="core",
        process_id=process_id,
        flow_qs=_flow_qs(),
        flow_wizard_page="next-steps",
    )


@core_bp.route("/core/notifications", methods=["GET"])
@requires_auth
def notifications_page():
    """Serve system notifications (system findings) as a card list."""
    return render_template("notifications.html", active_page="core")


@core_bp.route("/core/processes", methods=["GET"])
@requires_auth
def processes_list_page():
    """SPA list of all processes; links open flows2 for each process."""
    return render_template("processes/list.html", active_page="core")


@core_bp.route("/core/sourcemap", methods=["GET"])
@requires_auth
def sourcemap():
    """Serve the sourcemap.html frontend page"""
    return render_template("sourcemap.html", active_page="core")


@core_bp.route("/static/js/<filename>")
@limiter.exempt
def serve_core_js(filename):
    """Serve JavaScript files from core frontend (no auth so they load reliably; pages that include them are protected)."""
    from flask import abort
    from werkzeug.security import safe_join

    # Path traversal protection: reject filenames with .. or /
    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400, "Invalid filename")

    # Extension whitelist for security
    if not filename.lower().endswith(".js"):
        abort(400, "Invalid file type")

    core_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "js")
    # Use safe_join for validation only (not for file access)
    safe_path = safe_join(core_frontend_dir, filename)
    if safe_path is None:
        abort(400, "Invalid filename")

    # File serving must be done exclusively via send_from_directory
    try:
        response = send_from_directory(core_frontend_dir, filename)
        # Set explicit Content-Type header
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"
        # X-Content-Type-Options is set globally in after_request handler
        return response
    except FileNotFoundError:
        # Missing static file - log at info level (not error)
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Static JS file not found: {filename} from {core_frontend_dir}")
        # Return 404 - do not fall back to Flask's global static handler
        abort(404, "File not found")
    except Exception:
        # Unexpected exception - log at exception level
        import logging

        logger = logging.getLogger(__name__)
        logger.exception(f"Unexpected error serving static JS file: {filename}")
        abort(500, "Internal server error")


@core_bp.route("/static/css/<filename>")
@limiter.exempt
def serve_core_css(filename):
    """Serve CSS files from core frontend (no auth so they load reliably; pages that include them are protected)."""
    from flask import abort
    from werkzeug.security import safe_join

    # Path traversal protection: reject filenames with .. or /
    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400, "Invalid filename")

    # Extension whitelist for security
    if not filename.lower().endswith(".css"):
        abort(400, "Invalid file type")

    core_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "css")
    # Use safe_join for validation only (not for file access)
    safe_path = safe_join(core_frontend_dir, filename)
    if safe_path is None:
        abort(400, "Invalid filename")

    # File serving must be done exclusively via send_from_directory
    try:
        response = send_from_directory(core_frontend_dir, filename)
        # Set explicit Content-Type header
        response.headers["Content-Type"] = "text/css; charset=utf-8"
        # X-Content-Type-Options is set globally in after_request handler
        return response
    except FileNotFoundError:
        # Missing static file - log at info level (not error)
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Static CSS file not found: {filename} from {core_frontend_dir}")
        # Return 404 - do not fall back to Flask's global static handler
        abort(404, "File not found")
    except Exception:
        # Unexpected exception - log at exception level
        import logging

        logger = logging.getLogger(__name__)
        logger.exception(f"Unexpected error serving static CSS file: {filename}")
        abort(500, "Internal server error")


_INVENTORY_STATIC_ALLOWLIST = frozenset({"inventory-icon.svg", "inventory-spa-header.css"})


@core_bp.route("/static/inventory/<filename>")
@limiter.exempt
def serve_core_inventory_static(filename):
    """Serve SVG/CSS from core frontend inventory/ (used by inventory SPA header partial)."""
    from flask import abort
    from werkzeug.security import safe_join

    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400, "Invalid filename")
    if filename not in _INVENTORY_STATIC_ALLOWLIST:
        abort(400, "Invalid file")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".svg", ".css"):
        abort(400, "Invalid file type")

    inventory_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "inventory")
    safe_path = safe_join(inventory_dir, filename)
    if safe_path is None:
        abort(400, "Invalid filename")

    try:
        response = send_from_directory(inventory_dir, filename)
        if ext == ".svg":
            response.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
        else:
            response.headers["Content-Type"] = "text/css; charset=utf-8"
        return response
    except FileNotFoundError:
        import logging

        logging.getLogger(__name__).info("Inventory static file not found: %s", filename)
        abort(404, "File not found")
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Error serving inventory static: %s", filename)
        abort(500, "Internal server error")


@core_bp.route("/api/core/processes", methods=["GET"])
@requires_auth
def list_processes():
    """List all processes for the current organisation"""
    org_id = UUID(g.org_id)
    repo = ProcessRepository(db_session)
    processes = repo.list_processes(org_id)

    # Calculate stats for each process
    execution_repo = ExecutionRepository(db_session)
    result = []
    for process in processes:
        executions = execution_repo.list_executions(org_id, process_id=process.id)
        active_count = sum(1 for e in executions if e.status == ExecutionStatus.IN_PROGRESS)
        completed_count = sum(1 for e in executions if e.status == ExecutionStatus.COMPLETED)
        step_count = len(process.steps) if process.steps else 0

        result.append(
            {
                "id": str(process.id),
                "name": process.name,
                "description": process.description,
                "category": process.category.value if process.category else None,
                "is_draft": process.is_draft,
                "step_count": step_count,
                "active_executions": active_count,
                "completed_executions": completed_count,
                "created_at": process.created_at.isoformat() if process.created_at else None,
            }
        )

    return jsonify({"processes": result}), 200


@core_bp.route("/api/core/processes", methods=["POST"])
@requires_auth
def create_process():
    """Create a new process"""
    org_id = UUID(g.org_id)
    data = request.get_json()

    name = data.get("name")
    if not name:
        return jsonify({"error": "Process name is required"}), 400

    description = data.get("description")
    category_str = data.get("category")
    category = None
    if category_str:
        try:
            category = ProcessCategory(category_str)
        except ValueError:
            return jsonify({"error": f"Invalid category: {category_str}"}), 400

    is_draft = data.get("is_draft", False)

    repo = ProcessRepository(db_session)
    try:
        process = repo.create_process(
            org_id=org_id, name=name, description=description, category=category, is_draft=is_draft
        )
        return (
            jsonify(
                {
                    "id": str(process.id),
                    "name": process.name,
                    "description": process.description,
                    "category": process.category.value if process.category else None,
                    "is_draft": process.is_draft,
                    "created_at": process.created_at.isoformat() if process.created_at else None,
                }
            ),
            201,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        # Log the full error for debugging but return generic message to client
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error creating process")
        return jsonify({"error": "Failed to create process"}), 500


@core_bp.route("/api/core/processes/<process_id>", methods=["PUT"])
@requires_auth
def update_process(process_id: str):
    """Update a process"""
    org_id = UUID(g.org_id)
    try:
        process_uuid = UUID(process_id)
    except ValueError:
        return jsonify({"error": "Invalid process ID"}), 400

    data = request.get_json()
    name = data.get("name")
    description = data.get("description")
    category_str = data.get("category")
    is_draft = data.get("is_draft")  # Extract is_draft from request

    category = None
    if category_str:
        try:
            category = ProcessCategory(category_str)
        except ValueError:
            return jsonify({"error": f"Invalid category: {category_str}"}), 400

    repo = ProcessRepository(db_session)
    try:
        process = repo.update_process(
            process_id=process_uuid,
            org_id=org_id,
            name=name,
            description=description,
            category=category,
            is_draft=is_draft,  # Pass is_draft to repository
        )

        if not process:
            return jsonify({"error": "Process not found"}), 404

        return (
            jsonify(
                {
                    "id": str(process.id),
                    "name": process.name,
                    "description": process.description,
                    "category": process.category.value if process.category else None,
                    "is_draft": process.is_draft,
                    "created_at": process.created_at.isoformat() if process.created_at else None,
                }
            ),
            200,
        )
    except Exception:
        # Log the full error for debugging but return generic message to client
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error updating process")
        return jsonify({"error": "Failed to update process"}), 500


@core_bp.route("/api/core/processes/<process_id>", methods=["DELETE"])
@requires_auth
def delete_process(process_id: str):
    """Delete a process"""
    org_id = UUID(g.org_id)
    try:
        process_uuid = UUID(process_id)
    except ValueError:
        return jsonify({"error": "Invalid process ID"}), 400

    repo = ProcessRepository(db_session)
    try:
        success = repo.delete_process(process_id=process_uuid, org_id=org_id)

        if not success:
            return jsonify({"error": "Process not found"}), 404

        return jsonify({"message": "Process deleted successfully"}), 200
    except Exception:
        # Log the full error for debugging but return generic message to client
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error deleting process")
        return jsonify({"error": "Failed to delete process"}), 500


@core_bp.route("/api/core/processes/<process_id>", methods=["GET"])
@requires_auth
def get_process(process_id: str):
    """Get a process with its steps"""
    org_id = UUID(g.org_id)
    try:
        process_uuid = UUID(process_id)
    except ValueError:
        return jsonify({"error": "Invalid process ID"}), 400

    repo = ProcessRepository(db_session)
    process = repo.get_process_with_steps(process_uuid, org_id)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    steps = []
    for step in process.steps:
        steps.append(
            {
                "id": str(step.id),
                "step_number": step.step_number,
                "position": str(step.position) if getattr(step, "position", None) is not None else None,
                "name": step.name,
                "description": step.description,
                "inputs": step.inputs or [],
                "outputs": step.outputs or [],
                "execution_prompts": step.execution_prompts or [],
            }
        )

    return (
        jsonify(
            {
                "id": str(process.id),
                "name": process.name,
                "description": process.description,
                "category": process.category.value if process.category else None,
                "is_draft": process.is_draft,
                "steps": steps,
                "created_at": process.created_at.isoformat() if process.created_at else None,
            }
        ),
        200,
    )


@core_bp.route("/api/core/processes/<process_id>/steps", methods=["POST"])
@requires_auth
def add_step(process_id: str):
    """Add a step to a process"""
    org_id = UUID(g.org_id)
    try:
        process_uuid = UUID(process_id)
    except ValueError:
        return jsonify({"error": "Invalid process ID"}), 400

    data = request.get_json()
    step_number = data.get("step_number")
    name = data.get("name")

    if step_number is None or name is None:
        return jsonify({"error": "step_number and name are required"}), 400
    try:
        step_number_int = int(step_number)
    except Exception:
        return jsonify({"error": "Invalid step_number"}), 400

    # Option B ordering: accept explicit position, else append.
    position = _coerce_step_position(data.get("position"))
    if position is None:
        position = _next_step_position(process_uuid)

    outputs = data.get("outputs", [])
    expiry_ready_errors = _validate_step_outputs_expiry_after_ready(outputs)
    if expiry_ready_errors:
        return jsonify({"error": expiry_ready_errors[0]}), 400

    repo = ProcessRepository(db_session)
    try:
        step = repo.add_step(
            process_id=process_uuid,
            org_id=org_id,
            step_number=step_number_int,
            position=position,
            name=name,
            description=data.get("description"),
            inputs=data.get("inputs", []),
            outputs=data.get("outputs", []),
            execution_prompts=data.get("execution_prompts", []),
        )
    except IntegrityError:
        db_session.rollback()
        return jsonify({"error": "Could not create step"}), 409

    if not step:
        return jsonify({"error": "Process not found"}), 404

    return (
        jsonify(
            {
                "id": str(step.id),
                "step_number": step.step_number,
                "position": str(step.position) if getattr(step, "position", None) is not None else None,
                "name": step.name,
                "description": step.description,
                "inputs": step.inputs or [],
                "outputs": step.outputs or [],
                "execution_prompts": step.execution_prompts or [],
            }
        ),
        201,
    )


@core_bp.route("/api/core/processes/<process_id>/steps/<step_id>", methods=["PUT"])
@requires_auth
def update_step(process_id: str, step_id: str):
    """Update a step"""
    org_id = UUID(g.org_id)
    try:
        process_uuid = UUID(process_id)
        step_uuid = UUID(step_id)
    except ValueError:
        return jsonify({"error": "Invalid process or step ID"}), 400

    data = request.get_json()
    if data and "position" in data:
        _coerce_step_position(data.get("position"))

    outputs = data.get("outputs")
    if outputs is not None:
        expiry_ready_errors = _validate_step_outputs_expiry_after_ready(outputs)
        if expiry_ready_errors:
            return jsonify({"error": expiry_ready_errors[0]}), 400

    repo = ProcessRepository(db_session)
    try:
        step = repo.update_step(
            step_id=step_uuid,
            process_id=process_uuid,
            org_id=org_id,
            step_number=data.get("step_number"),
            position=_coerce_step_position(data.get("position")) if "position" in data else None,
            name=data.get("name"),
            description=data.get("description"),
            inputs=data.get("inputs"),
            outputs=data.get("outputs"),
            execution_prompts=data.get("execution_prompts"),
        )
    except IntegrityError:
        db_session.rollback()
        return jsonify({"error": "Could not update step"}), 409

    if not step:
        return jsonify({"error": "Step or process not found"}), 404

    return (
        jsonify(
            {
                "id": str(step.id),
                "step_number": step.step_number,
                "position": str(step.position) if getattr(step, "position", None) is not None else None,
                "name": step.name,
                "description": step.description,
                "inputs": step.inputs or [],
                "outputs": step.outputs or [],
                "execution_prompts": step.execution_prompts or [],
            }
        ),
        200,
    )


@core_bp.route("/api/core/processes/<process_id>/steps/reorder", methods=["POST"])
@requires_auth
def reorder_steps(process_id: str):
    """Batch reorder steps by updating their position values atomically.

    Client should send ordered IDs. Server normalizes positions to prevent precision entropy.
    """
    org_id = UUID(g.org_id)
    try:
        process_uuid = UUID(process_id)
    except ValueError:
        return jsonify({"error": "Invalid process ID"}), 400

    # Ensure process belongs to org (IDOR guard).
    repo = ProcessRepository(db_session)
    if not repo.get_process_by_id(process_uuid, org_id=org_id):
        return jsonify({"error": "Process not found"}), 404

    data = request.get_json() or {}
    step_ids = data.get("step_ids") or data.get("ids") or data.get("ordered_step_ids")
    if step_ids is None:
        # Backwards compatibility: accept {orders:[{id,...},...]} but ignore client positions.
        orders = data.get("orders") or data.get("steps") or []
        if isinstance(orders, list) and orders:
            step_ids = [(row.get("id") or row.get("step_id")) for row in orders if isinstance(row, dict)]
    if not isinstance(step_ids, list) or not step_ids:
        return jsonify({"error": "step_ids is required"}), 400

    # Parse and de-duplicate while preserving order.
    parsed_ids: list[UUID] = []
    seen: set[UUID] = set()
    for raw in step_ids:
        try:
            sid = UUID(str(raw))
        except Exception:
            return jsonify({"error": "Invalid step id"}), 400
        if sid in seen:
            continue
        seen.add(sid)
        parsed_ids.append(sid)

    from decimal import Decimal

    try:
        with db_session.begin():
            # Lock all steps for this process to prevent concurrent reorder collisions.
            locked = (
                db_session.query(Step.id)
                .filter(Step.process_id == process_uuid)
                .with_for_update()
                .all()
            )
            locked_ids = {sid for (sid,) in locked}
            if not locked_ids:
                return jsonify({"error": "No steps to reorder"}), 400

            # Ensure request includes only steps from this process.
            for sid in parsed_ids:
                if sid not in locked_ids:
                    return jsonify({"error": "Step not found"}), 404

            # If the client omitted some steps, append them in current position order.
            if len(parsed_ids) != len(locked_ids):
                remaining = (
                    db_session.query(Step.id)
                    .filter(Step.process_id == process_uuid, ~Step.id.in_(parsed_ids))
                    .order_by(Step.position)
                    .all()
                )
                parsed_ids.extend([sid for (sid,) in remaining])

            # Normalize positions with clean spacing.
            spacing = Decimal("1000")
            for i, sid in enumerate(parsed_ids, start=1):
                new_pos = spacing * Decimal(i)
                db_session.query(Step).filter(Step.id == sid, Step.process_id == process_uuid).update(
                    {"position": new_pos}
                )

        return jsonify({"message": "Reordered"}), 200
    except Exception:
        db_session.rollback()
        return jsonify({"error": "Failed to reorder steps"}), 500


@core_bp.route("/api/core/processes/<process_id>/steps/<step_id>", methods=["DELETE"])
@requires_auth
def delete_step(process_id: str, step_id: str):
    """Delete a step from a process"""
    org_id = UUID(g.org_id)
    try:
        process_uuid = UUID(process_id)
        step_uuid = UUID(step_id)
    except ValueError:
        return jsonify({"error": "Invalid process or step ID"}), 400

    repo = ProcessRepository(db_session)
    success = repo.delete_step(
        step_id=step_uuid,
        process_id=process_uuid,
        org_id=org_id,
    )

    if not success:
        return jsonify({"error": "Step or process not found"}), 404

    return jsonify({"message": "Step deleted successfully"}), 200


@core_bp.route("/api/core/executions", methods=["POST"])
@requires_auth
def create_execution():
    """Create a new execution for a process"""
    org_id = UUID(g.org_id)
    data = request.get_json()

    process_id_str = data.get("process_id")
    if not process_id_str:
        return jsonify({"error": "process_id is required"}), 400

    try:
        process_id = UUID(process_id_str)
    except ValueError:
        return jsonify({"error": "Invalid process ID"}), 400

    repo = ExecutionRepository(db_session)
    try:
        execution = repo.create_execution(org_id=org_id, process_id=process_id)
        return (
            jsonify(
                {
                    "id": str(execution.id),
                    "process_id": str(execution.process_id),
                    "status": execution.status.value,
                    "started_at": execution.started_at.isoformat() if execution.started_at else None,
                }
            ),
            201,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        # Log the full error for debugging but return generic message to client
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error creating process")
        return jsonify({"error": "Failed to create process"}), 500


@core_bp.route("/api/core/executions", methods=["GET"])
@requires_auth
def list_executions():
    """List executions, optionally filtered by process"""
    org_id = UUID(g.org_id)
    process_id_str = request.args.get("process_id")
    status_str = request.args.get("status")

    process_id = None
    if process_id_str:
        try:
            process_id = UUID(process_id_str)
        except ValueError:
            return jsonify({"error": "Invalid process_id parameter"}), 400

    status = None
    if status_str:
        try:
            status = ExecutionStatus(status_str)
        except ValueError:
            return jsonify({"error": f"Invalid status: {status_str}"}), 400

    repo = ExecutionRepository(db_session)
    executions = repo.list_executions(org_id=org_id, process_id=process_id, status=status)

    result = []
    for execution in executions:
        # Get current step info
        execution_steps = execution.execution_steps if execution.execution_steps else []
        execution_steps_sorted = sorted(execution_steps, key=lambda es: es.step_number)
        current_step = None
        ready_steps = [es for es in execution_steps_sorted if es.status.value == "ready"]
        completed_steps = [es for es in execution_steps if es.status.value == "completed"]

        if ready_steps:
            next_step = ready_steps[0]
            # Use 1-based position in execution (not raw step_number) so display is always "N of total"
            try:
                display_index = 1 + next(i for i, es in enumerate(execution_steps_sorted) if es.id == next_step.id)
            except StopIteration:
                display_index = next_step.step_number
            current_step = {
                "step_number": display_index,
                "step_id": str(next_step.step_id),
                "name": next_step.step.name if next_step.step else None,
            }

        # Calculate progress using snapshot total_steps to avoid division by zero and ensure consistency
        # Progress should not change if steps are added or reordered later
        total_steps = execution.total_steps or len(execution_steps) if execution_steps else 0
        progress = (len(completed_steps) / total_steps * 100) if total_steps > 0 else 0

        result.append(
            {
                "id": str(execution.id),
                "process_id": str(execution.process_id),
                "status": execution.status.value,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                "current_step": current_step,
                "progress": progress,
                "total_steps": total_steps,
            }
        )

    return jsonify({"executions": result}), 200


@core_bp.route("/api/core/executions/<execution_id>", methods=["GET"])
@requires_auth
def get_execution(execution_id: str):
    """Get an execution with its steps"""
    org_id = UUID(g.org_id)
    try:
        execution_uuid = UUID(execution_id)
    except ValueError:
        return jsonify({"error": "Invalid execution ID"}), 400

    repo = ExecutionRepository(db_session)
    execution = repo.get_execution_with_steps(execution_uuid, org_id)
    if not execution:
        return jsonify({"error": "Execution not found"}), 404

    execution_steps = []
    for es in execution.execution_steps:
        execution_steps.append(
            {
                "id": str(es.id),
                "step_id": str(es.step_id),
                "step_number": es.step_number,
                "status": es.status.value,
                "actual_inputs": es.actual_inputs or [],
                "actual_outputs": es.actual_outputs or [],
                "execution_data": es.execution_data or {},
                "started_at": es.started_at.isoformat() if es.started_at else None,
                "completed_at": es.completed_at.isoformat() if es.completed_at else None,
                "step_name": es.step.name if es.step else None,
                "step_inputs": es.step.inputs or [] if es.step else [],
                "step_outputs": es.step.outputs or [] if es.step else [],
            }
        )

    evidence_list = list_evidence_for_execution(execution_uuid, org_id)

    return (
        jsonify(
            {
                "id": str(execution.id),
                "process_id": str(execution.process_id),
                "status": execution.status.value,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                "execution_steps": execution_steps,
                "evidence": evidence_list,
            }
        ),
        200,
    )


@core_bp.route("/api/core/executions/<execution_id>/steps/<execution_step_id>/complete", methods=["POST"])
@requires_auth
def complete_step(execution_id: str, execution_step_id: str):
    """Complete an execution step"""
    org_id = UUID(g.org_id)
    try:
        execution_uuid = UUID(execution_id)
        execution_step_uuid = UUID(execution_step_id)
    except ValueError:
        return jsonify({"error": "Invalid execution or step ID"}), 400

    data = request.get_json() or {}
    actual_inputs = data.get("actual_inputs", [])
    actual_outputs = data.get("actual_outputs", [])
    execution_data = data.get("execution_data", {})
    allow_consumption_override = data.get("allow_consumption_override") is True

    # Get current user from Flask g and always store in execution_data for accuracy
    # TODO: execution_data is becoming a structured contract with known fields:
    # - User metadata: completed_by, completed_by_email, completed_by_user_id
    # - Execution metadata: execution_prompts (user-entered), execution_errors, execution_warnings
    # Consider formalizing this as a schema/validator in the future to prevent drift
    user_email = getattr(g, "user_email", None)
    if user_email:
        execution_data["completed_by"] = user_email
        execution_data["completed_by_email"] = user_email
        # Also store user_id if available
        user_id = getattr(g, "user_id", None)
        if user_id:
            execution_data["completed_by_user_id"] = str(user_id)

    repo = ExecutionRepository(db_session)
    try:
        execution_step = repo.complete_step(
            execution_step_id=execution_step_uuid,
            org_id=org_id,
            actual_inputs=actual_inputs,
            actual_outputs=actual_outputs,
            execution_data=execution_data,
        )

        if not execution_step:
            return jsonify({"error": "Execution step not found"}), 404

        # Refresh execution_step to ensure we have the latest data including execution_data
        db_session.refresh(execution_step)
        # Capture step outputs for post-commit audit (avoid lazy load after commit)
        step_outputs_for_audit = None
        step_def = getattr(execution_step, "step", None)
        if step_def is not None:
            step_outputs_for_audit = list(step_def.outputs or []) if getattr(step_def, "outputs", None) else None

        # Initialize inventory repository once for reuse throughout this function
        inventory_repo = InventoryRepository(db_session)

        # Collect execution warnings for structured error reporting
        # FAILURE HANDLING POLICY:
        # - Errors: Block execution, persist to execution_data, return 400
        #   Examples: Invalid quantity format, unit incompatibility, missing required inventory
        # - Warnings: Allow execution to continue, persist to execution_data for audit
        #   Examples: Zero-quantity outputs (skipped), missing optional inventory items
        # This distinction ensures critical failures are caught early while non-critical issues
        # are recorded for review without blocking workflow progress.
        execution_warnings = []
        execution_errors = []

        # Consume inventory for variable inputs
        # Aggregate by inventory_item_id so the same item cannot be consumed more than available across multiple inputs
        # TRANSACTION INTEGRITY: This function must run in a single DB transaction; no commit until the end.
        # get_inventory_item_by_id_for_update holds row locks until commit/rollback.
        inventory_updates = []
        if actual_inputs:
            consumption_by_item = {}
            for input_data in actual_inputs:
                inventory_item_id = input_data.get("inventory_item_id")
                if not inventory_item_id:
                    continue
                key = str(inventory_item_id)
                if key not in consumption_by_item:
                    consumption_by_item[key] = []
                consumption_by_item[key].append(
                    (
                        input_data.get("quantity", 0),
                        input_data.get("unit", ""),
                        input_data.get("name", "Unknown"),
                    )
                )

            for item_id_str, consumptions in consumption_by_item.items():
                try:
                    inventory_item_id = UUID(item_id_str)
                except (ValueError, TypeError):
                    execution_errors.append(f"Invalid inventory item id: {item_id_str}")
                    continue
                try:
                    inventory_item = inventory_repo.get_inventory_item_by_id_for_update(inventory_item_id, org_id)
                    if not inventory_item:
                        execution_warnings.append(f"Inventory item {item_id_str} not found for input(s)")
                        continue

                    if not allow_consumption_override:
                        ready_ok, ready_err = is_inventory_item_ready_for_consumption(db_session, inventory_item)
                        if not ready_ok and ready_err:
                            execution_errors.append(ready_err)
                            continue

                    try:
                        current_quantity = Decimal(str(inventory_item.quantity))
                    except (InvalidOperation, ValueError, TypeError):
                        execution_errors.append(
                            f"Invalid quantity format for inventory item {item_id_str}: {inventory_item.quantity}"
                        )
                        continue

                    inventory_unit = inventory_item.unit or ""
                    total_converted = Decimal("0")
                    conversion_failed = False

                    for quantity_consumed, consumed_unit, input_name in consumptions:
                        if inventory_unit and not (consumed_unit or "").strip():
                            execution_errors.append(
                                f"Input '{input_name}': unit required when inventory unit is {inventory_unit}"
                            )
                            conversion_failed = True
                            break
                        if consumed_unit and inventory_unit:
                            if not are_units_compatible(consumed_unit, inventory_unit):
                                execution_errors.append(
                                    f"Cannot consume {quantity_consumed} {consumed_unit} from inventory "
                                    f"item {item_id_str} (unit: {inventory_unit}): units are incompatible"
                                )
                                conversion_failed = True
                                break
                            try:
                                qty_decimal = Decimal(str(quantity_consumed))
                                converted = convert_to_inventory_unit_decimal(
                                    qty_decimal, consumed_unit, inventory_unit
                                )
                            except (ValueError, InvalidOperation) as conv_error:
                                execution_errors.append(
                                    f"Failed to convert {quantity_consumed} {consumed_unit} to {inventory_unit}: {conv_error}"
                                )
                                conversion_failed = True
                                break
                        else:
                            try:
                                converted = Decimal(str(quantity_consumed))
                            except (InvalidOperation, ValueError, TypeError):
                                execution_errors.append(
                                    f"Invalid quantity format for input '{input_name}': {quantity_consumed}"
                                )
                                conversion_failed = True
                                break
                        total_converted += converted

                    if conversion_failed:
                        continue
                    if total_converted > current_quantity:
                        execution_errors.append(
                            f"Total quantity requested for inventory item (batch) exceeds available: "
                            f"requested {total_converted} {inventory_unit or 'units'}, available {current_quantity} {inventory_unit or 'units'}"
                        )
                        continue

                    new_quantity = max(Decimal("0"), current_quantity - total_converted)
                    inventory_updates.append((inventory_item, new_quantity))

                except Exception as e:
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.exception(f"Unexpected error consuming inventory {item_id_str}")
                    execution_errors.append(f"Failed to consume inventory {item_id_str}: {str(e)}")

        # FAILURE HANDLING: Block execution if critical errors occurred
        if execution_errors:
            # Persist errors to execution_data for audit trail
            if not execution_step.execution_data:
                execution_step.execution_data = {}
            execution_step.execution_data["execution_errors"] = execution_errors
            db_session.commit()
            return jsonify({"error": "Execution failed", "details": execution_errors}), 400

        # Create inventory items for outputs if specified
        # All non-terminal outputs are stored as intermediate products (WORK_IN_PROGRESS)
        # Terminal outputs are stored as FINAL_PRODUCT
        # This provides a live view of stock at any moment
        # TRANSACTION INTEGRITY: Collect all output creations, then commit atomically
        output_creations = []
        if actual_outputs:
            for output in actual_outputs:
                output_quantity = output.get("quantity", 0)
                output_name = output.get("name", "Unknown")

                # QUANTITY PRECISION: Use Decimal for validation
                try:
                    quantity_decimal = Decimal(str(output_quantity))
                    if quantity_decimal <= 0:
                        execution_warnings.append(
                            f"Skipping output '{output_name}' with zero or negative quantity: {output_quantity}"
                        )
                        continue
                except (InvalidOperation, ValueError, TypeError):
                    execution_warnings.append(
                        f"Skipping output '{output_name}' with invalid quantity format: {output_quantity}"
                    )
                    continue

                # Determine inventory type based on terminal step detection
                # Use is_terminal_step field for deterministic detection
                # Non-terminal steps produce intermediate products (work_in_progress)
                # Terminal steps produce final products
                inventory_type = InventoryType.WORK_IN_PROGRESS.value
                if execution_step.is_terminal_step:
                    inventory_type = InventoryType.FINAL_PRODUCT.value

                # EXTRA_DATA DISCIPLINE: Store only source execution data (not derived data)
                # extra_data schema:
                # - execution_prompts: Source data from execution_step.execution_data (user-entered metadata)
                # - execution_trace: All system/audit metadata for sourcemap traceability (completed_by, completed_at, errors, warnings)
                # - variable_inputs: Source data from execution_step.actual_inputs (what was consumed)
                # - variable_output: Source data from execution_step.actual_outputs (this specific output)
                # NOTE: previous_steps_data is derived/read-only and should NEVER be persisted here
                extra_data = {}
                # Get execution_data from the execution_step (read from DB after refresh)
                step_execution_data = execution_step.execution_data if execution_step.execution_data else {}
                if step_execution_data:
                    execution_prompts, execution_trace = _split_execution_data(
                        step_execution_data, completed_at=execution_step.completed_at
                    )
                    if execution_prompts:
                        extra_data["execution_prompts"] = execution_prompts
                    if execution_trace:
                        extra_data["execution_trace"] = execution_trace

                # Store variable inputs used to produce this output
                # Get actual_inputs from the execution_step (it was stored when the step was completed)
                step_actual_inputs = execution_step.actual_inputs if execution_step.actual_inputs else []
                if step_actual_inputs:
                    extra_data["variable_inputs"] = step_actual_inputs

                # Store variable outputs (for this specific output item)
                # Only include the output that matches this inventory item
                step_actual_outputs = execution_step.actual_outputs if execution_step.actual_outputs else []
                if step_actual_outputs:
                    # Find the matching output in actual_outputs
                    matching_output = next((o for o in step_actual_outputs if o.get("name") == output_name), None)
                    if matching_output:
                        extra_data["variable_output"] = matching_output

                # Custom expiry: if configured to be set at execution, validate and persist operator selection
                step_def = getattr(execution_step, "step", None)
                step_outputs_def = step_def.outputs if step_def and getattr(step_def, "outputs", None) else []
                ce_cfg = None
                for od in step_outputs_def or []:
                    if isinstance(od, dict) and (od.get("name") or "").strip() == output_name:
                        candidate = (od.get("extra_data") or {}).get("custom_expiry")
                        if candidate and candidate.get("enabled"):
                            ce_cfg = candidate
                            break
                if ce_cfg and ce_cfg.get("enabled"):
                    cfg_mode = (ce_cfg.get("mode") or "").strip()
                    if cfg_mode not in {"fixed_duration", "set_at_execution"}:
                        cfg_mode = ""
                    # Reject execution-time expiry payload when step is configured as fixed_duration
                    if cfg_mode == "fixed_duration" and output.get("custom_expiry_input"):
                        execution_errors.append(
                            f"Output '{output_name}' is configured for fixed expiry; custom expiry input is not allowed."
                        )
                    elif cfg_mode == "set_at_execution":
                        ce_in = output.get("custom_expiry_input")
                        if not isinstance(ce_in, dict) or not ce_in.get("mode"):
                            execution_errors.append(
                                f"Output '{output_name}' requires expiry to be set during execution."
                            )
                        else:
                            in_mode = ce_in.get("mode")
                            # Validate units (reject invalid instead of normalizing)
                            du_raw = (ce_in.get("duration_unit") or "days").strip().lower()
                            wu_raw = (ce_in.get("warning_unit") or ce_cfg.get("warning_unit") or "days").strip().lower()
                            if du_raw not in VALID_EXPIRY_UNITS:
                                execution_errors.append(f"Output '{output_name}': invalid expiry duration unit.")
                            if wu_raw not in VALID_EXPIRY_UNITS:
                                execution_errors.append(f"Output '{output_name}': invalid warning duration unit.")
                            # Warning fallback from step config
                            warn_val = ce_in.get("warning_value")
                            if warn_val is None:
                                warn_val = ce_cfg.get("warning_value") or ce_cfg.get("warning_days")
                            if not warn_val and warn_val != 0:
                                warn_val = 7
                            try:
                                warn_val_int = int(warn_val)
                                if warn_val_int < 0:
                                    execution_errors.append(
                                        f"Output '{output_name}': warning duration must not be negative."
                                    )
                                    warn_val_int = 7
                            except (TypeError, ValueError):
                                warn_val_int = 7

                            if in_mode == "duration":
                                dv = ce_in.get("duration_value")
                                try:
                                    dv_int = int(dv) if dv is not None else 0
                                except (TypeError, ValueError):
                                    dv_int = 0
                                if dv_int <= 0:
                                    execution_errors.append(
                                        f"Output '{output_name}': expiry duration must be positive."
                                    )
                                elif du_raw in VALID_EXPIRY_UNITS and wu_raw in VALID_EXPIRY_UNITS:
                                    duration_errors = validate_custom_expiry_warning_not_exceed_duration(
                                        output_name, dv_int, du_raw, warn_val_int, wu_raw
                                    )
                                    execution_errors.extend(duration_errors)
                                    if not duration_errors:
                                        extra_data["custom_expiry_actual"] = {
                                            "mode": "duration",
                                            "duration_value": dv_int,
                                            "duration_unit": du_raw,
                                            "warning_value": warn_val_int,
                                            "warning_unit": wu_raw,
                                        }
                            elif in_mode == "datetime":
                                raw = ce_in.get("expiry_at")
                                expiry_iso = None
                                if isinstance(raw, str) and raw.strip():
                                    s = raw.strip()
                                    try:
                                        expiry_iso = datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
                                    except Exception:
                                        expiry_iso = None
                                if not expiry_iso:
                                    execution_errors.append(
                                        f"Output '{output_name}' has invalid expiry date/time. Choose a valid date/time."
                                    )
                                elif wu_raw in VALID_EXPIRY_UNITS:
                                    extra_data["custom_expiry_actual"] = {
                                        "mode": "datetime",
                                        "expiry_at": expiry_iso,
                                        "warning_value": warn_val_int,
                                        "warning_unit": wu_raw,
                                    }
                            else:
                                execution_errors.append(
                                    f"Output '{output_name}' has invalid expiry selection. Choose duration or date/time."
                                )

                # Ready date: if configured as set_at_execution, require and persist operator-set date
                rd_cfg = None
                for od in step_outputs_def or []:
                    if isinstance(od, dict) and (od.get("name") or "").strip() == output_name:
                        candidate = (od.get("extra_data") or {}).get("ready_date")
                        if (
                            candidate
                            and candidate.get("enabled")
                            and (candidate.get("mode") or "").strip() == "set_at_execution"
                        ):
                            rd_cfg = candidate
                            break
                if rd_cfg:
                    rd_in = output.get("ready_date_input")
                    if not isinstance(rd_in, dict) or not rd_in.get("date"):
                        execution_errors.append(
                            f"Output '{output_name}' requires a date of availability to be set during execution."
                        )
                    else:
                        raw = rd_in.get("date")
                        ready_iso = None
                        # Validate ISO parseability; optional future: reject past dates if policy requires future-only.
                        if isinstance(raw, str) and raw.strip():
                            try:
                                ready_iso = datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).isoformat()
                            except Exception:
                                ready_iso = None
                        if not ready_iso:
                            execution_errors.append(
                                f"Output '{output_name}' has invalid ready date. Choose a valid date."
                            )
                        else:
                            extra_data["ready_date_actual"] = {"date": ready_iso}

                # When both expiry and ready date are set, expiry cannot be before ready date (shared invariant)
                ready_iso_val = (extra_data.get("ready_date_actual") or {}).get("date")
                if ready_iso_val:
                    expiry_iso_val = None
                    ce_actual = extra_data.get("custom_expiry_actual") or {}
                    if ce_actual.get("mode") == "datetime" and ce_actual.get("expiry_at"):
                        expiry_iso_val = ce_actual.get("expiry_at")
                    elif ce_actual.get("mode") == "duration" and execution_step.completed_at:
                        try:
                            dv = int(ce_actual.get("duration_value") or 0)
                            du = (ce_actual.get("duration_unit") or "days").strip().lower()
                            if du in VALID_EXPIRY_UNITS and dv > 0:
                                delta = expiry_duration_to_timedelta(dv, du)
                                expiry_dt = execution_step.completed_at + delta
                                expiry_iso_val = expiry_dt.isoformat()
                        except (TypeError, ValueError):
                            pass
                    else:
                        # Step-level fixed expiry (no custom_expiry_actual): compute from step output config
                        for od in step_outputs_def or []:
                            if isinstance(od, dict) and (od.get("name") or "").strip() == output_name:
                                ce_cfg = (od.get("extra_data") or {}).get("custom_expiry")
                                if (
                                    ce_cfg
                                    and ce_cfg.get("enabled")
                                    and (ce_cfg.get("mode") or "").strip() == "fixed_duration"
                                    and execution_step.completed_at
                                ):
                                    try:
                                        dv = int(ce_cfg.get("duration_value") or 0)
                                        du = (ce_cfg.get("duration_unit") or "days").strip().lower()
                                        if du in VALID_EXPIRY_UNITS and dv > 0:
                                            delta = expiry_duration_to_timedelta(dv, du)
                                            expiry_dt = execution_step.completed_at + delta
                                            expiry_iso_val = expiry_dt.isoformat()
                                    except (TypeError, ValueError):
                                        pass
                                break
                    if ready_iso_val and expiry_iso_val:
                        execution_errors.extend(
                            assert_expiry_after_ready_dates(output_name, ready_iso_val, expiry_iso_val)
                        )

                # Optional: map this output to an untracked item (reconcile at completion)
                untracked_item_id_raw = output.get("untracked_item_id")
                untracked_item_id_uuid = None
                if untracked_item_id_raw:
                    try:
                        untracked_item_id_uuid = UUID(untracked_item_id_raw)
                    except (ValueError, TypeError):
                        execution_warnings.append(
                            f"Invalid untracked_item_id for output '{output_name}'; skipping reconciliation."
                        )

                # Store creation parameters for atomic commit
                source_step_name = step_def.name if step_def else None
                output_creations.append(
                    {
                        "org_id": org_id,
                        "name": output_name,
                        "quantity": str(quantity_decimal),  # Convert Decimal to string for storage
                        "unit": output.get("unit", "units"),
                        "inventory_type": inventory_type,
                        "source_execution_id": execution_uuid,
                        "source_execution_step_id": execution_step_uuid,
                        "source_step_name": source_step_name,
                        "extra_data": extra_data if extra_data else None,
                        "untracked_item_id": untracked_item_id_uuid,
                        "quantity_decimal": quantity_decimal,
                    }
                )

        # Block inventory creation when output validation failed (e.g. custom_expiry warning > duration)
        if execution_errors:
            if not execution_step.execution_data:
                execution_step.execution_data = {}
            execution_step.execution_data["execution_errors"] = execution_errors
            db_session.commit()
            return jsonify({"error": "Execution failed", "details": execution_errors}), 400

        # FAILURE HANDLING: Persist warnings to execution_data for audit trail
        if execution_warnings:
            if not execution_step.execution_data:
                execution_step.execution_data = {}
            execution_step.execution_data["execution_warnings"] = execution_warnings

        # TRANSACTION INTEGRITY: Commit all inventory operations atomically
        # This ensures inventory consumption and output creation are atomic per execution step
        try:
            # Apply inventory updates
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY):
                for inventory_item, new_quantity in inventory_updates:
                    inventory_item.quantity = new_quantity

            # Create inventory items for outputs; when reconciling to untracked, reduce first then create only surplus
            from app.core.backend.reconciliation_service import reconcile_output_to_untracked_reduce_only

            for output_params in output_creations:
                untracked_item_id = output_params.pop("untracked_item_id", None)
                quantity_decimal = output_params.pop("quantity_decimal", None)
                output_name = output_params.get("name", "Unknown")
                output_unit = output_params.get("unit", "units")

                if untracked_item_id is not None and quantity_decimal is not None:
                    rec_result = reconcile_output_to_untracked_reduce_only(
                        org_id=org_id,
                        session=db_session,
                        user_id=getattr(g, "user_id", None) and str(g.user_id),
                        user_email=user_email,
                        untracked_item_id=untracked_item_id,
                        output_quantity=quantity_decimal,
                        output_unit=output_unit,
                        output_name=output_name,
                        execution_id=execution_uuid,
                        execution_step_id=execution_step_uuid,
                        current_step_actual_inputs=actual_inputs,
                    )
                    if rec_result.get("error"):
                        execution_warnings.append(f"Reconciliation for output '{output_name}': {rec_result['error']}")
                        continue
                    surplus = quantity_decimal
                    try:
                        surplus = Decimal(rec_result["surplus"])
                    except (InvalidOperation, ValueError, TypeError):
                        surplus = quantity_decimal
                    if surplus <= 0 or abs(surplus) < Decimal("0.0001"):
                        continue
                    output_params["quantity"] = str(surplus)
                    extra = dict(output_params.get("extra_data") or {})
                    extra["reconciled_untracked_item_id"] = str(untracked_item_id)
                    extra["quantity_reconciled"] = rec_result.get("reconciled_amount", "")
                    extra["surplus_to_live"] = rec_result.get("surplus", "")
                    output_params["extra_data"] = extra

                inventory_repo.create_inventory_item(**output_params)

            # Single commit for all inventory operations
            db_session.commit()
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.exception("Failed to commit inventory operations atomically")
            db_session.rollback()
            return jsonify({"error": "Failed to update inventory", "details": str(e)}), 500

        # Audit: when completed step has custom output expiry config (non-blocking)
        try:
            if step_outputs_for_audit:
                for out in step_outputs_for_audit:
                    if isinstance(out, dict):
                        ce = (out.get("extra_data") or {}).get("custom_expiry")
                        if ce and ce.get("enabled"):
                            user_id = getattr(g, "user_id", None)
                            log_action(
                                "custom_output_expiry_used",
                                "execution_step",
                                execution_step.id,
                                {
                                    "execution_id": str(execution_step.execution_id),
                                    "step_id": str(execution_step.step_id),
                                    "mode": ce.get("mode"),
                                    "duration_value": ce.get("duration_value"),
                                    "duration_unit": ce.get("duration_unit"),
                                    "warning_value": ce.get("warning_value"),
                                    "warning_unit": ce.get("warning_unit"),
                                    # Legacy fields (deprecated)
                                    "expiry_days": ce.get("expiry_days"),
                                    "rule_type": ce.get("rule_type", "custom_output_expiry"),
                                },
                                org_id,
                                user_id,
                            )
                            break
        except Exception as audit_err:
            import logging

            logging.getLogger(__name__).warning(
                "Audit log for custom_output_expiry_used failed: %s",
                audit_err,
                exc_info=True,
                extra={"event": "custom_output_expiry_audit_failure"},
            )

        response_data = {
            "id": str(execution_step.id),
            "status": execution_step.status.value,
            "completed_at": execution_step.completed_at.isoformat() if execution_step.completed_at else None,
        }
        if execution_warnings:
            response_data["execution_warnings"] = execution_warnings
        return (jsonify(response_data), 200)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # Log the full error for debugging; return message and details for diagnosis
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error completing execution step")
        err_detail = str(e) if e else "Unknown error"
        return jsonify({"error": "Failed to complete step", "details": err_detail}), 500


@core_bp.route("/api/core/inventory", methods=["GET"])
@requires_auth
def list_inventory():
    """List inventory items, optionally filtered by type or process"""
    org_id = UUID(g.org_id)
    inventory_type = request.args.get("type")
    process_id_str = request.args.get("process_id")

    process_id = None
    if process_id_str:
        try:
            process_id = UUID(process_id_str)
        except ValueError:
            return jsonify({"error": "Invalid process_id parameter"}), 400

    repo = InventoryRepository(db_session)
    items = repo.list_inventory_items(org_id=org_id, inventory_type=inventory_type, process_id=process_id)

    # System findings per item (all checks) for UI: red border + reasons in dropdown
    findings_by_id = corechecks.get_system_findings_by_item(org_id, db_session)

    # Import ExecutionStep and InventoryItem models for lookups
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem

    result = []
    for item in items:
        # Filter out items with zero or negative quantity
        # QUANTITY PRECISION: Use Decimal for safe comparison
        try:
            quantity_decimal = parse_stored_quantity_to_decimal(item.quantity)
            # Skip items with zero or negative quantity (including very small numbers)
            if quantity_decimal <= 0 or abs(quantity_decimal) < Decimal("0.0001"):
                continue  # Skip this item
        except (InvalidOperation, ValueError, TypeError):
            # If quantity is not a valid number, skip this item
            continue

        # If extra_data doesn't exist but source_execution_step_id does, look up execution_data from DB
        # This allows existing inventory items to show metadata
        extra_data = item.extra_data if item.extra_data else {}
        if not extra_data.get("execution_prompts") and item.source_execution_step_id:
            try:
                execution_step = (
                    db_session.query(ExecutionStep).filter(ExecutionStep.id == item.source_execution_step_id).first()
                )
                if execution_step and execution_step.execution_data:
                    execution_prompts, execution_trace = _split_execution_data(
                        execution_step.execution_data, completed_at=execution_step.completed_at
                    )
                    if execution_prompts:
                        extra_data["execution_prompts"] = execution_prompts
                    if execution_trace:
                        extra_data["execution_trace"] = execution_trace

                    # Also include variable inputs and outputs if not already in extra_data
                    # This is important for existing items that may not have variable_inputs populated
                    if not extra_data.get("variable_inputs"):
                        if execution_step.actual_inputs:
                            extra_data["variable_inputs"] = execution_step.actual_inputs
                        else:
                            # Ensure variable_inputs exists as empty list if not present
                            extra_data["variable_inputs"] = []
                    if not extra_data.get("variable_output") and execution_step.actual_outputs:
                        # Find matching output
                        output_name = item.name
                        matching_output = next(
                            (o for o in execution_step.actual_outputs if o.get("name") == output_name), None
                        )
                        if matching_output:
                            extra_data["variable_output"] = matching_output
            except Exception:
                # If lookup fails, just use existing extra_data
                pass

        # Look up previous steps data for intermediate products AND final products
        # DAG TRAVERSAL PERFORMANCE WARNING:
        # This recursive traversal happens inside list_inventory() which is called frequently.
        # For large DAGs with deep chains, this can become a scalability bottleneck.
        # Consider:
        # 1. Caching previous_steps_data in extra_data (but mark as derived/read-only)
        # 2. Separating traceability queries into a dedicated endpoint
        # 3. Adding depth limits or pagination for very deep chains
        # 4. Using materialized views or denormalized data for common queries
        #
        # Traverse the full chain of steps that produced the inputs
        previous_steps_data = []
        # Check if this is a WIP or final product that has variable inputs
        has_variable_inputs = extra_data.get("variable_inputs") and len(extra_data.get("variable_inputs", [])) > 0
        if (
            item.inventory_type == InventoryType.WORK_IN_PROGRESS.value
            or item.inventory_type == InventoryType.FINAL_PRODUCT.value
        ) and has_variable_inputs:
            try:
                # Helper function to recursively trace back through the chain of steps
                # PERFORMANCE: This recursive traversal can be expensive for deep DAGs
                # Consider adding depth limits or caching strategies for production use
                def trace_step_chain(
                    inventory_item_id, input_name=None, input_quantity=None, input_unit=None, visited_ids=None, depth=0
                ):
                    """Recursively trace back through all steps that produced this inventory item

                    Args:
                        inventory_item_id: UUID of inventory item to trace
                        input_name: Name of input consumed from this step
                        input_quantity: Quantity consumed
                        input_unit: Unit of quantity consumed
                        visited_ids: Set of visited inventory item IDs to prevent cycles
                        depth: Current recursion depth (for safety limits)

                    Returns:
                        List of step data dictionaries in chronological order (oldest first)
                    """
                    # Safety limit to prevent excessive recursion (configurable)
                    max_dag_depth = 50
                    if depth > max_dag_depth:
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(
                            f"DAG traversal depth limit ({max_dag_depth}) reached for inventory item {inventory_item_id}"
                        )
                        return []

                    if visited_ids is None:
                        visited_ids = set()

                    # Prevent infinite loops (cycle detection)
                    if inventory_item_id in visited_ids:
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(f"Cycle detected in DAG traversal at inventory item {inventory_item_id}")
                        return []
                    visited_ids.add(inventory_item_id)

                    steps_data = []

                    # Look up the input inventory item
                    input_inventory_item = (
                        db_session.query(InventoryItem)
                        .filter(InventoryItem.id == UUID(inventory_item_id), InventoryItem.org_id == org_id)
                        .first()
                    )

                    if not input_inventory_item or not input_inventory_item.source_execution_step_id:
                        return steps_data

                    # Look up the execution step that produced this input
                    input_execution_step = (
                        db_session.query(ExecutionStep)
                        .filter(ExecutionStep.id == input_inventory_item.source_execution_step_id)
                        .first()
                    )

                    if not input_execution_step:
                        return steps_data

                    # Build step data for this step
                    step_data = {
                        "step_name": input_execution_step.step.name if input_execution_step.step else None,
                        "step_number": input_execution_step.step_number,
                        "completed_at": input_execution_step.completed_at.isoformat()
                        if input_execution_step.completed_at
                        else None,
                    }

                    # Add input information (what was consumed from the previous step)
                    if input_name:
                        step_data["input_name"] = input_name
                    if input_quantity is not None:
                        step_data["input_quantity"] = input_quantity
                    if input_unit:
                        step_data["input_unit"] = input_unit

                    # Add full execution metadata for sourcemap/audit traceability (every piece traceable)
                    if input_execution_step.execution_data:
                        prev_prompts, prev_trace = _split_execution_data(
                            input_execution_step.execution_data,
                            completed_at=input_execution_step.completed_at,
                        )
                        if prev_prompts:
                            step_data["execution_prompts"] = prev_prompts
                        if prev_trace.get("completed_by") is not None:
                            step_data["completed_by"] = prev_trace["completed_by"]
                        if prev_trace.get("completed_at") is not None:
                            step_data["completed_at"] = prev_trace["completed_at"]
                        if prev_trace.get("execution_errors") is not None:
                            step_data["execution_errors"] = prev_trace["execution_errors"]
                        if prev_trace.get("execution_warnings") is not None:
                            step_data["execution_warnings"] = prev_trace["execution_warnings"]

                    # Add this step to the list
                    steps_data.append(step_data)

                    # Now trace back through this step's inputs
                    if input_execution_step.actual_inputs:
                        for prev_input_data in input_execution_step.actual_inputs:
                            prev_inventory_item_id = prev_input_data.get("inventory_item_id")
                            if prev_inventory_item_id:
                                # Recursively get steps that produced this input
                                # Pass the input information so we know what was consumed
                                # Increment depth to track recursion level
                                prev_steps = trace_step_chain(
                                    prev_inventory_item_id,
                                    input_name=prev_input_data.get("name"),
                                    input_quantity=prev_input_data.get("quantity"),
                                    input_unit=prev_input_data.get("unit"),
                                    visited_ids=visited_ids,
                                    depth=depth + 1,
                                )
                                # Prepend previous steps (so they appear in chronological order)
                                steps_data = prev_steps + steps_data

                    return steps_data

                # For each variable input, trace back through the full chain
                for input_data in extra_data["variable_inputs"]:
                    inventory_item_id = input_data.get("inventory_item_id")
                    if inventory_item_id:
                        # Trace the full chain of steps, passing the input information
                        chain_steps = trace_step_chain(
                            inventory_item_id,
                            input_name=input_data.get("name"),
                            input_quantity=input_data.get("quantity"),
                            input_unit=input_data.get("unit"),
                        )
                        previous_steps_data.extend(chain_steps)

                # Remove duplicates (same step_number and step_name) while preserving order
                seen = set()
                unique_steps = []
                for step in previous_steps_data:
                    step_key = (step.get("step_number"), step.get("step_name"))
                    if step_key not in seen:
                        seen.add(step_key)
                        unique_steps.append(step)
                previous_steps_data = unique_steps

                # Sort by step_number in descending order (most recent first, oldest at bottom)
                previous_steps_data.sort(key=lambda x: x.get("step_number", 0), reverse=True)

            except Exception:
                # If lookup fails, just continue without previous steps data
                import logging

                logger = logging.getLogger(__name__)
                logger.exception("Error tracing step chain")
                pass

        # EXTRA_DATA DISCIPLINE: previous_steps_data is derived/read-only data for display only
        # It should NEVER be persisted to the database - it's computed on-the-fly for traceability
        # This ensures we don't accidentally persist derived data that could become stale
        if previous_steps_data:
            extra_data["previous_steps_data"] = previous_steps_data

        # Get process name from execution if available
        process_name = None
        if item.source_execution_id:
            try:
                from app.core.db.models.execution import Execution
                from app.core.db.models.process import Process

                execution = db_session.query(Execution).filter(Execution.id == item.source_execution_id).first()
                if execution and execution.process_id:
                    process = db_session.query(Process).filter(Process.id == execution.process_id).first()
                    if process:
                        process_name = process.name
            except Exception:
                # If lookup fails, just continue without process name
                pass

        # For untracked items, resolve producing step (step that defines this output) for "Execute next step" button
        producing_step_id = None
        producing_step_name = None
        if extra_data.get("untracked") and item.source_execution_id:
            try:
                from app.core.db.models.execution import Execution

                execution = db_session.query(Execution).filter(Execution.id == item.source_execution_id).first()
                if execution and execution.process_id:
                    process_repo = ProcessRepository(db_session)
                    process_with_steps = process_repo.get_process_with_steps(execution.process_id, org_id)
                    if process_with_steps:
                        producing_step_id, producing_step_name = _find_producing_step(
                            process_with_steps, item.name, item.unit
                        )
                    # Fallback: if no output match (e.g. name/unit mismatch), use the step where item was added
                    if not producing_step_id and item.source_execution_step_id:
                        execution_step = (
                            db_session.query(ExecutionStep)
                            .filter(ExecutionStep.id == item.source_execution_step_id)
                            .first()
                        )
                        if execution_step:
                            producing_step_id = execution_step.step_id
                            if execution_step.step:
                                producing_step_name = execution_step.step.name
            except Exception:
                pass

        result.append(
            {
                "id": str(item.id),
                "name": item.name,
                "quantity": quantity_to_api_str(item.quantity),
                "unit": item.unit,
                "inventory_type": item.inventory_type,
                "barcode": item.barcode,
                "supplier": item.supplier,
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                "supplier_batch_number": item.supplier_batch_number,
                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
                "source_execution_step_id": str(item.source_execution_step_id)
                if item.source_execution_step_id
                else None,
                "source_output_id": str(item.source_output_id) if item.source_output_id else None,
                "source_step_name": item.source_step_name,
                "process_name": process_name,
                "producing_step_id": str(producing_step_id) if producing_step_id else None,
                "producing_step_name": producing_step_name,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "extra_data": extra_data,
                "system_findings": findings_by_id.get(str(item.id), []),
            }
        )

    return jsonify({"inventory_items": result}), 200


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
    lines: list[tuple[int, UUID, Decimal, str | None]] = []
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
        lines.append((idx + 1, item_id, waste_decimal, parsed_unit))

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
        [{"inventory_item_id": item_id, "quantity_wasted": w, "quantity_unit": u or ""} for _i, item_id, w, u in lines]
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
        staged: list[tuple[InventoryItem, Decimal, int, str | None]] = []

        for entry_idx, item_id, waste_decimal, req_unit in lines:
            item = inventory_repo.get_inventory_item_by_id_for_update(item_id, org_id)
            if not item:
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
            staged.append((item, waste_in_inv, entry_idx, req_unit))

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
            for item, waste_decimal, _entry_idx, request_unit in staged:
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
        for iid in item_ids:
            item = (
                db_session.query(InventoryItem).filter(InventoryItem.id == iid, InventoryItem.org_id == org_id).first()
            )
            if item:
                items_by_id[str(iid)] = {"name": item.name, "unit": item.unit}
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
            }
        )
    return jsonify({"wastage_records": result}), 200


@core_bp.route("/api/core/inventory/out-of-stock", methods=["GET"])
@requires_auth
def list_out_of_stock_raw_materials():
    """List raw materials with zero quantity for recall/traceability purposes.

    Returns raw materials that have been fully consumed (quantity = 0) but may still
    need to be traced for supplier recall scenarios.
    """
    org_id = UUID(g.org_id)

    from app.core.db.models.inventory_item import InventoryItem

    # Query raw materials with exactly zero quantity
    # Note: We use exact zero comparison, not near-zero, as some customer processes
    # may require very precise measurements where small quantities are still valid stock
    items = (
        db_session.query(InventoryItem)
        .filter(InventoryItem.org_id == org_id)
        .filter(InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value)
        .order_by(InventoryItem.purchase_date.desc().nullslast(), InventoryItem.created_at.desc())
        .all()
    )

    result = []
    for item in items:
        quantity_decimal = parse_stored_quantity_to_decimal(item.quantity)
        if quantity_decimal != Decimal("0"):
            continue

        result.append(
            {
                "id": str(item.id),
                "name": item.name,
                "quantity": quantity_to_api_str(item.quantity),
                "unit": item.unit,
                "inventory_type": item.inventory_type,
                "supplier": item.supplier,
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                "supplier_batch_number": item.supplier_batch_number,
                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
                "source_execution_step_id": str(item.source_execution_step_id)
                if item.source_execution_step_id
                else None,
                "source_step_name": item.source_step_name,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "extra_data": item.extra_data if item.extra_data else {},
                "is_out_of_stock": True,
            }
        )

    return jsonify({"inventory_items": result}), 200


corechecks.register_routes(core_bp)
reconciliation_routes.register_routes(core_bp)
inventory_upload_routes.register_routes(core_bp)
evidence_routes.register_routes(core_bp)
process_docs_routes.register_routes(core_bp)


@core_bp.route("/api/core/reset-demo-db", methods=["POST"])
@requires_auth
def reset_demo_db_route():
    """Reset and populate DB with demo data for demo@whistlebird.co.nz. Only available in test or local environment."""
    if config.environment not in ("test", "local"):
        return jsonify({"error": "Reset demo DB is only available in test or local environment", "success": False}), 403
    from app.core.utils.resetdb import reset_demo_db

    session = db_session()
    try:
        result = reset_demo_db(session)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result), 200
    except Exception as e:
        import logging

        try:
            session.rollback()
        except Exception:
            pass
        logging.getLogger(__name__).exception("reset_demo_db failed: %s", e)
        return jsonify({"success": False, "message": str(e), "error": "RESET_FAILED"}), 500


@core_bp.route("/api/core/inventory", methods=["POST"])
@requires_auth
def create_inventory_item():
    """Create a new inventory item (typically raw material). Supports barcode; enforces product identity when barcode exists."""
    org_id = UUID(g.org_id)
    data = request.get_json()

    name = (data.get("name") or "").strip() or None
    quantity = data.get("quantity")
    unit = (data.get("unit") or "").strip() or None
    inventory_type = data.get("inventory_type", InventoryType.RAW_MATERIAL.value)
    barcode = (data.get("barcode") or "").strip() or None

    if quantity is None or (isinstance(quantity, str) and not quantity.strip()):
        return jsonify({"error": "quantity is required"}), 400
    try:
        qty_val = float(quantity)
        if qty_val <= 0:
            return jsonify({"error": "quantity must be greater than 0"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be a valid number"}), 400

    repo = InventoryRepository(db_session)
    try:
        # If barcode provided and we have an existing row for it, add quantity to it (one row per barcode per org)
        if barcode:
            existing = repo.find_by_barcode(org_id, barcode)
            if existing:
                if name is not None and name != existing.name:
                    return jsonify({"error": "Product name does not match existing product for this barcode"}), 409
                if unit is not None and unit != existing.unit:
                    return jsonify({"error": "Unit does not match existing product for this barcode"}), 409
                # Add quantity to existing item; supplier is stock-level (stored in audit only, row.supplier unchanged)
                supplier = (data.get("supplier") or "").strip() or None
                purchase_date = None
                if data.get("purchase_date"):
                    purchase_date = datetime.fromisoformat(data.get("purchase_date").replace("Z", "+00:00")).date()
                expiry_date = None
                if data.get("expiry_date"):
                    expiry_date = datetime.fromisoformat(data.get("expiry_date").replace("Z", "+00:00")).date()
                source_method = (data.get("source_method") or "barcode_scan").strip()
                if source_method not in ("manual", "csv_upload", "barcode_scan"):
                    source_method = "barcode_scan"
                audit_entry = {
                    "user_id": str(g.user_id) if getattr(g, "user_id", None) else None,
                    "timestamp_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source_method": source_method,
                    "quantity_added": str(quantity),
                    "supplier": supplier,
                    "purchase_date": purchase_date.isoformat() if purchase_date else None,
                    "expiry_date": expiry_date.isoformat() if expiry_date else None,
                    "supplier_batch_number": (data.get("supplier_batch_number") or "").strip() or None,
                }
                extra_merge = {"inventory_audit_history": [audit_entry]}
                updated = repo.add_quantity_to_inventory_item(
                    existing.id, org_id, str(quantity), extra_data_merge=extra_merge, commit=True
                )
                if not updated:
                    return jsonify({"error": "Failed to add quantity to existing item"}), 500
                return (
                    jsonify(
                        {
                            "id": str(updated.id),
                            "name": updated.name,
                            "quantity": quantity_to_api_str(updated.quantity),
                            "unit": updated.unit,
                            "inventory_type": updated.inventory_type,
                            "supplier": updated.supplier,
                            "purchase_date": updated.purchase_date.isoformat() if updated.purchase_date else None,
                            "supplier_batch_number": updated.supplier_batch_number,
                            "expiry_date": updated.expiry_date.isoformat() if updated.expiry_date else None,
                            "created_at": updated.created_at.isoformat() if updated.created_at else None,
                            "quantity_added": True,
                        }
                    ),
                    200,
                )
            elif not name or not unit:
                return jsonify({"error": "name and unit are required for new barcode"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400
        if not unit:
            return jsonify({"error": "unit is required"}), 400

        supplier = (data.get("supplier") or "").strip() or None
        # Parse purchase date if provided
        purchase_date = None
        if data.get("purchase_date"):
            purchase_date = datetime.fromisoformat(data.get("purchase_date").replace("Z", "+00:00")).date()

        expiry_date = None
        if data.get("expiry_date"):
            expiry_date = datetime.fromisoformat(data.get("expiry_date").replace("Z", "+00:00")).date()

        # Optional traceability (e.g. in-flow "add missing output" from execution step)
        source_execution_id = None
        if data.get("source_execution_id"):
            source_execution_id = UUID(data["source_execution_id"])
        source_execution_step_id = None
        if data.get("source_execution_step_id"):
            source_execution_step_id = UUID(data["source_execution_step_id"])
        source_output_id = None
        if data.get("source_output_id"):
            source_output_id = UUID(data["source_output_id"])

        extra_data = dict(data.get("metadata") or {})
        source_method = (data.get("source_method") or "manual").strip()
        if source_method not in ("manual", "csv_upload", "barcode_scan"):
            source_method = "manual"
        audit_entry = {
            "user_id": str(g.user_id) if getattr(g, "user_id", None) else None,
            "timestamp_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_method": source_method,
        }
        history = list(extra_data.get("inventory_audit_history") or [])
        history.append(audit_entry)
        extra_data["inventory_audit_history"] = history
        if data.get("untracked"):
            notes = (extra_data.get("notes") or data.get("notes") or "").strip()
            if not notes:
                return jsonify({"error": "notes are required when adding an untracked item"}), 400
            extra_data["notes"] = notes
            # Invariant: untracked items must always have remaining_balance_to_reconcile for reduce_only logic.
            extra_data["untracked"] = True  # Flag for reconciliation/sourcemap banners
            try:
                qty_val = float(quantity) if quantity is not None else 0
                extra_data["remaining_balance_to_reconcile"] = str(qty_val) if qty_val > 0 else "0"
            except (TypeError, ValueError):
                extra_data["remaining_balance_to_reconcile"] = str(quantity) if quantity else "0"

        try:
            item = repo.create_inventory_item(
                org_id=org_id,
                name=name,
                quantity=str(quantity),
                unit=unit,
                inventory_type=inventory_type,
                supplier=supplier,
                barcode=barcode,
                purchase_date=purchase_date,
                supplier_batch_number=data.get("supplier_batch_number"),
                expiry_date=expiry_date,
                source_execution_id=source_execution_id,
                source_execution_step_id=source_execution_step_id,
                source_output_id=source_output_id,
                extra_data=extra_data if extra_data else None,
            )
        except IntegrityError:
            db_session.rollback()
            return jsonify(
                {"error": "Duplicate barcode for this organisation; try again or add quantity to existing item."}
            ), 409

        return (
            jsonify(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "quantity": quantity_to_api_str(item.quantity),
                    "unit": item.unit,
                    "inventory_type": item.inventory_type,
                    "supplier": item.supplier,
                    "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                    "supplier_batch_number": item.supplier_batch_number,
                    "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
            ),
            201,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        # Log the full error for debugging but return generic message to client
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error creating process")
        return jsonify({"error": "Failed to create process"}), 500


@core_bp.route("/api/core/inventory/<item_id>", methods=["PUT"])
@requires_auth
def update_inventory_item(item_id):
    """Update an existing inventory item"""
    org_id = UUID(g.org_id)
    data = request.get_json()

    name = data.get("name")
    quantity = data.get("quantity")
    unit = data.get("unit")
    inventory_type = data.get("inventory_type", InventoryType.RAW_MATERIAL.value)

    if not all([name, quantity, unit]):
        return jsonify({"error": "name, quantity, and unit are required"}), 400

    repo = InventoryRepository(db_session)
    try:
        # Parse purchase date if provided
        purchase_date = None
        if data.get("purchase_date"):
            purchase_date = datetime.fromisoformat(data.get("purchase_date").replace("Z", "+00:00")).date()

        expiry_date = None
        if data.get("expiry_date"):
            expiry_date = datetime.fromisoformat(data.get("expiry_date").replace("Z", "+00:00")).date()

        # Get existing item
        item = repo.get_inventory_item_by_id(UUID(item_id), org_id)
        if not item:
            return jsonify({"error": "Inventory item not found"}), 404

        # Update item
        item.name = name
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
            item.quantity = coerce_stored_quantity(quantity)
        item.unit = unit
        item.inventory_type = inventory_type
        item.supplier = data.get("supplier")
        item.purchase_date = purchase_date
        item.supplier_batch_number = data.get("supplier_batch_number")
        item.expiry_date = expiry_date
        if data.get("metadata"):
            item.extra_data = data.get("metadata")

        db_session.commit()
        db_session.refresh(item)

        return (
            jsonify(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "quantity": quantity_to_api_str(item.quantity),
                    "unit": item.unit,
                    "inventory_type": item.inventory_type,
                    "supplier": item.supplier,
                    "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                    "supplier_batch_number": item.supplier_batch_number,
                    "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
            ),
            200,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error updating inventory item")
        return jsonify({"error": "Failed to update inventory item"}), 500


@core_bp.route("/api/core/inventory/<item_id>", methods=["DELETE"])
@requires_auth
def delete_inventory_item(item_id):
    """Delete an inventory item"""
    org_id = UUID(g.org_id)
    repo = InventoryRepository(db_session)

    try:
        success = repo.delete_inventory_item(UUID(item_id), org_id)
        if not success:
            return jsonify({"error": "Inventory item not found"}), 404

        return jsonify({"message": "Inventory item deleted successfully"}), 200
    except Exception:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error deleting inventory item")
        return jsonify({"error": "Failed to delete inventory item"}), 500


@core_bp.route("/api/core/inventory/trace/<raw_material_id>", methods=["GET"])
@requires_auth
def trace_raw_material(raw_material_id: str):
    """Trace forward from a raw material to find all connected intermediates and final products

    Uses DAG traversal to find all inventory items that trace back to this raw material.
    Returns only items with quantity > 0, except for the raw material itself (if consumed).
    """
    from app.core.backend.dagtraversal import trace_forward, validate_item_uuid
    from app.core.db.models.inventory_item import InventoryItem

    org_id = UUID(g.org_id)
    raw_material_uuid, err = validate_item_uuid(raw_material_id)
    if err or raw_material_uuid is None:
        return jsonify({"error": err or "Invalid raw material ID"}), 400

    raw_material = (
        db_session.query(InventoryItem)
        .filter(InventoryItem.id == raw_material_uuid, InventoryItem.org_id == org_id)
        .first()
    )
    if not raw_material:
        return jsonify({"error": "Raw material not found"}), 404

    result = trace_forward(
        org_id,
        db_session,
        raw_material_uuid,
        include_quantity_filter=True,
        root_item_id=raw_material_uuid,
    )
    connected_items = result["items"]
    connections = result["connections"]

    # Match original API: add direct connection from raw material to every connected item (execution_id as link)
    raw_id_str = str(raw_material_uuid)
    conn_pairs = {(c["from_id"], c["to_id"]) for c in connections}
    for item in connected_items:
        if item["id"] == raw_id_str:
            continue
        exec_id = item.get("source_execution_id")
        if exec_id and (raw_id_str, item["id"]) not in conn_pairs:
            connections.append({"from_id": raw_id_str, "to_id": item["id"], "execution_id": exec_id})
            conn_pairs.add((raw_id_str, item["id"]))

    # Only return connections where both from_id and to_id are inventory item IDs in the response.
    # This prevents the source map table from showing "TO <uuid>" when an ID is missing (e.g. execution_id).
    item_ids = {item["id"] for item in connected_items} | {raw_id_str}
    connections = [c for c in connections if c.get("from_id") in item_ids and c.get("to_id") in item_ids]

    raw_material_data = {
        "id": str(raw_material.id),
        "name": raw_material.name,
        "quantity": quantity_to_api_str(raw_material.quantity),
        "unit": raw_material.unit,
        "inventory_type": raw_material.inventory_type,
        "supplier": raw_material.supplier,
        "purchase_date": raw_material.purchase_date.isoformat() if raw_material.purchase_date else None,
        "supplier_batch_number": raw_material.supplier_batch_number,
        "expiry_date": raw_material.expiry_date.isoformat() if raw_material.expiry_date else None,
        "source_execution_id": str(raw_material.source_execution_id) if raw_material.source_execution_id else None,
        "source_execution_step_id": str(raw_material.source_execution_step_id)
        if raw_material.source_execution_step_id
        else None,
        "source_step_name": raw_material.source_step_name,
        "process_name": None,
        "created_at": raw_material.created_at.isoformat() if raw_material.created_at else None,
        "extra_data": raw_material.extra_data if raw_material.extra_data else {},
    }
    if not any(item["id"] == str(raw_material.id) for item in connected_items):
        connected_items.insert(0, raw_material_data)

    intermediates = [item for item in connected_items if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value]
    finals = [item for item in connected_items if item["inventory_type"] == InventoryType.FINAL_PRODUCT.value]

    return jsonify(
        {
            "raw_material": raw_material_data,
            "intermediates": intermediates,
            "finals": finals,
            "all_items": connected_items,
            "connections": connections,
        }
    ), 200


@core_bp.route("/api/core/inventory/trace-backward/<inventory_item_id>", methods=["GET"])
@requires_auth
def trace_inventory_backward(inventory_item_id: str):
    """Trace backward from any inventory item (raw, intermediate, or final) to find all source items

    Uses DAG traversal to find all inventory items that contributed to this item.
    Returns only items with quantity > 0, except for the traced item itself (if consumed).
    """
    from app.core.backend.dagtraversal import trace_backward, validate_item_uuid
    from app.core.db.models.inventory_item import InventoryItem

    org_id = UUID(g.org_id)
    item_uuid, err = validate_item_uuid(inventory_item_id)
    if err or item_uuid is None:
        return jsonify({"error": err or "Invalid inventory item ID"}), 400

    traced_item = (
        db_session.query(InventoryItem).filter(InventoryItem.id == item_uuid, InventoryItem.org_id == org_id).first()
    )
    if not traced_item:
        return jsonify({"error": "Inventory item not found"}), 404

    result = trace_backward(
        org_id,
        db_session,
        item_uuid,
        include_quantity_filter=True,
        traced_item_id=item_uuid,
    )
    all_result_items = result["items"]
    connections = result["connections"]

    # Match original API: add direct connection from every source item to traced item (for sourcemap arrows)
    traced_id_str = str(traced_item.id)
    exec_id_str = str(traced_item.source_execution_id) if traced_item.source_execution_id else None
    if exec_id_str:
        existing_to_traced = {c["from_id"] for c in connections if c.get("to_id") == traced_id_str}
        for item in all_result_items:
            if item["id"] == traced_id_str:
                continue
            if item["id"] not in existing_to_traced:
                connections.append({"from_id": item["id"], "to_id": traced_id_str, "execution_id": exec_id_str})
                existing_to_traced.add(item["id"])

    # Traced item data: use enriched entry from result if present, else build from ORM
    traced_item_data = next(
        (item for item in all_result_items if item["id"] == str(traced_item.id)),
        None,
    )
    if traced_item_data is None:
        traced_extra = traced_item.extra_data if traced_item.extra_data else {}
        traced_item_data = {
            "id": str(traced_item.id),
            "name": traced_item.name,
            "quantity": quantity_to_api_str(traced_item.quantity),
            "unit": traced_item.unit,
            "inventory_type": traced_item.inventory_type,
            "supplier": traced_item.supplier,
            "purchase_date": traced_item.purchase_date.isoformat() if traced_item.purchase_date else None,
            "supplier_batch_number": traced_item.supplier_batch_number,
            "expiry_date": traced_item.expiry_date.isoformat() if traced_item.expiry_date else None,
            "source_execution_id": str(traced_item.source_execution_id) if traced_item.source_execution_id else None,
            "source_execution_step_id": str(traced_item.source_execution_step_id)
            if traced_item.source_execution_step_id
            else None,
            "source_step_name": traced_item.source_step_name,
            "process_name": None,
            "created_at": traced_item.created_at.isoformat() if traced_item.created_at else None,
            "extra_data": traced_extra,
        }

    source_items_without_traced = [item for item in all_result_items if item["id"] != str(traced_item.id)]
    raw_materials = [
        item for item in source_items_without_traced if item["inventory_type"] == InventoryType.RAW_MATERIAL.value
    ]
    intermediates = [
        item for item in source_items_without_traced if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value
    ]

    # Only return connections where both from_id and to_id are inventory item IDs in the response.
    # Prevents the source map table from showing "TO <uuid>" when an ID is missing (e.g. execution_id).
    backward_item_ids = {item["id"] for item in all_result_items}
    connections = [
        c for c in connections if c.get("from_id") in backward_item_ids and c.get("to_id") in backward_item_ids
    ]

    return jsonify(
        {
            "traced_item": traced_item_data,
            "raw_materials": raw_materials,
            "intermediates": intermediates,
            "all_items": source_items_without_traced,
            "connections": connections,
        }
    ), 200


@core_bp.route("/api/core/execution-metadata", methods=["GET"])
@requires_auth
def get_execution_metadata():
    """Get unique execution metadata values for search/tracing.
    Returns all unique key-value pairs from execution_data across all execution steps.
    """
    from app.core.db.models.inventory_item import InventoryItem

    org_id = UUID(g.org_id)

    # Get all executions for this org
    execution_repo = ExecutionRepository(db_session)
    executions = execution_repo.list_executions(org_id)

    # Collect unique metadata key-value pairs
    metadata_map = {}  # key -> set of values
    metadata_items = []  # List of {key, value, execution_ids, inventory_item_ids}

    # Fields to exclude from metadata display
    exclude_fields = {"completed_by_email", "completed_by_user_id", "execution_errors"}

    for execution in executions:
        if not execution.execution_steps:
            continue
        for step in execution.execution_steps:
            if not step.execution_data:
                continue
            for key, value in step.execution_data.items():
                if key in exclude_fields:
                    continue
                if value is None or value == "":
                    continue
                # Convert value to string for consistency
                str_value = str(value)
                # Create a unique key for this metadata pair
                pair_key = f"{key}::{str_value}"
                if pair_key not in metadata_map:
                    metadata_map[pair_key] = {
                        "key": key,
                        "value": str_value,
                        "execution_ids": set(),
                        "execution_step_ids": set(),
                    }
                metadata_map[pair_key]["execution_ids"].add(str(execution.id))
                metadata_map[pair_key]["execution_step_ids"].add(str(step.id))

    # Convert to list format
    for pair_key, data in metadata_map.items():
        # Find inventory items linked to these execution steps
        inventory_item_ids = []
        for step_id in data["execution_step_ids"]:
            items = (
                db_session.query(InventoryItem)
                .filter(InventoryItem.org_id == org_id)
                .filter(InventoryItem.source_execution_step_id == UUID(step_id))
                .all()
            )
            for item in items:
                inventory_item_ids.append(str(item.id))

        metadata_items.append(
            {
                "key": data["key"],
                "value": data["value"],
                "display_key": data["key"].replace("_", " ").title(),
                "execution_count": len(data["execution_ids"]),
                "execution_ids": list(data["execution_ids"]),
                "inventory_item_ids": inventory_item_ids,
            }
        )

    # Sort by key then value
    metadata_items.sort(key=lambda x: (x["key"].lower(), x["value"].lower()))

    return jsonify({"metadata": metadata_items}), 200


@core_bp.route("/api/core/metrics", methods=["GET"])
@requires_auth
def get_metrics():
    """Get summary metrics for the dashboard"""
    org_id = UUID(g.org_id)

    process_repo = ProcessRepository(db_session)
    execution_repo = ExecutionRepository(db_session)
    inventory_repo = InventoryRepository(db_session)

    # Total processes
    processes = process_repo.list_processes(org_id)
    total_processes = len(processes)

    # Active executions
    executions = execution_repo.list_executions(org_id, status=ExecutionStatus.IN_PROGRESS)
    active_executions = len(executions)

    # Completed executions
    completed_executions = execution_repo.list_executions(org_id, status=ExecutionStatus.COMPLETED)
    completed_count = len(completed_executions)

    # Inventory items
    inventory_items = inventory_repo.list_inventory_items(org_id)
    raw_materials = [i for i in inventory_items if i.inventory_type == InventoryType.RAW_MATERIAL.value]
    wip = [i for i in inventory_items if i.inventory_type == InventoryType.WORK_IN_PROGRESS.value]
    final_products = [i for i in inventory_items if i.inventory_type == InventoryType.FINAL_PRODUCT.value]

    return (
        jsonify(
            {
                "total_processes": total_processes,
                "active_executions": active_executions,
                "completed_executions": completed_count,
                "inventory_items": {
                    "total": len(inventory_items),
                    "raw_materials": len(raw_materials),
                    "work_in_progress": len(wip),
                    "final_products": len(final_products),
                },
            }
        ),
        200,
    )
