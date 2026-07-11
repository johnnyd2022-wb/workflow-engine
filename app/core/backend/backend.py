"""Core backend API routes for process execution platform"""

import hashlib
import json
import logging
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, send_from_directory, session
from pydantic import ValidationError
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError

from app.api.routes.auth_routes import limiter
from app.core.backend import corechecks, inventory_upload_routes, reconciliation_routes
from app.core.backend.checks.output_ready_date_check import is_inventory_item_ready_for_consumption
from app.core.backend.complete_step_payload import (
    MAX_COMPLETE_STEP_CONTENT_LENGTH,
    CompleteStepRequestBody,
    validate_json_blob,
)
from app.core.backend.complete_step_payload import (
    MAX_JSON_DEPTH as _STRIP_MAX_DEPTH,
)
from app.core.backend.event_writer import EventWriter
from app.core.backend.evidence import evidence_routes
from app.core.backend.evidence.evidence_service import list_evidence_for_execution, list_evidence_for_executions_batch
from app.core.backend.process_docs import process_docs_routes
from app.core.backend.reconciliation_service import _find_producing_step
from app.core.db import SessionLocal, db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution import Execution, ExecutionStatus
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
from app.core.utils.internal_counters import get_counter_snapshot, inc_counter
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

# GET /api/core/inventory: bound nested display-only lists (aligned with flows2.html caps; not persisted).
LIST_INVENTORY_MAX_PREVIOUS_STEPS = 80
LIST_INVENTORY_MAX_AUDIT_HISTORY = 120
LIST_INVENTORY_MAX_RECONCILIATION_HISTORY = 60


_LIST_ITEM_MAX_CHARS = 4096
_LIST_ITEM_MAX_NESTED = 20


def _trim_value(v):
    """Cap strings, lists, and dicts one level deep — prevents deep payload explosions."""
    if isinstance(v, str) and len(v) > _LIST_ITEM_MAX_CHARS:
        return v[:_LIST_ITEM_MAX_CHARS] + "…"
    if isinstance(v, list):
        return v[:_LIST_ITEM_MAX_NESTED]
    if isinstance(v, dict):
        return {k: _trim_value(val) for k, val in list(v.items())[:_LIST_ITEM_MAX_NESTED]}
    return v


def _safe_slice_list(lst: list, max_len: int) -> list:
    """Slice list and recursively bound values inside dict items."""
    out = []
    for item in lst[:max_len]:
        if isinstance(item, dict):
            out.append({k: _trim_value(v) for k, v in item.items()})
        else:
            out.append(item)
    return out


def _bound_inventory_extra_data_for_list_response(extra_data: dict) -> dict:
    """Clamp large nested lists in extra_data for list responses (operator UI only)."""
    if not extra_data:
        return extra_data
    out = dict(extra_data)
    psd = out.get("previous_steps_data")
    if isinstance(psd, list):
        out["previous_steps_data"] = _safe_slice_list(psd, LIST_INVENTORY_MAX_PREVIOUS_STEPS)
    ah = out.get("inventory_audit_history")
    if isinstance(ah, list):
        sliced = _safe_slice_list(ah, LIST_INVENTORY_MAX_AUDIT_HISTORY)
        out["inventory_audit_history"] = [
            {k: v for k, v in entry.items() if k != "user_id"} if isinstance(entry, dict) else entry for entry in sliced
        ]
    rh = out.get("reconciliation_history")
    if isinstance(rh, list):
        out["reconciliation_history"] = _safe_slice_list(rh, LIST_INVENTORY_MAX_RECONCILIATION_HISTORY)
    return out


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

_ALLOWED_RETURN_PREFIX = "/core/flows"  # keep in sync with ALLOWED_PREFIX in batch-start-scripts.html


def _safe_flow_return_to(value, process_id) -> str:
    """
    Only allow same-app paths under /core/flows.
    Blocks open redirects, protocol-relative URLs, encoded bypasses, and path traversal.
    """
    from posixpath import normpath
    from urllib.parse import unquote, urlparse, urlunparse

    default = f"/core/flows?id={process_id}"
    if value is None or not str(value).strip():
        return default
    s0 = str(value).strip()
    # Encoded backslash (%5c) can normalize to "/" or "\" in clients — reject early.
    if "%5c" in s0.lower():
        return default
    # Decode percent-encoding (may reveal // or schemes hidden as %2F%2F…).
    # Tradeoff: decoding may transform inputs; we cap normalization at 2 passes on purpose.
    s = unquote(s0)
    if s != s0:
        s = unquote(s)
    if "\\" in s:
        return default
    low = s.lower()
    if low.startswith(("javascript:", "data:", "vbscript:")):
        return default
    if "://" in s:
        return default
    if s.startswith("//"):
        return default
    if not s.startswith("/"):
        return default
    parsed = urlparse(s)
    # Only allow path-only relative URLs (no scheme like http:foo or file:).
    if parsed.scheme:
        return default
    if parsed.netloc:
        return default
    raw_path = parsed.path or "/"
    norm_path = normpath(raw_path)
    if norm_path in ("", "."):
        return default
    if not norm_path.startswith("/"):
        norm_path = "/" + norm_path
    if "\\" in norm_path:
        return default
    # Stay within process workspace routes (blocks /core/flows/../../admin → /admin)
    if norm_path != _ALLOWED_RETURN_PREFIX and not norm_path.startswith(_ALLOWED_RETURN_PREFIX + "/"):
        return default
    if parsed.fragment:
        frag = unquote(parsed.fragment)
        if frag != parsed.fragment:
            frag = unquote(frag)
        frag_low = frag.lower().lstrip()
        if (
            frag_low.startswith("//")
            or "://" in frag_low
            or "\\" in frag_low
            or frag_low.startswith(("javascript:", "data:", "vbscript:"))
        ):
            return default
    safe = urlunparse(("", "", norm_path, "", parsed.query, parsed.fragment))
    return safe


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

    [n for (n,) in q.with_entities(Step.step_number).all() if isinstance(n, int)]
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
        # If a process id is present, the wizard might have been started via the API
        # (e.g. Save step creates the process) without first hitting /core/flows/create,
        # so the session sequencing state for this process id was never initialized.
        # In that case, initialize in-place and allow navigation to the requested page.
        if process_id is not None:
            bucket["started"] = True
            bucket["max_step"] = max(int(bucket.get("max_step") or 1), int(requested or 1))
            session.modified = True
        else:
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


def _strip_trace_keys_recursive(obj: Any, depth: int = 0) -> Any:
    """
    Remove trace keys at any depth.

    **Contract:** Call only on trees that already passed ``validate_json_blob`` (same MAX_JSON_DEPTH).
    If depth exceeds the guard, something bypassed validation — fail loudly rather than return partly stripped data.
    """
    if depth > _STRIP_MAX_DEPTH:
        raise RuntimeError(
            "_strip_trace_keys_recursive exceeded MAX_JSON_DEPTH; "
            "execution_data must be validated with validate_json_blob before strip."
        )
    if isinstance(obj, dict):
        return {
            k: _strip_trace_keys_recursive(v, depth + 1) for k, v in obj.items() if k not in _EXECUTION_DATA_TRACE_KEYS
        }
    if isinstance(obj, list):
        return [_strip_trace_keys_recursive(x, depth + 1) for x in obj]
    return obj


def _strip_incoming_execution_trace_keys(execution_data: dict | None) -> dict:
    """
    Remove audit/trace keys from the client JSON payload before merge/persist (recursive).

    For HTTP: only call after ``validate_json_blob`` on the same object so depth/node invariants match.
    """
    if not execution_data:
        return {}
    cleaned = _strip_trace_keys_recursive(execution_data, 0)
    return cleaned if isinstance(cleaned, dict) else {}


def _parse_uuid(v: str | None) -> UUID | None:
    """Parse v as a UUID, returning None on any failure. Avoids double-parsing and 500s on malformed DB values."""
    if not v:
        return None
    try:
        return UUID(str(v))
    except (ValueError, AttributeError):
        return None


def _hydrate_step_data(items: list[dict], db_session, org_id: UUID) -> None:
    """
    Attach step_data to each item dict in-place.

    Bulk-fetches ExecutionStep records for all items that have a source_execution_step_id,
    joining through Execution to enforce org_id (defense-in-depth against upstream scoping drift).
    Sets item["step_data"] = {completed_at, actual_inputs, actual_outputs} or None.
    """
    from app.core.db.models.execution import Execution as ExecutionModel
    from app.core.db.models.execution_step import ExecutionStep as ExecutionStepModel

    # Parse UUIDs once; raw value → UUID map eliminates second-pass parsing in the hydration loop.
    raw_to_uuid: dict[str, UUID] = {
        raw: uid for it in items if (raw := it.get("source_execution_step_id")) and (uid := _parse_uuid(raw))
    }
    step_ids: set[UUID] = set(raw_to_uuid.values())

    # UUID-keyed map: avoids str/UUID mismatch at lookup time.
    step_map: dict[UUID, ExecutionStepModel] = {}
    if step_ids:
        for _s in (
            db_session.query(ExecutionStepModel)
            .join(ExecutionModel, ExecutionStepModel.execution_id == ExecutionModel.id)
            .filter(ExecutionStepModel.id.in_(step_ids), ExecutionModel.org_id == org_id)
            .all()
        ):
            step_map[_s.id] = _s

    for _item in items:
        uid = raw_to_uuid.get(_item.get("source_execution_step_id"))
        _s = step_map.get(uid) if uid else None
        if uid and _s is None:
            logger.debug("_hydrate_step_data: ExecutionStep %s not found (org_id=%s)", uid, org_id)
        _item["step_data"] = (
            {
                "completed_at": _to_iso_timestamp(_s.completed_at),
                "actual_inputs": _s.actual_inputs,
                "actual_outputs": _s.actual_outputs,
            }
            if _s
            else None
        )


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
    return render_template("core/core2.html", active_page="core", show_reset_db=show_reset_db)


@core_bp.route("/core/dashboard", methods=["GET"])
@requires_auth
def dashboard():
    return render_template("dashboard/dashboard.html", active_page="dashboard")


@core_bp.route("/core/integrations", methods=["GET"])
@requires_auth
def integrations():
    return redirect("/crm/configuration")


@core_bp.route("/core/settings", methods=["GET"])
@requires_auth
def settings():
    return render_template("settings/settings.html", active_page="settings")


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


@core_bp.route("/core/inventory/live", methods=["GET"])
@requires_auth
def inventory_live_view():
    """Dedicated live inventory experience (drill-in from Core inventory tab)."""
    return render_template("core/core2.html", active_page="core", core2_focus="inventory_live")


@core_bp.route("/core/executions/live", methods=["GET"])
@requires_auth
def executions_live_view():
    """Dedicated active batches experience (drill-in from Core product workflows tab)."""
    return render_template("core/core2.html", active_page="core", core2_focus="active_batches_live")


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


@core_bp.route("/core/flows/executions/step", methods=["GET"])
@requires_auth
def execution_step_page():
    """
    Dedicated routeable execution step screen (replaces execute-step modal).

    Query params:
    - execution_id: required (UUID-like string)
    - process_id: required (UUID-like string)
    - return_to: optional URL for Back CTA
    """
    # Option B: reuse the existing batches/start screen as the canonical execute-step UI.
    # Keep this route as a compatibility alias.
    from urllib.parse import urlencode

    args = dict(request.args)
    process_id = args.get("process_id")

    # Map to the batches/start contract:
    # - process_id -> id
    # - keep execution_id, step_id, draft, return_to as-is
    if process_id and "id" not in args:
        args["id"] = process_id
    args.pop("process_id", None)

    dest = "/core/flows/batches/start"
    q = urlencode([(k, v) for k, v in args.items() if v is not None and v != ""])
    return redirect(dest + (("?" + q) if q else ""))


@core_bp.route("/core/flows/batches/start", methods=["GET"])
@requires_auth
def flows_batches_start():
    """
    Canonical execute-step screen (Option B).

    Supports:
    - Draft start: ?draft=1&id=<process_id>&step_id=<step_id>
    - Existing execution: ?execution_id=<id>&id=<process_id>
    - Optional: return_to=<url>
    """
    process_id = _flow_process_id_from_request()
    if process_id is None:
        abort(400)
    _assert_flow_process_access(process_id)

    execution_id = request.args.get("execution_id")
    step_id = request.args.get("step_id")
    draft = request.args.get("draft")
    is_draft = str(draft or "").strip() in {"1", "true", "True"}
    if not execution_id and not is_draft:
        abort(400)
    if is_draft and not step_id:
        abort(400)

    return_to = _safe_flow_return_to(request.args.get("return_to"), process_id)

    # HTMX fragment support (boosted navigation swaps #page-content).
    if request.headers.get("HX-Request") == "true":
        return render_template(
            "processes/batch-start-hx.html",
            active_page="core",
            process_id=str(process_id),
            execution_id=str(execution_id) if execution_id else None,
            step_id=str(step_id) if step_id else None,
            draft=is_draft,
            return_to=return_to,
        )

    return render_template(
        "processes/batch-start.html",
        active_page="core",
        process_id=str(process_id),
        execution_id=str(execution_id) if execution_id else None,
        step_id=str(step_id) if step_id else None,
        draft=is_draft,
        return_to=return_to,
    )


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
    return render_template("notifications/notifications.html", active_page="core")


@core_bp.route("/core/processes", methods=["GET"])
@requires_auth
def processes_list_page():
    """SPA list of all processes; links open flows2 for each process."""
    return render_template("processes/list.html", active_page="core")


@core_bp.route("/core/sourcemap", methods=["GET"])
@requires_auth
def sourcemap():
    """Serve the sourcemap.html frontend page"""
    return render_template("sourcemap/sourcemap.html", active_page="core")


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
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=60"
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
        response.headers["Content-Type"] = "text/css; charset=utf-8"
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=60"
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
_IMG_STATIC_ALLOWLIST = frozenset({"hero-wave.jpg"})


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


@core_bp.route("/static/img/<filename>")
@limiter.exempt
def serve_core_img(filename):
    """Serve images from core frontend img/ (no auth; used by unauthenticated landing page)."""
    from flask import abort
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
    except FileNotFoundError:
        import logging

        logging.getLogger(__name__).info("Image static file not found: %s", filename)
        abort(404, "File not found")
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Error serving image static: %s", filename)
        abort(500, "Internal server error")


@core_bp.route("/api/core/processes", methods=["GET"])
@requires_auth
def list_processes():
    """List all processes for the current organisation"""
    org_id = UUID(g.org_id)
    include_steps = request.args.get("include_steps", "false").lower() == "true"
    repo = ProcessRepository(db_session)
    processes = repo.list_processes(org_id)

    # Batch-fetch all executions for the org once, then group by process_id in Python.
    # Avoids N queries (one per process) when calculating active/completed counts.
    execution_repo = ExecutionRepository(db_session)
    all_executions = execution_repo.list_executions(org_id)
    from collections import defaultdict

    execs_by_process: dict = defaultdict(list)
    for e in all_executions:
        execs_by_process[e.process_id].append(e)

    # Batch-load process event summaries
    from app.core.db.models.entity_event_summary import EntityEventSummary

    proc_ids_all = [p.id for p in processes]
    proc_summary_by_id: dict = {}
    if proc_ids_all:
        proc_ees = db_session.query(EntityEventSummary).filter(EntityEventSummary.entity_id.in_(proc_ids_all)).all()
        proc_summary_by_id = {str(r.entity_id): r.summary for r in proc_ees}

    result = []
    for process in processes:
        proc_execs = execs_by_process.get(process.id, [])
        active_count = sum(1 for e in proc_execs if e.status == ExecutionStatus.IN_PROGRESS)
        completed_count = sum(1 for e in proc_execs if e.status == ExecutionStatus.COMPLETED)
        step_list = process.steps or []
        step_count = len(step_list)

        entry = {
            "id": str(process.id),
            "name": process.name,
            "description": process.description,
            "category": process.category.value if process.category else None,
            "is_draft": process.is_draft,
            "step_count": step_count,
            "active_executions": active_count,
            "completed_executions": completed_count,
            "created_at": process.created_at.isoformat() if process.created_at else None,
            "event_summary": proc_summary_by_id.get(str(process.id)),
        }

        if include_steps:
            entry["steps"] = [
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
                for step in step_list
            ]

        result.append(entry)

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

    Preferred payload:
      { "orders": [ { "id": "<uuid>", "position": 1000 }, ... ] }

    Alias:
      - { "steps": [ { "id": "<uuid>", "position": ... }, ... ] }
    """
    org_id = UUID(g.org_id)
    try:
        process_uuid = UUID(process_id)
    except ValueError:
        return jsonify({"error": "Invalid process ID"}), 400

    data = request.get_json() or {}

    # Explicit orders with positions (preferred).
    orders = data.get("orders") or data.get("steps")

    from decimal import Decimal

    try:
        if not isinstance(orders, list) or not orders:
            return jsonify({"error": "orders is required"}), 400

        updates: list[tuple[UUID, Decimal]] = []
        for row in orders:
            if not isinstance(row, dict):
                return jsonify({"error": "Invalid orders payload"}), 400
            sid = row.get("id") or row.get("step_id")
            pos = row.get("position")
            if not sid or pos is None:
                return jsonify({"error": "Each order must include id and position"}), 400
            try:
                step_uuid = UUID(str(sid))
                position = Decimal(str(pos))
            except Exception:
                return jsonify({"error": "Invalid id or position"}), 400
            updates.append((step_uuid, position))

        # Use an isolated session for this write endpoint.
        # The app's before_request tenant middleware uses the scoped_session for reads and can leave
        # an open transaction on it; using a fresh SessionLocal avoids nested-transaction surprises
        # and ensures the commit persists.
        sess = SessionLocal()
        with sess.begin():
            # Ensure process belongs to org (IDOR guard).
            repo = ProcessRepository(sess)
            if not repo.get_process_by_id(process_uuid, org_id=org_id):
                return jsonify({"error": "Process not found"}), 404

            # Lock all steps for this process to prevent concurrent reorder collisions.
            locked = sess.query(Step.id).filter(Step.process_id == process_uuid).with_for_update().all()
            locked_ids = {sid for (sid,) in locked}
            if not locked_ids:
                return jsonify({"error": "No steps to reorder"}), 400

            for step_uuid, position in updates:
                if step_uuid not in locked_ids:
                    return jsonify({"error": "Step not found"}), 404
                updated = (
                    sess.query(Step)  # nosemgrep: sqlalchemy-query-in-for-loop — each step gets a distinct position
                    .filter(Step.id == step_uuid, Step.process_id == process_uuid)
                    .update({"position": position})
                )
                if updated != 1:
                    return jsonify({"error": "Step not found"}), 404

        sess.close()
        return jsonify({"message": "Reordered"}), 200
    except Exception as e:
        try:
            sess.rollback()  # type: ignore[name-defined]
            sess.close()  # type: ignore[name-defined]
        except Exception:
            db_session.rollback()
        try:
            from flask import current_app

            current_app.logger.exception("Failed to reorder steps process_id=%s", process_id)
        except Exception:
            pass
        return jsonify({"error": "Failed to reorder steps", "details": str(e)}), 500


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

    # Batch-fetch all evidence for all executions in a single query
    executions_by_id = {str(e.id): e for e in executions}
    evidence_by_execution = list_evidence_for_executions_batch([e.id for e in executions], org_id, executions_by_id)

    # Batch-load execution event summaries
    from app.core.db.models.entity_event_summary import EntityEventSummary

    exec_ids_all = [e.id for e in executions]
    exec_summary_by_id: dict = {}
    if exec_ids_all:
        exec_ees = db_session.query(EntityEventSummary).filter(EntityEventSummary.entity_id.in_(exec_ids_all)).all()
        exec_summary_by_id = {str(r.entity_id): r.summary for r in exec_ees}

    result = []
    for execution in executions:
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

        total_steps = execution.total_steps or len(execution_steps) if execution_steps else 0
        progress = (len(completed_steps) / total_steps * 100) if total_steps > 0 else 0

        # Extract completed_by from the last completed step (highest step_number = who finished the execution)
        completed_by = None
        for _es in reversed(execution_steps_sorted):
            if _es.execution_data and _es.execution_data.get("completed_by"):
                completed_by = _es.execution_data["completed_by"]
                break

        steps_payload = [
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
            for es in execution_steps_sorted
        ]

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
                "execution_steps": steps_payload,
                "evidence": evidence_by_execution.get(str(execution.id), []),
                "completed_by": completed_by,
                "created_at": execution.created_at.isoformat() if execution.created_at else None,
                "event_summary": exec_summary_by_id.get(str(execution.id)),
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

    evidence_list = list_evidence_for_execution(execution_uuid, org_id, execution=execution)

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


@core_bp.route("/api/core/executions/<execution_id>/with-process", methods=["GET"])
@requires_auth
def get_execution_with_process(execution_id: str):
    """Single round-trip: execution (with steps + evidence) and full process definition."""
    org_id = UUID(g.org_id)
    try:
        execution_uuid = UUID(execution_id)
    except ValueError:
        return jsonify({"error": "Invalid execution ID"}), 400

    exec_repo = ExecutionRepository(db_session)
    execution = exec_repo.get_execution_with_steps(execution_uuid, org_id)
    if not execution:
        return jsonify({"error": "Execution not found"}), 404

    process_repo = ProcessRepository(db_session)
    process = process_repo.get_process_with_steps(execution.process_id, org_id)
    if not process:
        return jsonify({"error": "Process not found"}), 404

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

    minimal = str(request.args.get("minimal") or "").strip().lower() in {"1", "true", "yes"}
    evidence_list = [] if minimal else list_evidence_for_execution(execution_uuid, org_id)

    execution_payload = {
        "id": str(execution.id),
        "process_id": str(execution.process_id),
        "status": execution.status.value,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "execution_steps": execution_steps,
        "evidence": evidence_list,
    }

    steps = []
    for step in process.steps:
        steps.append(
            {
                "id": str(step.id),
                "step_number": step.step_number,
                "position": str(step.position) if getattr(step, "position", None) is not None else None,
                "name": step.name,
                "inputs": step.inputs or [],
                "outputs": step.outputs or [],
                "execution_prompts": step.execution_prompts or [],
                "description": None if minimal else step.description,
            }
        )

    process_payload = {
        "id": str(process.id),
        "name": process.name,
        "description": None if minimal else process.description,
        "category": None if minimal else (process.category.value if process.category else None),
        "is_draft": None if minimal else process.is_draft,
        "created_at": None if minimal else (process.created_at.isoformat() if process.created_at else None),
        "steps": steps,
    }

    return jsonify(
        {
            "meta": {
                "bundle": "execution_with_process",
                "minimal": minimal,
            },
            "execution": execution_payload,
            "process": process_payload,
        }
    ), 200


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

    content_length = request.content_length
    if content_length is not None and content_length > MAX_COMPLETE_STEP_CONTENT_LENGTH:
        return jsonify({"error": "Request body too large"}), 413

    raw_bytes = request.get_data(cache=True, as_text=False) or b""
    if len(raw_bytes) > MAX_COMPLETE_STEP_CONTENT_LENGTH:
        return jsonify({"error": "Request body too large"}), 413
    if not raw_bytes.strip():
        raw_body = {}
    else:
        try:
            raw_body = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return jsonify({"error": "Invalid JSON"}), 400
        if not isinstance(raw_body, dict):
            return jsonify({"error": "Invalid request body", "details": ["JSON root must be an object"]}), 400

    try:
        parsed_body = CompleteStepRequestBody.model_validate(raw_body)
    except ValidationError as e:
        return jsonify({"error": "Invalid request body", "details": e.errors()}), 400

    try:
        validate_json_blob(parsed_body.actual_inputs, path="$.actual_inputs")
        validate_json_blob(parsed_body.actual_outputs, path="$.actual_outputs")
        validate_json_blob(parsed_body.execution_data, path="$.execution_data")
    except ValueError as e:
        return jsonify({"error": "Invalid request body", "details": [str(e)]}), 400

    actual_inputs = parsed_body.actual_inputs
    actual_outputs = parsed_body.actual_outputs
    try:
        execution_data = _strip_incoming_execution_trace_keys(parsed_body.execution_data)
    except RuntimeError:
        logger.exception("execution_data trace-strip invariant violated (should follow validate_json_blob)")
        inc_counter("execution_data_strip_invariant_violations")
        return jsonify(
            {
                "error": "Invalid request body",
                "details": ["Payload failed sanitisation invariants"],
            }
        ), 400
    allow_consumption_override = parsed_body.allow_consumption_override

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
        # Single transaction: mark step complete + inventory + outputs commit together.
        # If validation fails after marking COMPLETED in-session, rollback so the step stays READY
        # and the client can retry (avoids "not in a state that can be completed" on the next attempt).
        execution_step = repo.complete_step(
            execution_step_id=execution_step_uuid,
            org_id=org_id,
            actual_inputs=actual_inputs,
            actual_outputs=actual_outputs,
            execution_data=execution_data,
            commit=False,
        )

        if not execution_step:
            return jsonify({"error": "Execution step not found"}), 404

        db_session.flush()
        # Capture step outputs for audit (same transaction as completion)
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
            db_session.rollback()
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
            db_session.rollback()
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
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # Log the full error for debugging; return message and details for diagnosis
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error completing execution step")
        err_detail = str(e) if e else "Unknown error"
        db_session.rollback()
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

    from sqlalchemy.orm import joinedload

    from app.core.backend.checks.output_ready_date_check import get_operator_ready_instant_for_item
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem

    # One query for all producing steps (avoids N+1 hydration + ready-date lookups).
    # JOIN Execution + filter org_id: bounded by step_ids (inventory row count), no materialized list of all org executions.
    # Step.outputs is JSONB on `steps` (see Step model); joinedload(ExecutionStep.step) loads one row per step — no relationship N+1 for outputs.
    step_ids = {i.source_execution_step_id for i in items if i.source_execution_step_id}
    execution_step_by_id: dict = {}
    if step_ids:
        loaded_steps = (
            db_session.query(ExecutionStep)
            .join(Execution, ExecutionStep.execution_id == Execution.id)
            .filter(Execution.org_id == org_id)
            .filter(ExecutionStep.id.in_(step_ids))
            .options(joinedload(ExecutionStep.step))
            .all()
        )
        execution_step_by_id = {es.id: es for es in loaded_steps}

    # Batch-load executions and their processes for process-name and untracked-step lookups.
    # Replaces per-item db_session.query(Execution/Process) calls inside the loop below.
    source_exec_ids = {i.source_execution_id for i in items if i.source_execution_id}
    execution_by_id: dict = {}
    process_by_id: dict = {}
    if source_exec_ids:
        loaded_execs = (
            db_session.query(Execution)
            .filter(Execution.org_id == org_id)
            .filter(Execution.id.in_(source_exec_ids))
            .all()
        )
        execution_by_id = {e.id: e for e in loaded_execs}
        proc_ids = {e.process_id for e in loaded_execs if e.process_id}
        if proc_ids:
            from sqlalchemy.orm import selectinload

            from app.core.db.models.process import Process as ProcessModel

            loaded_procs = (
                db_session.query(ProcessModel)
                .filter(ProcessModel.org_id == org_id)
                .filter(ProcessModel.id.in_(proc_ids))
                .options(selectinload(ProcessModel.steps))
                .all()
            )
            process_by_id = {p.id: p for p in loaded_procs}

    # Batch-load event summaries for card enrichment (single query, no N+1)
    from app.core.db.models.entity_event_summary import EntityEventSummary

    item_ids_all = [item.id for item in items]
    event_summary_by_id: dict = {}
    if item_ids_all:
        ees_rows = db_session.query(EntityEventSummary).filter(EntityEventSummary.entity_id.in_(item_ids_all)).all()
        event_summary_by_id = {str(r.entity_id): r.summary for r in ees_rows}

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

        # Hydrate extra_data from the producing ExecutionStep when needed (shallow copy so we don't mutate ORM JSON in place).
        # Prompts, trace, inputs, and output are filled independently — previously inputs were only loaded when
        # execution_prompts was missing, which hid variable_inputs on many intermediate/final items.
        extra_data = {**(item.extra_data or {})}
        src_step = execution_step_by_id.get(item.source_execution_step_id) if item.source_execution_step_id else None
        if src_step:
            try:
                if src_step.execution_data:
                    execution_prompts, execution_trace = _split_execution_data(
                        src_step.execution_data, completed_at=src_step.completed_at
                    )
                    if not extra_data.get("execution_prompts"):
                        extra_data["execution_prompts"] = execution_prompts or {}
                    if not extra_data.get("execution_trace"):
                        extra_data["execution_trace"] = execution_trace or {}

                if not extra_data.get("variable_inputs"):
                    if src_step.actual_inputs:
                        extra_data["variable_inputs"] = src_step.actual_inputs
                    else:
                        extra_data["variable_inputs"] = []

                if not extra_data.get("variable_output") and src_step.actual_outputs:
                    output_name = item.name
                    matching_output = next((o for o in src_step.actual_outputs if o.get("name") == output_name), None)
                    if matching_output:
                        extra_data["variable_output"] = matching_output
            except Exception:
                inc_counter("inventory_hydration_failures")

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
                        db_session.query(
                            InventoryItem
                        )  # nosemgrep: sqlalchemy-query-in-for-loop — recursive DAG traversal, each node fetched on demand
                        .filter(InventoryItem.id == UUID(inventory_item_id), InventoryItem.org_id == org_id)
                        .first()
                    )

                    if not input_inventory_item or not input_inventory_item.source_execution_step_id:
                        return steps_data

                    # Look up the execution step that produced this input
                    input_execution_step = (
                        db_session.query(
                            ExecutionStep
                        )  # nosemgrep: sqlalchemy-query-in-for-loop — recursive DAG traversal, each node fetched on demand
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

        # Get process name from execution if available (uses pre-loaded batch dicts)
        process_name = None
        if item.source_execution_id:
            try:
                execution = execution_by_id.get(item.source_execution_id)
                if execution and execution.process_id:
                    process = process_by_id.get(execution.process_id)
                    if process:
                        process_name = process.name
            except Exception:
                pass
        if not process_name:
            try:
                tagged = (extra_data or {}).get("producing_process_name")
                if tagged:
                    process_name = str(tagged)
            except Exception:
                pass

        # For untracked items, resolve producing step (step that defines this output) for "Execute next step" button
        producing_step_id = None
        producing_step_name = None
        if extra_data.get("untracked") and item.source_execution_id:
            try:
                execution = execution_by_id.get(item.source_execution_id)
                if execution and execution.process_id:
                    process_with_steps = process_by_id.get(execution.process_id)
                    if process_with_steps:
                        producing_step_id, producing_step_name = _find_producing_step(
                            process_with_steps, item.name, item.unit
                        )
                    # Fallback: if no output match (e.g. name/unit mismatch), use the step where item was added
                    if not producing_step_id and item.source_execution_step_id:
                        es_untracked = execution_step_by_id.get(item.source_execution_step_id)
                        if es_untracked:
                            producing_step_id = es_untracked.step_id
                            if es_untracked.step:
                                producing_step_name = es_untracked.step.name
            except Exception:
                inc_counter("inventory_producing_step_failures")
                logger.debug(
                    "list_inventory producing_step resolution failed item_id=%s",
                    item.id,
                    exc_info=True,
                )
        if not producing_step_name:
            try:
                tagged_step = (extra_data or {}).get("producing_step_name")
                if tagged_step:
                    producing_step_name = str(tagged_step)
            except Exception:
                inc_counter("inventory_producing_step_name_fallback_failures")
                logger.debug("list_inventory producing_step_name fallback failed item_id=%s", item.id, exc_info=True)

        # Single operator-facing ready instant (set_at_execution date or fixed-duration from step completion)
        ready_date_display = None
        try:
            rdt = get_operator_ready_instant_for_item(db_session, item, execution_step=src_step)
            if rdt:
                ready_date_display = rdt.isoformat()
        except Exception:
            inc_counter("ready_date_compute_failures")
            logger.debug("list_inventory ready_date_display failed item_id=%s", item.id, exc_info=True)

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
                "extra_data": _bound_inventory_extra_data_for_list_response(extra_data),
                "system_findings": findings_by_id.get(str(item.id), []),
                "ready_date_display": ready_date_display,
                "event_summary": event_summary_by_id.get(str(item.id)),
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

        for entry_idx, item_id, waste_decimal, req_unit, reason in lines:
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
                # Human-friendly operator fields for audit (self-contained, append-only).
                operator_email = getattr(getattr(g, "current_user", None), "email", None)
                operator_first = getattr(getattr(g, "current_user", None), "first_name", None)
                operator_last = getattr(getattr(g, "current_user", None), "last_name", None)
                operator_name = " ".join([x for x in [operator_first, operator_last] if x]) or operator_email
                audit_entry = {
                    "user_id": str(g.user_id) if getattr(g, "user_id", None) else None,
                    "operator_email": operator_email,
                    "operator_name": operator_name,
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
        # Human-friendly operator fields for audit (self-contained, append-only).
        operator_email = getattr(getattr(g, "current_user", None), "email", None)
        operator_first = getattr(getattr(g, "current_user", None), "first_name", None)
        operator_last = getattr(getattr(g, "current_user", None), "last_name", None)
        operator_name = " ".join([x for x in [operator_first, operator_last] if x]) or operator_email
        audit_entry = {
            "user_id": str(g.user_id) if getattr(g, "user_id", None) else None,
            "operator_email": operator_email,
            "operator_name": operator_name,
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

        # Snapshot before mutation for diff
        before = {
            "name": item.name,
            "inventory_type": item.inventory_type,
            "quantity": quantity_to_api_str(item.quantity),
            "unit": item.unit,
            "supplier": item.supplier,
            "supplier_batch_number": item.supplier_batch_number,
            "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
            "barcode": item.barcode,
        }

        # Apply updates
        item.name = name
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.MANUAL_API_UPDATE):
            item.quantity = coerce_stored_quantity(quantity)
        item.unit = unit
        item.inventory_type = inventory_type
        item.supplier = data.get("supplier")
        item.purchase_date = purchase_date
        item.supplier_batch_number = data.get("supplier_batch_number")
        item.expiry_date = expiry_date
        item.barcode = data.get("barcode") or None
        if data.get("metadata"):
            item.extra_data = data.get("metadata")

        after = {
            "name": item.name,
            "inventory_type": item.inventory_type,
            "quantity": quantity_to_api_str(item.quantity),
            "unit": item.unit,
            "supplier": item.supplier,
            "supplier_batch_number": item.supplier_batch_number,
            "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
            "barcode": item.barcode,
        }

        diff = {k: {"before": before[k], "after": after[k]} for k in before if before[k] != after[k]}

        ew = EventWriter(db_session, org_id)
        ew.emit(
            event_type="inventory_item.updated",
            entity_type="inventory_item",
            entity_id=item.id,
            payload={**after, "reason": "manual_edit"},
            diff=diff if diff else None,
        )

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


@core_bp.route("/api/core/inventory/<item_id>/adjust", methods=["POST"])
@requires_auth
def adjust_inventory_item_quantity(item_id):
    """Manually correct an inventory item's quantity (absolute value).

    Emits inventory_item.quantity_adjusted so the change is fully traceable.
    """
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    raw = data.get("new_quantity")
    if raw is None or str(raw).strip() == "":
        return jsonify({"error": "new_quantity is required"}), 400
    try:
        float(str(raw).strip())
    except (TypeError, ValueError):
        return jsonify({"error": "new_quantity must be a valid number"}), 400

    repo = InventoryRepository(db_session)
    try:
        item = repo.set_inventory_item_quantity(UUID(item_id), org_id, str(raw).strip())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not item:
        return jsonify({"error": "Inventory item not found"}), 404
    return jsonify(
        {
            "id": str(item.id),
            "quantity": quantity_to_api_str(item.quantity),
            "unit": item.unit,
        }
    ), 200


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
    """Trace forward from a raw material to find all connected intermediates and final products.

    Returns all items in the production chain regardless of current quantity — zero-quantity
    intermediates must be visible for a complete audit trail.
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
        include_quantity_filter=False,
        root_item_id=raw_material_uuid,
    )
    connected_items = result["items"]
    connections = result["connections"]

    # Attach step_data to each item for historical quantities and step timestamps.
    _hydrate_step_data(connected_items, db_session, org_id)

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
        "step_data": None,
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
    """Trace backward from any inventory item (raw, intermediate, or final) to find all source items.

    Returns all items in the production chain regardless of current quantity — zero-quantity
    intermediates must be visible for a complete audit trail.
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
        include_quantity_filter=False,
        traced_item_id=item_uuid,
    )
    all_result_items = result["items"]
    connections = result["connections"]

    # Build traced_item_data first; add it to all_result_items so step enrichment and connection
    # filtering both include it. trace_backward only returns SOURCE items, not the traced item itself.
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
            "step_data": None,
        }
        all_result_items.append(traced_item_data)

    # Attach step_data (including traced item itself, which is now in all_result_items).
    _hydrate_step_data(all_result_items, db_session, org_id)

    # Add direct connections from every source item to traced item (for sourcemap execution grouping)
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

    source_items_without_traced = [item for item in all_result_items if item["id"] != str(traced_item.id)]
    raw_materials = [
        item for item in source_items_without_traced if item["inventory_type"] == InventoryType.RAW_MATERIAL.value
    ]
    intermediates = [
        item for item in source_items_without_traced if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value
    ]

    # Only return connections where both endpoints are items in the response (prevents TO <uuid> display).
    # all_result_items now includes traced_item so connections to it are preserved.
    all_item_ids = {item["id"] for item in all_result_items}
    connections = [c for c in connections if c.get("from_id") in all_item_ids and c.get("to_id") in all_item_ids]

    return jsonify(
        {
            "traced_item": traced_item_data,
            "raw_materials": raw_materials,
            "intermediates": intermediates,
            "all_items": all_result_items,
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

    # Batch-fetch all inventory items for all execution step IDs in one query.
    all_step_ids = {UUID(sid) for data in metadata_map.values() for sid in data["execution_step_ids"]}
    items_by_step: dict = {}
    if all_step_ids:
        step_items = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.org_id == org_id)
            .filter(InventoryItem.source_execution_step_id.in_(all_step_ids))
            .all()
        )
        for inv_item in step_items:
            items_by_step.setdefault(inv_item.source_execution_step_id, []).append(str(inv_item.id))

    # Convert to list format
    for pair_key, data in metadata_map.items():
        inventory_item_ids = []
        for step_id in data["execution_step_ids"]:
            inventory_item_ids.extend(items_by_step.get(UUID(step_id), []))

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


def _dashboard_parse_due_date(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _dashboard_priority_rank(priority: Any) -> int:
    p = str(priority or "").strip().lower()
    if p == "high":
        return 0
    if p == "medium":
        return 1
    if p == "low":
        return 2
    return 3


def _dashboard_summarize_tasks(
    open_tasks: list[dict[str, Any]],
    today: date,
    week_start: date | None = None,
    week_end_exclusive: date | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for task in open_tasks or []:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"pending", "in_progress"}:
            continue
        due = _dashboard_parse_due_date(task.get("due_date"))
        rows.append(
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "due_date": due.isoformat() if due else None,
                "priority": task.get("priority"),
                "status": status,
                "contact_name": task.get("contact_name"),
                "_due_obj": due,
            }
        )

    due_today_count = sum(1 for t in rows if t["_due_obj"] == today)
    overdue_count = sum(1 for t in rows if t["_due_obj"] is not None and t["_due_obj"] < today)
    due_this_week_count = 0
    if week_start is not None and week_end_exclusive is not None:
        due_this_week_count = sum(
            1
            for t in rows
            if t["_due_obj"] is not None and week_start <= t["_due_obj"] and t["_due_obj"] < week_end_exclusive
        )

    sorted_rows = sorted(
        rows,
        key=lambda t: (
            t["_due_obj"] is None,
            t["_due_obj"] or date.max,
            _dashboard_priority_rank(t.get("priority")),
            str(t.get("title") or "").lower(),
        ),
    )
    top_tasks = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "due_date": t.get("due_date"),
            "priority": t.get("priority"),
            "status": t.get("status"),
            "contact_name": t.get("contact_name"),
        }
        for t in sorted_rows[:5]
    ]

    return {
        "enabled": True,
        "open_count": len(rows),
        "due_today_count": due_today_count,
        "overdue_count": overdue_count,
        "due_this_week_count": due_this_week_count,
        "top_tasks": top_tasks,
    }


def _dashboard_count_red_amber(items: list[dict[str, Any]] | None) -> tuple[int, int]:
    red = 0
    amber = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").strip().lower()
        if severity == "red":
            red += 1
        elif severity == "amber":
            amber += 1
    return red, amber


def _dashboard_build_compliance_summary(results: list[Any], system_status: dict[str, Any]) -> dict[str, Any]:
    by_id = {r.check_id: r for r in results}

    expired_data = (by_id.get("expired_materials").data or {}) if by_id.get("expired_materials") else {}
    untracked_data = (by_id.get("untracked_items").data or {}) if by_id.get("untracked_items") else {}
    output_expiry_data = (by_id.get("output_expiry").data or {}) if by_id.get("output_expiry") else {}
    output_ready_data = (by_id.get("output_ready_date").data or {}) if by_id.get("output_ready_date") else {}

    expired_raw = len(expired_data.get("expired_raw_materials") or [])
    expired_impacted = len(expired_data.get("impacted_items") or [])
    untracked_count = len(untracked_data.get("untracked_items") or [])
    output_expiry_red, output_expiry_amber = _dashboard_count_red_amber(output_expiry_data.get("output_expiry_items"))
    output_ready_red, output_ready_amber = _dashboard_count_red_amber(output_ready_data.get("output_ready_date_items"))

    expired_penalty = min(40, (25 if expired_raw > 0 else 0) + (2 * expired_impacted))
    untracked_penalty = min(25, 3 * untracked_count)
    output_expiry_penalty = min(20, (4 * output_expiry_red) + output_expiry_amber)
    output_ready_penalty = min(15, (2 * output_ready_red) + output_ready_amber)
    total_penalty = expired_penalty + untracked_penalty + output_expiry_penalty + output_ready_penalty
    score = max(0, min(100, 100 - total_penalty))

    drivers = [
        {"key": "expired_materials", "label": "Expired materials", "penalty": expired_penalty},
        {"key": "untracked_items", "label": "Untracked inventory", "penalty": untracked_penalty},
        {"key": "output_expiry", "label": "Output expiry", "penalty": output_expiry_penalty},
        {"key": "output_ready_date", "label": "Output ready-date", "penalty": output_ready_penalty},
    ]
    drivers = [d for d in drivers if d["penalty"] > 0]
    drivers.sort(key=lambda d: d["penalty"], reverse=True)

    active_use_risk_count = 0
    if isinstance(system_status, dict) and system_status.get("mode") == "health":
        signals = system_status.get("signals") or []
        active_use_risk_count = sum(
            1 for s in signals if isinstance(s, dict) and s.get("has_issue") and s.get("in_active_use")
        )

    return {
        "score": score,
        "score_version": "v1",
        "trend_delta_7d": None,
        "state": (system_status or {}).get("state", "unknown"),
        "top_drivers": drivers[:3],
        "findings": {
            "expired_materials": {"count": expired_raw, "impacted_count": expired_impacted},
            "untracked_items": {"count": untracked_count},
            "output_expiry": {"red_count": output_expiry_red, "amber_count": output_expiry_amber},
            "output_ready_date": {"red_count": output_ready_red, "amber_count": output_ready_amber},
            "active_use_risk_count": active_use_risk_count,
        },
    }


def _dashboard_event_log_period(
    org_id: UUID, session, period_start: datetime, period_end: datetime, limit: int = 10
) -> dict[str, Any]:
    q = (
        session.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id)
        .filter(EntityEvent.created_at >= period_start, EntityEvent.created_at < period_end)
    )
    total = q.count()
    events = q.order_by(EntityEvent.created_at.desc()).limit(limit).all()
    items = [
        {
            "id": str(ev.id),
            "event_type": ev.event_type,
            "summary": _human_summary(ev),
            "at": ev.created_at.isoformat() if ev.created_at else None,
            "actor": ev.actor_label or "System",
            "entity_type": ev.entity_type,
            "entity_id": str(ev.entity_id) if ev.entity_id else None,
        }
        for ev in events
    ]
    return {"total": total, "items": items}


def _dashboard_operations_summary(
    org_id: UUID, session, day_start: datetime, next_day_start: datetime
) -> dict[str, int]:
    active_executions = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS]))
        .count()
    )
    completed_today = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status == ExecutionStatus.COMPLETED)
        .filter(Execution.completed_at.isnot(None))
        .filter(Execution.completed_at >= day_start, Execution.completed_at < next_day_start)
        .count()
    )
    failed_or_cancelled_today = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]))
        .filter(Execution.updated_at >= day_start, Execution.updated_at < next_day_start)
        .count()
    )
    return {
        "active_executions": active_executions,
        "completed_today": completed_today,
        "failed_or_cancelled_today": failed_or_cancelled_today,
    }


def _dashboard_week_boundaries(today: date) -> tuple[datetime, datetime, datetime]:
    week_start_date = today - timedelta(days=today.weekday())
    week_start = datetime.combine(week_start_date, datetime.min.time())
    next_week_start = week_start + timedelta(days=7)
    prev_week_start = week_start - timedelta(days=7)
    return week_start, next_week_start, prev_week_start


def _dashboard_parse_date_like(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _dashboard_short_date_label(day: date) -> str:
    return f"{day.strftime('%b')} {day.day}"


def _dashboard_series_from_date_counts(
    day_counts: dict[date, int],
    *,
    start_day: date | None = None,
    end_day: date | None = None,
    cumulative: bool = True,
) -> dict[str, Any]:
    if start_day is None and day_counts:
        start_day = min(day_counts)
    if end_day is None and day_counts:
        end_day = max(day_counts)
    if start_day is None:
        start_day = date.today()
    if end_day is None:
        end_day = start_day
    if end_day < start_day:
        end_day = start_day

    points: list[dict[str, Any]] = []
    cursor = start_day
    running = 0
    while cursor <= end_day:
        value = int(day_counts.get(cursor) or 0)
        if cumulative:
            running += value
            y = running
        else:
            y = value
        points.append({"date": cursor.isoformat(), "value": y})
        cursor = cursor + timedelta(days=1)

    return {
        "start": start_day.isoformat(),
        "end": end_day.isoformat(),
        "start_label": _dashboard_short_date_label(start_day),
        "end_label": _dashboard_short_date_label(end_day),
        "points": points,
    }


def _dashboard_event_counts_by_day(
    org_id: UUID, session, start_dt: datetime, end_dt: datetime, actor_type: str | None = None
) -> dict[date, int]:
    q = (
        session.query(func.date(EntityEvent.created_at).label("event_day"), func.count(EntityEvent.id).label("total"))
        .filter(EntityEvent.org_id == org_id)
        .filter(EntityEvent.created_at >= start_dt, EntityEvent.created_at < end_dt)
    )
    if actor_type:
        q = q.filter(EntityEvent.actor_type == actor_type)
    rows = q.group_by(func.date(EntityEvent.created_at)).all()
    out: dict[date, int] = {}
    for row in rows:
        day = _dashboard_parse_date_like(getattr(row, "event_day", None))
        if day is None:
            continue
        out[day] = int(getattr(row, "total", 0) or 0)
    return out


def _dashboard_execution_counts_by_day(
    org_id: UUID, session, start_dt: datetime, end_dt: datetime, column: str
) -> dict[date, int]:
    if column == "completed":
        day_col = Execution.completed_at
        q = (
            session.query(func.date(day_col).label("event_day"), func.count(Execution.id).label("total"))
            .filter(Execution.org_id == org_id)
            .filter(Execution.status == ExecutionStatus.COMPLETED)
            .filter(day_col.isnot(None))
            .filter(day_col >= start_dt, day_col < end_dt)
        )
    else:
        day_col = Execution.started_at
        q = (
            session.query(func.date(day_col).label("event_day"), func.count(Execution.id).label("total"))
            .filter(Execution.org_id == org_id)
            .filter(day_col.isnot(None))
            .filter(day_col >= start_dt, day_col < end_dt)
        )
    rows = q.group_by(func.date(day_col)).all()
    out: dict[date, int] = {}
    for row in rows:
        day = _dashboard_parse_date_like(getattr(row, "event_day", None))
        if day is None:
            continue
        out[day] = int(getattr(row, "total", 0) or 0)
    return out


def _dashboard_open_action_item_dates(
    check_results: list[Any], open_tasks: list[dict[str, Any]], today: date
) -> list[date]:
    by_id = {r.check_id: r for r in check_results or []}
    dates: list[date] = []

    expired_data = (by_id.get("expired_materials").data or {}) if by_id.get("expired_materials") else {}
    for item in expired_data.get("expired_raw_materials") or []:
        if not isinstance(item, dict):
            continue
        d = _dashboard_parse_date_like(item.get("expiry_date")) or _dashboard_parse_date_like(item.get("created_at"))
        if d:
            dates.append(d)

    untracked_data = (by_id.get("untracked_items").data or {}) if by_id.get("untracked_items") else {}
    for item in untracked_data.get("untracked_items") or []:
        if not isinstance(item, dict):
            continue
        d = _dashboard_parse_date_like(item.get("created_at"))
        if d:
            dates.append(d)

    output_expiry_data = (by_id.get("output_expiry").data or {}) if by_id.get("output_expiry") else {}
    for item in output_expiry_data.get("output_expiry_items") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("severity") or "").strip().lower() != "red":
            continue
        d = _dashboard_parse_date_like(item.get("detected_at")) or _dashboard_parse_date_like(item.get("expiry_at"))
        if d:
            dates.append(d)

    for task in open_tasks or []:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"pending", "in_progress"}:
            continue
        due = _dashboard_parse_date_like(task.get("due_date"))
        if due is not None and due < today:
            dates.append(due)

    return dates


def _dashboard_operations_weekly_summary(org_id: UUID, session, now_dt: datetime, today: date) -> dict[str, Any]:
    week_start, next_week_start, prev_week_start = _dashboard_week_boundaries(today)

    active_executions = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS]))
        .count()
    )
    started_this_week = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.started_at >= week_start, Execution.started_at < next_week_start)
        .count()
    )
    completed_this_week = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status == ExecutionStatus.COMPLETED)
        .filter(Execution.completed_at.isnot(None))
        .filter(Execution.completed_at >= week_start, Execution.completed_at < next_week_start)
        .count()
    )
    completed_last_week = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status == ExecutionStatus.COMPLETED)
        .filter(Execution.completed_at.isnot(None))
        .filter(Execution.completed_at >= prev_week_start, Execution.completed_at < week_start)
        .count()
    )
    failed_or_cancelled_this_week = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]))
        .filter(Execution.updated_at >= week_start, Execution.updated_at < next_week_start)
        .count()
    )
    stalled_active_over_48h = (
        session.query(Execution)
        .filter(Execution.org_id == org_id)
        .filter(Execution.status.in_([ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS]))
        .filter(Execution.started_at < (now_dt - timedelta(hours=48)))
        .count()
    )
    completed_vs_last_week_pct = None
    if completed_last_week > 0:
        completed_vs_last_week_pct = round(((completed_this_week - completed_last_week) / completed_last_week) * 100, 1)

    return {
        "window": "week_to_date",
        "active_executions": active_executions,
        "started_this_week": started_this_week,
        "completed_this_week": completed_this_week,
        "failed_or_cancelled_this_week": failed_or_cancelled_this_week,
        "stalled_active_over_48h": stalled_active_over_48h,
        "completed_last_week": completed_last_week,
        "completed_vs_last_week_pct": completed_vs_last_week_pct,
    }


def _dashboard_build_action_board(tasks_summary: dict[str, Any], compliance: dict[str, Any]) -> dict[str, Any]:
    findings = (compliance or {}).get("findings") or {}
    output_expiry = findings.get("output_expiry") or {}
    output_ready = findings.get("output_ready_date") or {}

    candidates = [
        {
            "key": "expired_raw",
            "label": "Expired raw materials with stock",
            "count": (findings.get("expired_materials") or {}).get("count") or 0,
            "severity": "critical",
            "href": "/core/inventory/view",
        },
        {
            "key": "untracked_items",
            "label": "Untracked items needing reconciliation",
            "count": (findings.get("untracked_items") or {}).get("count") or 0,
            "severity": "high",
            "href": "/core/notifications",
        },
        {
            "key": "output_expired",
            "label": "Expired outputs",
            "count": output_expiry.get("red_count") or 0,
            "severity": "critical",
            "href": "/core/notifications",
        },
        {
            "key": "output_not_ready",
            "label": "Outputs waiting for ready date",
            "count": output_ready.get("red_count") or 0,
            "severity": "informational",
            "href": "/core/notifications",
        },
        {
            "key": "overdue_tasks",
            "label": "Overdue CRM tasks",
            "count": (tasks_summary or {}).get("overdue_count") or 0,
            "severity": "high",
            "href": "/crm/tasks",
        },
    ]

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
    items = [item for item in candidates if (item.get("count") or 0) > 0]
    items.sort(key=lambda item: (severity_rank.get(str(item.get("severity") or "low"), 4), -(item.get("count") or 0)))
    critical_actions_total = sum(
        int(item.get("count") or 0) for item in items if str(item.get("severity") or "").lower() != "informational"
    )

    return {"critical_actions_total": critical_actions_total, "items": items[:6]}


@core_bp.route("/api/core/dashboard/summary", methods=["GET"])
@requires_auth
def get_dashboard_summary():
    org_id = UUID(g.org_id)
    window_days_raw = (request.args.get("window_days") or "30").strip()
    try:
        window_days = int(window_days_raw)
    except ValueError:
        return jsonify({"error": "window_days must be an integer"}), 400
    if window_days < 7 or window_days > 180:
        return jsonify({"error": "window_days must be between 7 and 180"}), 400

    today = date.today()
    now_dt = datetime.now()
    day_start = datetime.combine(today, datetime.min.time())
    next_day_start = day_start + timedelta(days=1)
    week_start, next_week_start, _prev_week_start = _dashboard_week_boundaries(today)

    runner = corechecks.CoreChecksRunner(org_id=org_id, session=db_session)
    check_results = runner.run_all_checks()

    from app.core.backend.system_status import build_system_status_payload

    system_status = build_system_status_payload(org_id, db_session, check_results)
    compliance = _dashboard_build_compliance_summary(check_results, system_status)

    operations_day_summary = _dashboard_operations_summary(org_id, db_session, day_start, next_day_start)
    operations_week_summary = _dashboard_operations_weekly_summary(org_id, db_session, now_dt, today)
    operator_actions_this_week = (
        db_session.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id)
        .filter(EntityEvent.created_at >= week_start, EntityEvent.created_at < next_week_start)
        .filter(EntityEvent.actor_type == "user")
        .count()
    )
    audit_log = {
        "limit": 10,
        "day": _dashboard_event_log_period(org_id, db_session, day_start, next_day_start, limit=10),
        "week": _dashboard_event_log_period(org_id, db_session, week_start, next_week_start, limit=10),
    }

    tasks_summary: dict[str, Any] = {
        "enabled": False,
        "open_count": 0,
        "due_today_count": 0,
        "overdue_count": 0,
        "due_this_week_count": 0,
        "top_tasks": [],
    }
    open_tasks_for_insights: list[dict[str, Any]] = []
    sales_summary: dict[str, Any] = {
        "enabled": False,
        "current_month_revenue": 0.0,
        "outstanding_receivables": 0.0,
        "revenue_vs_last_month_pct": None,
        "baseline_target_mtd": None,
        "baseline_variance_mtd": None,
        "baseline_attainment_pct": None,
    }
    revenue_daily_mtd: list[dict[str, Any]] = []

    if config.crm_enabled:
        try:
            from app.features.crm.services.crm_service import CRMService

            crm_service = CRMService(db_session)
            crm_overview = crm_service.get_overview(org_id)
            trace_cfg = crm_service.get_traceability_config(org_id)
            open_tasks_for_insights = crm_overview.get("open_tasks") or []
            tasks_summary = _dashboard_summarize_tasks(
                open_tasks_for_insights,
                today,
                week_start=week_start.date(),
                week_end_exclusive=next_week_start.date(),
            )
            month_start = today.replace(day=1)
            revenue_daily_mtd = crm_service.daily_sales_for_period(org_id, month_start, today + timedelta(days=1))
            baseline_target = trace_cfg.get("revenue_baseline_target_mtd")
            baseline_variance = None
            baseline_attainment = None
            if baseline_target is not None:
                try:
                    baseline_target = float(baseline_target)
                    baseline_variance = float((crm_overview.get("current_month_revenue") or 0.0) - baseline_target)
                    if baseline_target > 0:
                        baseline_attainment = round(
                            ((crm_overview.get("current_month_revenue") or 0.0) / baseline_target) * 100, 1
                        )
                except (TypeError, ValueError):
                    baseline_target = None
            sales_summary = {
                "enabled": True,
                "current_month_revenue": crm_overview.get("current_month_revenue") or 0.0,
                "outstanding_receivables": crm_overview.get("outstanding_receivables") or 0.0,
                "revenue_vs_last_month_pct": crm_overview.get("revenue_vs_last_month_pct"),
                "baseline_target_mtd": baseline_target,
                "baseline_variance_mtd": baseline_variance,
                "baseline_attainment_pct": baseline_attainment,
            }
        except Exception:
            logger.exception("Failed to assemble CRM summary for org_id=%s", org_id)

    action_board = _dashboard_build_action_board(tasks_summary, compliance)

    operator_series = _dashboard_series_from_date_counts(
        _dashboard_event_counts_by_day(org_id, db_session, week_start, next_week_start, actor_type="user"),
        start_day=week_start.date(),
        end_day=today,
        cumulative=True,
    )

    open_action_dates = _dashboard_open_action_item_dates(check_results, open_tasks_for_insights, today)
    open_action_counts: dict[date, int] = {}
    for d in open_action_dates:
        open_action_counts[d] = int(open_action_counts.get(d, 0)) + 1
    open_action_series = _dashboard_series_from_date_counts(
        open_action_counts,
        start_day=min(open_action_counts) if open_action_counts else (today - timedelta(days=6)),
        end_day=max(open_action_counts) if open_action_counts else today,
        cumulative=True,
    )

    execution_started_series = _dashboard_series_from_date_counts(
        _dashboard_execution_counts_by_day(org_id, db_session, week_start, next_week_start, column="started"),
        start_day=week_start.date(),
        end_day=today,
        cumulative=True,
    )
    execution_completed_series = _dashboard_series_from_date_counts(
        _dashboard_execution_counts_by_day(org_id, db_session, week_start, next_week_start, column="completed"),
        start_day=week_start.date(),
        end_day=today,
        cumulative=True,
    )

    tasks_due_counts: dict[date, int] = {}
    for task in open_tasks_for_insights:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"pending", "in_progress"}:
            continue
        due = _dashboard_parse_date_like(task.get("due_date"))
        if due is None:
            continue
        if week_start.date() <= due < next_week_start.date():
            tasks_due_counts[due] = int(tasks_due_counts.get(due, 0)) + 1
    tasks_due_series = _dashboard_series_from_date_counts(
        tasks_due_counts,
        start_day=week_start.date(),
        end_day=today,
        cumulative=True,
    )

    revenue_day_counts: dict[date, int] = {}
    for row in revenue_daily_mtd:
        if not isinstance(row, dict):
            continue
        d = _dashboard_parse_date_like(row.get("day"))
        if d is None:
            continue
        revenue_day_counts[d] = int(round(float(row.get("total") or 0)))
    month_start_date = today.replace(day=1)
    revenue_series = _dashboard_series_from_date_counts(
        revenue_day_counts,
        start_day=month_start_date,
        end_day=today,
        cumulative=True,
    )

    return (
        jsonify(
            {
                "generated_at": datetime.now().isoformat(),
                "window_days": window_days,
                "tasks": tasks_summary,
                "compliance": compliance,
                "action_board": action_board,
                "operator_actions": {"week_to_date": operator_actions_this_week},
                "audit_log": audit_log,
                "operations": operations_week_summary,
                "operations_today": operations_day_summary,
                "sales": sales_summary,
                "insight_series": {
                    "operator_actions_week": operator_series,
                    "open_action_items": open_action_series,
                    "active_batches_week": execution_started_series,
                    "batch_completion_week": execution_completed_series,
                    "tasks_due_week": tasks_due_series,
                    "revenue_goal_mtd": revenue_series,
                },
            }
        ),
        200,
    )


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
                "operational_counters": {
                    "scope": "process-local",
                    "note": "Counts are per web worker process; use an external sink to aggregate in multi-worker deployments.",
                    "counts": get_counter_snapshot(),
                },
            }
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Entity Event Endpoints — Summary, Story, and Sourcemap
# ---------------------------------------------------------------------------


def _parse_entity_type(entity_type: str) -> str | None:
    """Validate entity_type is one we support."""
    valid = {"inventory_item", "execution", "process", "user", "org"}
    return entity_type if entity_type in valid else None


def _event_to_dict(ev) -> dict:
    return {
        "id": str(ev.id),
        "event_type": ev.event_type,
        "entity_type": ev.entity_type,
        "entity_id": str(ev.entity_id) if ev.entity_id else None,
        "at": ev.created_at.isoformat() if ev.created_at else None,
        "actor": ev.actor_label,
        "actor_type": ev.actor_type,
        "payload": ev.payload,
        "diff": ev.diff,
        "causation_id": str(ev.causation_id) if ev.causation_id else None,
    }


_FIELD_LABELS = {
    "name": "Name",
    "description": "Description",
    "quantity": "Quantity",
    "unit": "Unit",
    "inventory_type": "Type",
    "supplier": "Supplier",
    "supplier_batch_number": "Batch number",
    "barcode": "Barcode",
    "purchase_date": "Purchase date",
    "expiry_date": "Expiry date",
    "step_number": "Position",
    "inputs": "Inputs",
    "outputs": "Outputs",
    "execution_prompts": "Prompts",
    "category": "Category",
    "is_draft": "Draft",
}

_ITEM_FIELD_LABELS = {
    "name": "Name",
    "label": "Label",
    "quantity": "Quantity",
    "unit": "Unit",
    "inventory_type": "Inventory type",
    "expected_inventory_type": "Expected type",
    "type": "Type",
    "required": "Required",
    "is_variable": "Variable qty",
    "requires_execution_confirmation": "Confirmation required",
    "description": "Description",
}

# Fields that are auto-populated by the system and should not be reported when
# they only appear in the after snapshot (i.e. before is None/absent).
_ITEM_IMPLICIT_FIELDS = frozenset(
    {
        "inventory_type",
        "expected_inventory_type",
        "is_variable",
        "requires_execution_confirmation",
    }
)

_INVENTORY_TYPE_LABELS = {
    "raw_material": "Raw material",
    "work_in_progress": "Work in progress",
    "final_product": "Final product",
}

_ITEM_SKIP_FIELDS = frozenset({"id", "extra_data"})


def _fmt_field_value(val) -> str:
    if val is None or val == "":
        return "—"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, list):
        if not val:
            return "(none)"
        if all(isinstance(i, dict) for i in val):
            parts = []
            for item in val:
                if "name" in item:
                    s = item["name"]
                    if item.get("quantity") is not None:
                        s += f" ({item['quantity']}"
                        if item.get("unit"):
                            s += f" {item['unit']}"
                        s += ")"
                    parts.append(s)
                elif "label" in item:
                    s = item["label"]
                    if item.get("type"):
                        s += f" ({item['type']})"
                    parts.append(s)
            if parts:
                return ", ".join(parts)
        return f"{len(val)} item{'s' if len(val) != 1 else ''}"
    if isinstance(val, str) and val in _INVENTORY_TYPE_LABELS:
        return _INVENTORY_TYPE_LABELS[val]
    return str(val)


def _fmt_sub_val(val, field: str = "") -> str:
    if val is None or val == "":
        return "(none)"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, list | dict):
        return "(complex)"
    if field in ("inventory_type", "expected_inventory_type"):
        return _INVENTORY_TYPE_LABELS.get(str(val), str(val))
    return str(val)


def _item_key(item: dict) -> str | None:
    for k in ("id", "name", "label"):
        if k in item:
            return str(item[k])
    return None


def _item_display_name(item: dict) -> str:
    return item.get("name") or item.get("label") or "(item)"


def _smart_list_diff_rows(label: str, before: list, after: list) -> list[dict]:
    """Deep diff two lists of dicts, returning structured {label, before, after} rows."""
    rows: list[dict] = []
    before_by_key: dict = {}
    after_by_key: dict = {}
    for item in before:
        k = _item_key(item)
        if k:
            before_by_key[k] = item
    for item in after:
        k = _item_key(item)
        if k:
            after_by_key[k] = item

    if not before_by_key and not after_by_key:
        if before != after:
            rows.append({"label": label, "before": _fmt_field_value(before), "after": _fmt_field_value(after)})
        return rows

    seen: set = set()
    for item in before:
        k = _item_key(item)
        if not k or k in seen:
            continue
        seen.add(k)
        a_item = after_by_key.get(k)
        if a_item is None:
            rows.append({"label": label, "before": f"'{_item_display_name(item)}' removed", "after": None})
        else:
            all_fields = [f for f in set(item) | set(a_item) if f not in _ITEM_SKIP_FIELDS]
            for field in all_fields:
                b_val = item.get(field)
                a_val = a_item.get(field)
                if b_val == a_val:
                    continue
                # Skip fields that are auto-populated when they were simply absent before
                if field in _ITEM_IMPLICIT_FIELDS and b_val is None:
                    continue
                fl = _ITEM_FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
                rows.append(
                    {
                        "label": f"{label} '{_item_display_name(item)}' – {fl}",
                        "before": _fmt_sub_val(b_val, field),
                        "after": _fmt_sub_val(a_val, field),
                    }
                )

    for item in after:
        k = _item_key(item)
        if not k or k in seen:
            continue
        seen.add(k)
        if k not in before_by_key:
            rows.append({"label": label, "before": None, "after": f"'{_item_display_name(item)}' added"})

    return rows


def _build_diff_rows(diff: dict) -> list[dict]:
    """Build structured diff rows: [{label, before, after}]. before/after may be None."""
    rows: list[dict] = []
    for field, change in (diff or {}).items():
        if not isinstance(change, dict):
            continue
        label = _FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
        before = change.get("before")
        after = change.get("after")
        if isinstance(before, list) and isinstance(after, list) and all(isinstance(i, dict) for i in (before + after)):
            rows.extend(_smart_list_diff_rows(label, before, after))
        else:
            b_str = _fmt_field_value(before)
            a_str = _fmt_field_value(after)
            if b_str != a_str:
                rows.append(
                    {
                        "label": label,
                        "before": None if b_str == "—" else b_str,
                        "after": None if a_str == "—" else a_str,
                    }
                )
    return rows


def _step_added_diff_rows(step_data: dict) -> list[dict]:
    """Synthesize diff rows for a newly added step from its snapshot payload."""
    rows: list[dict] = []
    desc = step_data.get("description")
    if desc:
        rows.append({"label": "Description", "before": None, "after": desc})
    for inp in step_data.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        name = _item_display_name(inp)
        qty = inp.get("quantity")
        unit = inp.get("unit", "")
        detail = f"'{name}'"
        if qty is not None:
            detail += f" — {qty} {unit}".rstrip()
        rows.append({"label": "Input", "before": None, "after": detail})
    for out in step_data.get("outputs") or []:
        if not isinstance(out, dict):
            continue
        name = _item_display_name(out)
        qty = out.get("quantity")
        unit = out.get("unit", "")
        detail = f"'{name}'"
        if qty is not None:
            detail += f" — {qty} {unit}".rstrip()
        rows.append({"label": "Output", "before": None, "after": detail})
    for pr in step_data.get("execution_prompts") or []:
        if not isinstance(pr, dict):
            continue
        label = pr.get("label") or pr.get("name") or "(prompt)"
        rows.append({"label": "Prompt", "before": None, "after": label})
    return rows


def _event_diff_rows(ev) -> list[dict]:
    """Return per-change diff rows for an event, handling nested step diffs."""
    et = ev.event_type
    p = ev.payload or {}
    if et == "process.step_added":
        return _step_added_diff_rows(p.get("step") or {})
    if et == "process.step_updated":
        return _build_diff_rows((ev.diff or {}).get("step") or {})
    return _build_diff_rows(ev.diff or {})


def _human_summary(ev) -> str:
    et = ev.event_type
    p = ev.payload or {}
    d = ev.diff or {}

    if et == "inventory_item.created":
        qty = p.get("quantity", "")
        unit = p.get("unit", "")
        method = p.get("add_method", "manual").replace("_", " ")
        inv_type = _INVENTORY_TYPE_LABELS.get(
            p.get("inventory_type") or "", (p.get("inventory_type") or "").replace("_", " ")
        )
        parts = [f"Added {qty} {unit}".strip()]
        if inv_type:
            parts[0] += f" ({inv_type})"
        parts.append(f"via {method}")
        supplier = p.get("supplier")
        batch = p.get("supplier_batch_number")
        if supplier:
            parts.append(f"· supplier: {supplier}")
        if batch:
            parts.append(f"· batch: {batch}")
        return " ".join(parts)

    if et == "inventory_item.quantity_adjusted":
        before = p.get("quantity_before", "?")
        after = p.get("quantity_after", p.get("quantity", "?"))
        unit = p.get("unit", "")
        return f"Quantity adjusted {before} → {after} {unit}".strip()

    if et == "inventory_item.consumed":
        qty = p.get("quantity_consumed", "?")
        unit = p.get("unit", "")
        step = p.get("step_name", "")
        base = f"{qty} {unit} consumed".strip()
        if step:
            base += f" in '{step}'"
        return base

    if et == "inventory_item.produced":
        qty = p.get("quantity_produced", "?")
        unit = p.get("unit", "")
        step = p.get("step_name", "")
        base = f"{qty} {unit} produced".strip()
        if step:
            base += f" by '{step}'"
        return base

    if et == "inventory_item.wasted":
        qty = p.get("quantity_wasted", "?")
        unit = p.get("unit", "")
        reason = p.get("reason", "")
        base = f"{qty} {unit} wasted".strip()
        if reason:
            base += f" — {reason}"
        return base

    if et == "inventory_item.updated":
        if not d:
            return "Updated"
        field_labels = {
            "name": "name",
            "inventory_type": "type",
            "quantity": "quantity",
            "unit": "unit",
            "supplier": "supplier",
            "supplier_batch_number": "batch",
            "purchase_date": "purchase date",
            "expiry_date": "expiry date",
            "barcode": "barcode",
        }
        changed = [field_labels.get(k, k) for k in d]
        return "Updated " + ", ".join(changed)

    if et == "inventory_item.deleted":
        name = p.get("name", "")
        return f"Deleted{(' ' + name) if name else ''}"

    if et == "execution.created":
        steps = p.get("total_steps", "")
        ver = p.get("process_version_number", "")
        base = "Batch started"
        if steps:
            base += f" — {steps} steps"
        if ver:
            base += f" (process v{ver})"
        return base

    if et == "execution.step_completed":
        step = p.get("step_name", f"Step {p.get('step_number', '?')}")
        consumed = p.get("items_consumed") or []
        produced = p.get("items_produced") or []
        base = f"'{step}' completed"
        if consumed:
            base += f" — {len(consumed)} input{'s' if len(consumed) != 1 else ''} consumed"
        if produced:
            base += f", {len(produced)} output{'s' if len(produced) != 1 else ''} produced"
        return base

    if et == "execution.completed":
        steps = p.get("total_steps", "")
        base = "Batch completed"
        if steps:
            base += f" ({steps} steps)"
        return base

    if et == "execution.cancelled":
        reason = p.get("reason", "")
        base = "Batch cancelled"
        if reason:
            base += f" — {reason}"
        return base

    if et == "process.created":
        name = p.get("name", "")
        return f"Process{(' ' + repr(name)) if name else ''} created"

    if et == "process.updated":
        return "Process updated"

    if et == "process.step_added":
        step_data = p.get("step") or {}
        step_name = step_data.get("name", "step")
        pos = step_data.get("step_number", "")
        base = f"Step '{step_name}' added"
        if pos:
            base += f" at position {pos}"
        return base

    if et == "process.step_updated":
        step_name = (p.get("step") or {}).get("name", "step")
        return f"Step '{step_name}' updated"

    if et == "process.step_deleted":
        step = (p.get("deleted_step") or {}).get("name", "step")
        return f"Step '{step}' removed"

    if et == "process.deleted":
        name = p.get("name", "")
        return f"Process{(' ' + repr(name)) if name else ''} deleted"

    if et == "process.step_doc_uploaded":
        step = p.get("step_name", "step")
        title = p.get("doc_title", "document")
        return f"SOP file '{title}' uploaded to step '{step}'"

    if et == "process.step_doc_created":
        step = p.get("step_name", "step")
        title = p.get("doc_title", "document")
        return f"SOP instructions '{title}' written for step '{step}'"

    if et == "process.step_doc_updated":
        step = p.get("step_name", "step")
        title = p.get("doc_title", "document")
        return f"SOP instructions '{title}' updated for step '{step}'"

    if et == "process.step_doc_deleted":
        step = p.get("step_name", "step")
        title = p.get("doc_title", "document")
        return f"SOP document '{title}' removed from step '{step}'"

    if et == "user.created":
        return f"Account created — {p.get('email', '')}"

    if et == "user.login":
        method = "with 2FA" if p.get("2fa_used") else "with password"
        return f"Logged in {method} from {p.get('ip', '?')}"

    if et == "user.login_failed":
        return f"Login failed from {p.get('ip', '?')} (attempt {p.get('failed_attempts', '?')})"

    if et == "user.2fa_enabled":
        return "Two-factor authentication enabled"

    if et == "user.2fa_disabled":
        return "Two-factor authentication disabled"

    if et == "user.role_changed":
        return f"Role changed from {p.get('old_role', '?')} to {p.get('new_role', '?')}"

    if et == "org.settings_updated":
        d = ev.diff or {}
        parts = []
        if "name" in d:
            parts.append(f"Name changed to '{d['name'].get('after', '?')}'")
        if "status" in d:
            parts.append(f"Status changed to {d['status'].get('after', '?')}")
        return "Organisation settings updated" + (f" — {', '.join(parts)}" if parts else "")

    return et.replace(".", " — ").replace("_", " ").capitalize()


@core_bp.route("/api/core/entities/<entity_type>/<entity_id>/story", methods=["GET"])
@requires_auth
def entity_story(entity_type: str, entity_id: str):
    """Full event timeline for a single entity, ordered chronologically.

    Used when drilling into a card to see its complete audit history.
    For inventory items, legacy extra_data.inventory_audit_history entries are
    merged in so nothing is lost — deduplicated against entity_events by timestamp.
    """
    from app.core.db.models.entity_event import EntityEvent

    etype = _parse_entity_type(entity_type)
    if not etype:
        return jsonify({"error": "Invalid entity_type"}), 400

    try:
        eid = UUID(entity_id)
    except ValueError:
        return jsonify({"error": "Invalid entity_id"}), 400

    org_id = UUID(g.org_id)
    limit = min(int(request.args.get("limit", 200)), 500)
    offset = int(request.args.get("offset", 0))

    db = db_session()
    events = (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id, EntityEvent.entity_id == eid)
        .order_by(EntityEvent.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total = db.query(EntityEvent).filter(EntityEvent.org_id == org_id, EntityEvent.entity_id == eid).count()

    event_dicts = [
        {**_event_to_dict(ev), "summary": _human_summary(ev), "diff_rows": _event_diff_rows(ev)} for ev in events
    ]

    if etype == "inventory_item":
        event_dicts = _merge_inventory_legacy_audit(db, eid, org_id, event_dicts, events)

    return jsonify(
        {
            "entity_id": str(eid),
            "entity_type": etype,
            "total": total,
            "offset": offset,
            "events": event_dicts,
        }
    ), 200


def _merge_inventory_legacy_audit(db, eid: UUID, org_id: UUID, event_dicts: list, events: list) -> list:
    """Merge extra_data.inventory_audit_history into the entity_events timeline.

    - Entries within 10 s of an existing entity_event are considered the same
      action: the display name from the legacy entry augments the actor field.
    - Entries with no matching entity_event are inserted as standalone timeline
      items (covers pre-event-sourcing items and barcode re-stocks).
    - user_id is always stripped.
    """
    from datetime import datetime

    from app.core.db.models.inventory_item import InventoryItem

    item = db.query(InventoryItem).filter(InventoryItem.id == eid, InventoryItem.org_id == org_id).first()
    if not item or not item.extra_data:
        return event_dicts

    legacy_entries = item.extra_data.get("inventory_audit_history") or []
    if not legacy_entries:
        return event_dicts

    # Build a lookup of entity_event timestamps (naive UTC) → index in event_dicts
    ev_timestamps = []
    for ev in events:
        if ev.created_at:
            ts = ev.created_at.replace(tzinfo=None) if ev.created_at.tzinfo else ev.created_at
            ev_timestamps.append(ts)
        else:
            ev_timestamps.append(None)

    def _parse_legacy_ts(ts_str):
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            return None

    def _actor_display(entry):
        name = (entry.get("operator_name") or "").strip()
        email = (entry.get("operator_email") or "").strip()
        if name and email and name != email:
            return f"{name} ({email})"
        return name or email or ""

    def _legacy_summary(entry):
        method = (entry.get("source_method") or "manual").replace("_", " ")
        parts = []
        qty = entry.get("quantity_added")
        if qty:
            parts.append(f"Added {qty}")
        else:
            parts.append("Item recorded")
        parts.append(f"via {method}")
        supplier = entry.get("supplier")
        batch = entry.get("supplier_batch_number")
        purchase = entry.get("purchase_date")
        expiry = entry.get("expiry_date")
        if supplier:
            parts.append(f"· supplier: {supplier}")
        if batch:
            parts.append(f"· batch: {batch}")
        if purchase:
            parts.append(f"· purchased: {purchase}")
        if expiry:
            parts.append(f"· expiry: {expiry}")
        return " ".join(parts)

    extra_events = []
    for entry in legacy_entries:
        if not isinstance(entry, dict):
            continue
        entry = {k: v for k, v in entry.items() if k != "user_id"}
        legacy_ts = _parse_legacy_ts(entry.get("timestamp_utc"))

        matched_idx = None
        if legacy_ts:
            for i, ev_ts in enumerate(ev_timestamps):
                if ev_ts and abs((legacy_ts - ev_ts).total_seconds()) < 10:
                    matched_idx = i
                    break

        if matched_idx is not None:
            # Augment the matching event's actor with the display name if available
            name = (entry.get("operator_name") or "").strip()
            email = (entry.get("operator_email") or "").strip()
            if name and email and name != email:
                current = event_dicts[matched_idx].get("actor") or ""
                if name not in current:
                    event_dicts[matched_idx] = dict(event_dicts[matched_idx])
                    event_dicts[matched_idx]["actor"] = f"{name} ({current})" if current else name
        else:
            extra_events.append(
                {
                    "id": f"legacy_{entry.get('timestamp_utc', '')}",
                    "event_type": "inventory_item.legacy_entry",
                    "entity_type": "inventory_item",
                    "entity_id": str(eid),
                    "at": entry.get("timestamp_utc"),
                    "actor": _actor_display(entry),
                    "actor_type": "user",
                    "summary": _legacy_summary(entry),
                    "diff_rows": [],
                    "payload": None,
                    "diff": None,
                    "causation_id": None,
                }
            )

    if extra_events:
        merged = event_dicts + extra_events
        merged.sort(key=lambda e: e.get("at") or "")
        return merged

    return event_dicts


@core_bp.route("/api/core/entities/<entity_type>/<entity_id>/summary", methods=["GET"])
@requires_auth
def entity_summary_detail(entity_type: str, entity_id: str):
    """Rich computed summary for a single entity card detail view.

    Queries entity_events directly (more detail than the pre-computed summary table).
    """
    from app.core.db.models.entity_event import EntityEvent
    from app.core.db.models.entity_event_summary import EntityEventSummary

    etype = _parse_entity_type(entity_type)
    if not etype:
        return jsonify({"error": "Invalid entity_type"}), 400

    try:
        eid = UUID(entity_id)
    except ValueError:
        return jsonify({"error": "Invalid entity_id"}), 400

    org_id = UUID(g.org_id)
    db = db_session()

    # Pull pre-computed summary
    summary_row = db.query(EntityEventSummary).filter(EntityEventSummary.entity_id == eid).first()
    summary = summary_row.summary if summary_row else {}

    # Pull most recent 10 events for "recent_events" display
    recent = (
        db.query(EntityEvent)
        .filter(EntityEvent.org_id == org_id, EntityEvent.entity_id == eid)
        .order_by(EntityEvent.created_at.desc())
        .limit(10)
        .all()
    )

    return jsonify(
        {
            "entity_id": str(eid),
            "entity_type": etype,
            "summary": summary,
            "recent_events": [
                {**_event_to_dict(ev), "summary": _human_summary(ev), "diff_rows": _event_diff_rows(ev)}
                for ev in reversed(recent)
            ],
        }
    ), 200


@core_bp.route("/api/core/entities/activity", methods=["GET"])
@requires_auth
def entity_activity_feed():
    """All entity events for the org, newest-first, with optional date/type filtering.

    Powers the sourcemap Activity tab and any org-wide audit stream.
    """
    from app.core.db.models.entity_event import EntityEvent

    org_id = UUID(g.org_id)
    limit = min(int(request.args.get("limit", 150)), 500)
    offset = int(request.args.get("offset", 0))
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")
    entity_types_param = request.args.get("entity_types", "")

    db = db_session()
    q = db.query(EntityEvent).filter(EntityEvent.org_id == org_id)

    if entity_types_param:
        allowed = [t.strip() for t in entity_types_param.split(",") if t.strip()]
        if allowed:
            q = q.filter(EntityEvent.entity_type.in_(allowed))

    if from_date:
        try:
            from datetime import timezone as _tz

            fd = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=_tz.utc)
            q = q.filter(EntityEvent.created_at >= fd)
        except ValueError:
            pass

    if to_date:
        try:
            from datetime import timezone as _tz

            td = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=_tz.utc)
            q = q.filter(EntityEvent.created_at <= td)
        except ValueError:
            pass

    total = q.count()
    events = q.order_by(EntityEvent.created_at.desc()).offset(offset).limit(limit).all()

    return jsonify(
        {
            "total": total,
            "offset": offset,
            "events": [
                {**_event_to_dict(ev), "summary": _human_summary(ev), "diff_rows": _event_diff_rows(ev)}
                for ev in events
            ],
        }
    ), 200


@core_bp.route("/api/core/sourcemap/objects", methods=["GET"])
@requires_auth
def sourcemap_objects():
    """Lightweight paginated index of all traceable entities.

    Returns just enough for selectors — no joins to steps or execution_steps.
    """
    org_id = UUID(g.org_id)
    db = db_session()

    page = max(1, int(request.args.get("page", 1)))
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = (page - 1) * limit
    q = request.args.get("q", "").strip()
    entity_type_filter = request.args.get("type", "").strip()

    objects = []
    total = 0

    from app.core.db.models.execution import Execution
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.process import Process

    if not entity_type_filter or entity_type_filter == "inventory_item":
        inv_q = db.query(InventoryItem).filter(InventoryItem.org_id == org_id)
        if q:
            inv_q = inv_q.filter(InventoryItem.name.ilike(f"%{q}%"))
        inv_count = inv_q.count()
        total += inv_count
        for item in (
            inv_q.order_by(InventoryItem.created_at.desc())
            .offset(offset if not entity_type_filter else 0)
            .limit(limit)
            .all()
        ):
            objects.append(
                {
                    "id": str(item.id),
                    "type": "inventory_item",
                    "label": item.display_label or item.name,
                    "sublabel": f"{item.inventory_type.replace('_', ' ').title()} · {item.quantity} {item.unit}",
                    "discriminators": {
                        "supplier": item.supplier,
                        "batch_number": item.supplier_batch_number,
                        "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                        "quantity": str(item.quantity),
                        "unit": item.unit,
                    },
                    "traceable_since": item.created_at.isoformat() if item.created_at else None,
                    "is_consumed": str(item.quantity) == "0.0000",
                }
            )

    if not entity_type_filter or entity_type_filter == "execution":
        exec_q = db.query(Execution).filter(Execution.org_id == org_id)
        exec_count = exec_q.count()
        total += exec_count
        for ex in exec_q.order_by(Execution.created_at.desc()).limit(limit).all():
            objects.append(
                {
                    "id": str(ex.id),
                    "type": "execution",
                    "label": f"Execution #{str(ex.id)[:8]}",
                    "sublabel": f"{ex.status.value.replace('_', ' ').title()} · {ex.total_steps or '?'} steps",
                    "discriminators": {
                        "process_id": str(ex.process_id),
                        "status": ex.status.value,
                        "started_at": ex.started_at.isoformat() if ex.started_at else None,
                    },
                    "traceable_since": ex.created_at.isoformat() if ex.created_at else None,
                }
            )

    if not entity_type_filter or entity_type_filter == "process":
        proc_q = db.query(Process).filter(Process.org_id == org_id)
        if q:
            proc_q = proc_q.filter(Process.name.ilike(f"%{q}%"))
        proc_count = proc_q.count()
        total += proc_count
        for proc in proc_q.order_by(Process.created_at.desc()).limit(limit).all():
            objects.append(
                {
                    "id": str(proc.id),
                    "type": "process",
                    "label": proc.name,
                    "sublabel": f"{'Draft' if proc.is_draft else 'Published'} · {proc.category.value if proc.category else 'Uncategorised'}",
                    "discriminators": {
                        "category": proc.category.value if proc.category else None,
                        "is_draft": proc.is_draft,
                    },
                    "traceable_since": proc.created_at.isoformat() if proc.created_at else None,
                }
            )

    return jsonify({"objects": objects[:limit], "total": total, "page": page}), 200


@core_bp.route("/api/core/sourcemap/trace", methods=["POST"])
@requires_auth
def sourcemap_trace():
    """On-demand DAG traversal — current state or temporal (with as_of).

    Routes to DAGTracer (current) or TemporalDAGTracer (historical).
    """
    data = request.get_json() or {}
    root_type = data.get("root_type", "inventory_item")
    root_id_str = data.get("root_id")
    as_of_str = data.get("as_of")
    depth = min(int(data.get("depth", 5)), 10)

    if not root_id_str:
        return jsonify({"error": "root_id is required"}), 400

    try:
        root_id = UUID(root_id_str)
    except ValueError:
        return jsonify({"error": "Invalid root_id"}), 400

    org_id = UUID(g.org_id)
    db = db_session()

    # Temporal trace — use as_of if provided
    if as_of_str:
        try:
            as_of = datetime.fromisoformat(as_of_str.replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "Invalid as_of datetime format"}), 400

        from app.core.backend.temporal_dag_tracer import TemporalDAGTracer

        tracer = TemporalDAGTracer(db, org_id, as_of, max_depth=depth)
        result = tracer.trace(root_id, root_type)

        # Annotate timeline with human summaries
        from app.core.db.models.entity_event import EntityEvent as _EE_Trace

        timeline_ids = [item.get("event_id") for item in result["timeline"] if item.get("event_id")]
        events_by_id: dict = {}
        if timeline_ids:
            ev_rows = db.query(_EE_Trace).filter(_EE_Trace.id.in_(timeline_ids)).all()
            events_by_id = {str(ev.id): ev for ev in ev_rows}
        story = [
            {
                "at": item["at"],
                "event_type": item["event_type"],
                "entity_id": item["entity_id"],
                "summary": _human_summary(events_by_id[item["event_id"]])
                if item.get("event_id") and item["event_id"] in events_by_id
                else item["event_type"].replace(".", " — ").replace("_", " ").capitalize(),
                "actor": item.get("actor"),
            }
            for item in result["timeline"]
        ]

        return jsonify(
            {
                "root": next(
                    (n for n in result["nodes"] if n["is_root"]), result["nodes"][0] if result["nodes"] else {}
                ),
                "nodes": result["nodes"],
                "edges": result["edges"],
                "as_of": result["as_of"],
                "is_current": False,
                "story": story,
            }
        ), 200

    # Current state trace — use existing DAGTracer
    from app.core.db.models.inventory_item import InventoryItem

    item = db.query(InventoryItem).filter(InventoryItem.id == root_id, InventoryItem.org_id == org_id).first()
    if not item:
        return jsonify({"error": "Item not found"}), 404

    try:
        from app.features.workflow_engine.dagtraversal import trace_backward, trace_forward

        result_fwd = trace_forward(str(root_id), db, org_id=str(org_id))
        result_bwd = trace_backward(str(root_id), db, org_id=str(org_id))

        all_nodes = {n["id"]: n for n in (result_fwd.nodes + result_bwd.nodes)}
        all_edges = list({(e["from_id"], e["to_id"]): e for e in (result_fwd.edges + result_bwd.edges)}.values())

        return jsonify(
            {
                "root": {"id": str(root_id), "type": "inventory_item", "label": item.display_label or item.name},
                "nodes": list(all_nodes.values()),
                "edges": [
                    {"from": e["from_id"], "to": e["to_id"], "execution_id": e.get("execution_id")} for e in all_edges
                ],
                "as_of": None,
                "is_current": True,
                "story": [],
            }
        ), 200
    except Exception:
        logger.exception("Trace failed")
        return jsonify({"error": "Trace failed"}), 500


def _is_valid_uuid(v: str) -> bool:
    try:
        UUID(v)
        return True
    except (ValueError, AttributeError):
        return False
