"""Core backend API routes for process execution platform"""

import base64
import functools
import hashlib
import os
from datetime import UTC, datetime, timedelta
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

from app.api.routes.auth_routes import limiter
from app.core.backend import (
    changes_feed,
    execution_routes,
    inventory_routes,
    inventory_upload_routes,
    process_design_routes,
    suppliers,
    tasks,
    traceability_routes,
)
from app.core.backend.evidence import evidence_routes
from app.core.backend.process_docs import process_docs_routes
from app.core.backend.static_assets import core_asset_directory, iter_core_assets
from app.core.db import db_session
from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.inventory_item import InventoryType
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.domain.expiry_rules import assert_warning_within_expiry
from app.core.security.permissions import requires_auth
from app.features.activity_log.routes import activity_routes
from app.features.compliance_checks.routes import corechecks
from app.features.dashboard.routes import dashboard_routes
from app.features.demo_data.routes import api_routes as demo_data_routes
from app.features.demo_data.services.resetdb import DEMO_USER_EMAIL
from app.features.reconciliation.routes import reconciliation_routes
from app.features.wastage.routes import wastage_routes
from app.observability import get_logger
from app.utils.config_loader import config

logger = get_logger(__name__)
_EXECUTION_DATA_TRACE_KEYS = execution_routes._EXECUTION_DATA_TRACE_KEYS


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
