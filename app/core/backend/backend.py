"""Core backend API routes for process execution platform"""

import base64
import functools
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
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
from pydantic import ValidationError

from app.api.routes.auth_routes import limiter
from app.core.backend import (
    changes_feed,
    inventory_routes,
    inventory_upload_routes,
    process_design_routes,
    suppliers,
    tasks,
    traceability_routes,
)
from app.core.backend.complete_step_payload import (
    MAX_COMPLETE_STEP_CONTENT_LENGTH,
    CompleteStepRequestBody,
    validate_json_blob,
)
from app.core.backend.complete_step_payload import (
    MAX_JSON_DEPTH as _STRIP_MAX_DEPTH,
)
from app.core.backend.evidence import evidence_routes
from app.core.backend.evidence.evidence_service import list_evidence_for_execution, list_evidence_for_executions_batch
from app.core.backend.process_docs import process_docs_routes
from app.core.backend.static_assets import core_asset_directory, iter_core_assets
from app.core.backend.step_outputs import apply_whole_unit_rules, parse_output_batch_number
from app.core.db import db_session
from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.execution_evidence import EVIDENCE_STATUS_ACTIVE, ExecutionEvidence
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.domain.expiry_ready_date_rules import assert_expiry_after_ready_dates
from app.core.domain.expiry_rules import VALID_EXPIRY_UNITS, assert_warning_within_expiry
from app.core.domain.expiry_rules import duration_to_timedelta as expiry_duration_to_timedelta
from app.core.domain.inventory_quantity_guard import (
    InventoryQuantityWriteReason,
    allow_inventory_quantity_write,
)
from app.core.security.permissions import requires_auth
from app.core.utils.internal_counters import inc_counter
from app.core.utils.log_action import log_action
from app.core.utils.unit_conversion import are_units_compatible, convert_to_inventory_unit_decimal
from app.features.activity_log.routes import activity_routes
from app.features.compliance_checks.checks.output_ready_date_check import is_inventory_item_ready_for_consumption
from app.features.compliance_checks.routes import corechecks
from app.features.dashboard.routes import dashboard_routes
from app.features.demo_data.routes import api_routes as demo_data_routes
from app.features.demo_data.services.resetdb import DEMO_USER_EMAIL
from app.features.reconciliation.routes import reconciliation_routes
from app.features.wastage.routes import wastage_routes
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)

_flow_process_id_from_request = process_design_routes._flow_process_id_from_request
_assert_flow_process_access = process_design_routes._assert_flow_process_access


def _product_available(feature: str) -> bool:
    """Whether an optional product completed registration in this app instance."""
    return bool(current_app.extensions.get("product_availability", {}).get(feature, False))


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


@core_bp.route("/settings", methods=["GET"])
@core_bp.route("/workflow-engine/settings", methods=["GET"])
@core_bp.route("/core/settings", methods=["GET"])
@requires_auth
def settings():
    if request.path != "/core/settings":
        return redirect("/core/settings", code=308)
    return render_template("settings/settings.html", active_page="settings")


@core_bp.route("/core/executions/live", methods=["GET"])
@requires_auth
def executions_live_view():
    """Dedicated active batches experience (drill-in from Core product workflows tab)."""
    return render_template("core/core2.html", active_page="core", core2_focus="active_batches_live")


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
    from flask import abort
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
    from flask import abort
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
    from flask import abort
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

    # count=1 -> just the total (for a paginated caller's "N batches" header). No object
    # graph, no growth with history.
    if request.args.get("count") in ("1", "true"):
        return jsonify({"count": repo.count_executions(org_id=org_id, process_id=process_id, status=status)}), 200

    try:
        page_limit, cursor = _parse_page_params(request.args)
    except ValueError:
        return jsonify({"error": "Invalid limit or cursor parameter"}), 400
    executions = repo.list_executions(
        org_id=org_id,
        process_id=process_id,
        status=status,
        limit=(page_limit + 1 if page_limit is not None else None),
        cursor=cursor,
    )
    has_more = page_limit is not None and len(executions) > page_limit
    if has_more:
        executions = executions[:page_limit]

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

    # execution_steps is already joinedload'd by ExecutionRepository.list_executions
    # above, so the access below is in-memory, not a per-iteration query.
    result = []
    for execution in executions:
        execution_steps = execution.execution_steps or []  # nosemgrep: orm-relationship-access-in-loop
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

    body = {"executions": result}
    if page_limit is not None:
        body["has_more"] = has_more
        body["next_cursor"] = (
            _encode_list_cursor(executions[-1].created_at, executions[-1].id) if has_more and executions else None
        )
    return jsonify(body), 200


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


def _prompt_value_violation(value: Any, constraint: Any) -> str | None:
    """Check a module-required execution-prompt value Core itself captured.

    Generic by design: the constraint names the prompt label and optional inclusive
    numeric bounds; which compliance rule asked for it stays with the module.
    """
    label = constraint.prompt_label
    if value is None or (isinstance(value, str) and not value.strip()):
        return constraint.message
    if constraint.minimum is None and constraint.maximum is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return f'"{label}" must be a number.'
    if not number.is_finite():
        return f'"{label}" must be a number.'
    if (constraint.minimum is not None and number < constraint.minimum) or (
        constraint.maximum is not None and number > constraint.maximum
    ):
        return f'"{label}" must be between {constraint.minimum} and {constraint.maximum}.'
    return None


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
        # Installed Compliant modules contribute normalized workflow rules through their
        # own platform registry. Core knows only how to verify its own operational facts
        # (such as an active evidence file), never which industry or framework requested
        # the constraint.
        if _product_available("compliant"):
            from app.features.compliant.platform.workflow_rules import completion_constraints

            policy_step = (
                db_session.query(ExecutionStep)
                .filter(
                    ExecutionStep.id == execution_step_uuid,
                    ExecutionStep.execution_id == execution_uuid,
                    ExecutionStep.org_id == org_id,
                )
                .one_or_none()
            )
            constraints = completion_constraints(
                db_session, org_id, policy_step.step_id if policy_step is not None else None
            )
            for constraint in constraints:
                if constraint.requirement != "prompt_value" or not constraint.prompt_label:
                    continue
                violation = _prompt_value_violation(execution_data.get(constraint.prompt_label), constraint)
                if violation:
                    return jsonify({"error": violation, "code": constraint.code, "action": constraint.action}), 409
            evidence_constraints = [item for item in constraints if item.requirement == "active_evidence"]
            if evidence_constraints:
                if policy_step is not None:
                    has_evidence = (
                        db_session.query(ExecutionEvidence.id)
                        .filter(
                            ExecutionEvidence.org_id == org_id,
                            ExecutionEvidence.execution_id == execution_uuid,
                            ExecutionEvidence.step_id == policy_step.step_id,
                            ExecutionEvidence.evidence_status == EVIDENCE_STATUS_ACTIVE,
                        )
                        .first()
                        is not None
                    )
                    if not has_evidence:
                        constraint = evidence_constraints[0]
                        return jsonify(
                            {
                                "error": constraint.message,
                                "code": constraint.code,
                                "action": constraint.action,
                            }
                        ), 409

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
                    # Per-item FOR UPDATE lock with per-entry error accumulation
                    # (execution_errors above); batching would change lock-acquisition
                    # order and continue-on-error semantics for a small, bounded
                    # per-execution input list.
                    # nosemgrep: repository-get-in-for-loop
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

                # sample_only override: a step's static output definition can force
                # WORK_IN_PROGRESS regardless of terminal-step position, for outputs that
                # must never be presented as saleable finished stock (e.g. process_templates'
                # R&D/QA-sample templates, which are structurally single-step and therefore
                # always terminal). Same extra_data-on-output-definition pattern custom_expiry
                # uses below, checked here so it can override before extra_data is built.
                _sample_only_step_def = getattr(execution_step, "step", None)
                _sample_only_outputs_def = (
                    _sample_only_step_def.outputs
                    if _sample_only_step_def and getattr(_sample_only_step_def, "outputs", None)
                    else []
                )
                for _od in _sample_only_outputs_def or []:
                    if isinstance(_od, dict) and (_od.get("name") or "").strip() == output_name:
                        if (_od.get("extra_data") or {}).get("sample_only"):
                            inventory_type = InventoryType.WORK_IN_PROGRESS.value
                        break

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

                parse_output_batch_number(output, output_name, extra_data, execution_warnings)

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

        # Whole bottles; remainders to Library stock (plan 1.2, app/core/backend/step_outputs.py)
        _step_process = getattr(getattr(execution_step, "step", None), "process", None)
        execution_errors.extend(
            apply_whole_unit_rules(output_creations, actual_outputs, getattr(_step_process, "settings", None))
        )
        # Block inventory creation when output validation failed (e.g. custom_expiry warning > duration)
        if execution_errors:
            db_session.rollback()
            return jsonify({"error": "Execution failed", "details": execution_errors}), 400

        # FAILURE HANDLING: Persist warnings to execution_data for audit trail
        # Reassign (not in-place mutate) the JSONB dict: execution_data was already
        # flushed once above (db_session.flush()), so an in-place key add on the same
        # dict object is invisible to SQLAlchemy's dirty tracking (JSONB is not
        # MutableDict-wrapped) and would be silently dropped by the commit below.
        if execution_warnings:
            execution_step.execution_data = {
                **(execution_step.execution_data or {}),
                "execution_warnings": execution_warnings,
            }

        # TRANSACTION INTEGRITY: Commit all inventory operations atomically
        # This ensures inventory consumption and output creation are atomic per execution step
        try:
            # Apply inventory updates. Flush while still inside the guard: a step that only
            # consumes (no actual_outputs, e.g. a terminal "labelling" step consuming a
            # bottled-product item) never re-enters allow_inventory_quantity_write via
            # create_inventory_item below, so these dirty quantity changes would otherwise
            # sit unflushed until the plain db_session.commit() further down -- outside any
            # guard -- and autoflush's before_flush check would reject them right there.
            with allow_inventory_quantity_write(InventoryQuantityWriteReason.EXECUTION_STEP_INVENTORY):
                for inventory_item, new_quantity in inventory_updates:
                    inventory_item.quantity = new_quantity
                db_session.flush()

            # Create inventory items for outputs; when reconciling to untracked, reduce first then create only surplus
            from app.features.reconciliation.service import reconcile_output_to_untracked_reduce_only

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
            logger.warning(
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
        logger.exception("Error completing execution step")
        err_detail = str(e) if e else "Unknown error"
        db_session.rollback()
        return jsonify({"error": "Failed to complete step", "details": err_detail}), 500


activity_routes.register_routes(core_bp)
dashboard_routes.register_routes(core_bp)
changes_feed.register_routes(core_bp)
corechecks.register_routes(core_bp)
reconciliation_routes.register_routes(core_bp)
inventory_upload_routes.register_routes(core_bp)
evidence_routes.register_routes(core_bp)
process_docs_routes.register_routes(core_bp)
wastage_routes.register_routes(core_bp)
tasks.register_routes(core_bp)
process_design_routes.register_routes(core_bp)
inventory_routes.register_routes(
    core_bp,
    parse_page_params=_parse_page_params,
    encode_list_cursor=_encode_list_cursor,
    split_execution_data=_split_execution_data,
)
traceability_routes.register_routes(core_bp)
suppliers.register_routes(core_bp)
demo_data_routes.register_routes(core_bp)


@core_bp.route("/api/core/execution-metadata", methods=["GET"])
@requires_auth
def get_execution_metadata():
    """Get unique execution metadata values for search/tracing.
    Returns all unique key-value pairs from execution_data across all execution steps.
    """

    org_id = UUID(g.org_id)

    # Get all executions for this org
    execution_repo = ExecutionRepository(db_session)
    executions = execution_repo.list_executions(org_id)

    # Collect unique metadata key-value pairs
    metadata_map = {}  # key -> set of values
    metadata_items = []  # List of {key, value, execution_ids, inventory_item_ids}

    # Fields to exclude from metadata display
    exclude_fields = {"completed_by_email", "completed_by_user_id", "execution_errors"}

    # execution_steps is already joinedload'd by ExecutionRepository.list_executions
    # above, so every access below is in-memory, not a per-iteration query.
    for execution in executions:
        if not execution.execution_steps:  # nosemgrep: orm-relationship-access-in-loop
            continue
        for step in execution.execution_steps:  # nosemgrep: orm-relationship-access-in-loop
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
