"""Process design and flow-wizard routes. Register with register_routes(core_bp)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from flask import abort, g, jsonify, redirect, render_template, request, session
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal, db_session
from app.core.db.models.entity_event_summary import EntityEventSummary
from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.process import ProcessCategory
from app.core.db.models.step import Step
from app.core.db.models.user import UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.process_repo import STALE_WRITE, ProcessRepository
from app.core.domain.expiry_ready_date_rules import assert_expiry_after_ready_duration
from app.core.security.permissions import requires_auth, requires_role
from app.observability import get_logger

logger = get_logger(__name__)

_PROCESS_SETTINGS_KEYS = {"fifo_auto_select", "library_stock_name"}  # library: plan 1.2


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


def _log_process_access_denied(org_id: UUID, process_id: UUID) -> None:
    """A rejected org-scoped process lookup is a tenant-boundary probe (or a stale link);
    the route turns it into a generic 404, so without this it leaves no trace at all.
    Same `access_denied` event name as permissions.py/inventory_repo.py so one query covers all three.
    """
    logger.warning(
        "access_denied",
        reason="process_not_found_or_cross_org",
        feature="process-design",
        org_id=str(org_id),
        process_id=str(process_id),
        path=request.path,
    )


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
        _log_process_access_denied(org_id, process_id)
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
        _log_process_access_denied(org_id, process_id)
        abort(404)
    return proc


def _is_valid_step_position(pos) -> bool:
    """Pure grid-validity check, shared by `_coerce_step_position` (which aborts) and
    `reorder_steps` (which needs a plain bool since it can't call `abort()` from inside
    a `with sess.begin():` block without triggering a partial commit — see reorder_steps).
    """
    from decimal import Decimal

    # Defensive bounds: reject NaN/Inf and negative/zero positions.
    if not pos.is_finite() or pos <= 0:
        return False
    # Guard against pathological magnitudes (prevents log spam / abuse).
    if pos.copy_abs() > Decimal("1e30"):
        return False
    # Hard invariant: always store positions on the 1000-grid.
    if (pos % Decimal("1000")) != 0:
        return False
    return True


def _coerce_step_position(value):
    if value is None:
        return None
    from decimal import Decimal

    try:
        pos = Decimal(str(value))
    except Exception:
        abort(400)
    if not _is_valid_step_position(pos):
        abort(400)
    return pos


def _next_step_position(process_id: UUID) -> Decimal:
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


def _iso(dt):
    return dt.isoformat() if dt else None


def _serialize_step(step) -> dict:
    return {
        "id": str(step.id),
        "step_number": step.step_number,
        "position": str(step.position) if getattr(step, "position", None) is not None else None,
        "name": step.name,
        "description": step.description,
        "inputs": step.inputs or [],
        "outputs": step.outputs or [],
        "execution_prompts": step.execution_prompts or [],
        "updated_at": _iso(getattr(step, "updated_at", None)),
    }


def _validate_process_settings(raw: Any) -> tuple[dict, str | None]:
    """`({}, None)` when absent; `(cleaned, None)` when valid; `({}, error)` otherwise."""
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return {}, "settings must be an object"
    unknown = sorted(set(raw) - _PROCESS_SETTINGS_KEYS)
    if unknown:
        return {}, f"settings: unknown key(s) {', '.join(unknown)}"
    if "fifo_auto_select" in raw and not isinstance(raw["fifo_auto_select"], bool):
        return {}, "settings.fifo_auto_select must be true or false"
    if "library_stock_name" in raw and not (0 < len(str(raw["library_stock_name"] or "").strip()) <= 60):
        return {}, "settings.library_stock_name must be 1-60 characters"
    return raw, None


def _serialize_process(process, *, with_steps: bool = False) -> dict:
    out = {
        "id": str(process.id),
        "name": process.name,
        "description": process.description,
        "category": process.category.value if process.category else None,
        "is_draft": process.is_draft,
        "settings": process.settings or {},
        "created_at": _iso(getattr(process, "created_at", None)),
        "updated_at": _iso(getattr(process, "updated_at", None)),
    }
    if with_steps:
        out["steps"] = [_serialize_step(s) for s in process.steps]
    return out


def _if_match_token() -> str | None:
    """The request's If-Match token, normalised (trimmed, optional surrounding quotes
    removed), or ``None`` when the header is absent/empty.

    Opt-in optimistic concurrency: no header -> ``None`` -> the repo keeps the old
    last-write-wins behaviour. When present, the token is handed to the repo write
    method, which locks the row and re-compares it to ``updated_at`` *in the same
    transaction as the write* -- so two concurrent writers can't both pass the check.
    (The previous helper compared here, before any lock, then the route wrote later.)
    """
    want = request.headers.get("If-Match")
    if not want:
        return None
    return want.strip().strip('"')


def _stale_write_response(current_entity: dict):
    """The 409 body the client shows when its If-Match token was stale: the error marker
    plus the *current* server state to re-render."""
    return jsonify(
        {
            "error": "stale_write",
            "message": "This was changed by someone else. Showing the latest.",
            "current": current_entity,
        }
    ), 409


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


def register_routes(bp):
    """Register process-design routes on the given blueprint, preserving endpoints."""

    @bp.route("/core/flows", methods=["GET"])
    @requires_auth
    def flows():
        """Serve the process workspace page (processes/flows2.html)."""
        process_id = _flow_process_id_from_request()
        if process_id is not None:
            _assert_flow_process_access(process_id)
        return render_template("processes/flows2.html", active_page="core", process_id=process_id)

    @bp.route("/core/flows/create/start", methods=["GET"])
    @requires_auth
    def flows_create_start_chooser():
        """Two-choice entry point (process_templates feature): Start from scratch / Start
        from a template. This is a new page, not a change to `flows_create` below — that
        route is the wizard's own long-established entry/reset point and several existing
        e2e tests (test_process_wizard_flow.py) treat a bare `GET /core/flows/create` as an
        unconditional redirect straight to process-overview; branching that route on the
        chooser broke those. The two real "Create process" UI links (processes/list.html,
        core/core2.html) point here instead; "Start from scratch" here links straight to
        the unmodified `/core/flows/create` below, and "Start from a template" links to
        process_templates' own catalogue page.
        """
        return render_template("processes/flow-create-chooser.html", active_page="core")

    @bp.route("/core/flows/create", methods=["GET"])
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

    @bp.route("/core/flows/create/step/<int:step>", methods=["GET"])
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

    @bp.route("/core/flows/create/process-overview", methods=["GET"])
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

    @bp.route("/core/flows/create/step-name", methods=["GET"])
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

    @bp.route("/core/flows/create/inputs", methods=["GET"])
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

    @bp.route("/core/flows/create/outputs", methods=["GET"])
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

    @bp.route("/core/flows/create/evidence-and-prompts", methods=["GET"])
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

    @bp.route("/core/flows/create/summary", methods=["GET"])
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

    @bp.route("/core/flows/create/next-steps", methods=["GET"])
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

    @bp.route("/core/processes", methods=["GET"])
    @requires_auth
    def processes_list_page():
        """SPA list of all processes; links open flows2 for each process."""
        return render_template("processes/list.html", active_page="core")

    @bp.route("/api/core/processes", methods=["GET"])
    @requires_auth
    def list_processes():
        """List all processes for the current organisation"""
        org_id = UUID(g.org_id)
        include_steps = request.args.get("include_steps", "false").lower() == "true"
        repo = ProcessRepository(db_session)
        processes = repo.list_processes(org_id)

        # Active/completed counts per process from one GROUP BY -- not by loading every org
        # execution (with joined steps) into Python, which scales with execution history.

        execution_repo = ExecutionRepository(db_session)
        counts_by_process = execution_repo.count_by_process_and_status(org_id)

        # Batch-load process event summaries

        proc_ids_all = [p.id for p in processes]
        proc_summary_by_id: dict = {}
        if proc_ids_all:
            proc_ees = db_session.query(EntityEventSummary).filter(EntityEventSummary.entity_id.in_(proc_ids_all)).all()
            proc_summary_by_id = {str(r.entity_id): r.summary for r in proc_ees}

        # Batch-fetch all steps for the org's processes once, then group by process_id in
        # Python. `process.steps` is a lazy relationship — accessing it per-process below
        # would be one SELECT per process (N+1); this replaces that with a single query.
        steps_by_process: dict = defaultdict(list)
        if proc_ids_all:
            all_steps = (
                db_session.query(Step)
                .filter(Step.process_id.in_(proc_ids_all))
                .order_by(Step.position, Step.step_number)
                .all()
            )
            for s in all_steps:
                steps_by_process[s.process_id].append(s)

        result = []
        for process in processes:
            proc_counts = counts_by_process.get(process.id, {})
            active_count = proc_counts.get(ExecutionStatus.IN_PROGRESS.value, 0)
            completed_count = proc_counts.get(ExecutionStatus.COMPLETED.value, 0)
            step_list = steps_by_process.get(process.id, [])
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

    @bp.route("/api/core/processes", methods=["POST"])
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
        settings, settings_error = _validate_process_settings(data.get("settings"))
        if settings_error:
            return jsonify({"error": settings_error}), 400

        repo = ProcessRepository(db_session)
        try:
            process = repo.create_process(
                org_id=org_id,
                name=name,
                description=description,
                category=category,
                is_draft=is_draft,
                settings=settings,
            )
            return jsonify(_serialize_process(process)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception:
            # Log the full error for debugging but return generic message to client
            logger.exception("Error creating process")
            return jsonify({"error": "Failed to create process"}), 500

    @bp.route("/api/core/processes/<process_id>", methods=["PUT"])
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
        settings, settings_error = _validate_process_settings(data.get("settings"))
        if settings_error:
            return jsonify({"error": settings_error}), 400

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
                settings=settings or None,
                if_match=_if_match_token(),
            )

            if process == STALE_WRITE:
                db_session.rollback()  # release the FOR UPDATE lock the failed check took
                current = repo.get_process_by_id(process_uuid, org_id)
                if not current:
                    return jsonify({"error": "Process not found"}), 404
                return _stale_write_response(_serialize_process(current))

            if not process:
                return jsonify({"error": "Process not found"}), 404

            return jsonify(_serialize_process(process)), 200
        except Exception:
            # Log the full error for debugging but return generic message to client
            logger.exception("Error updating process")
            return jsonify({"error": "Failed to update process"}), 500

    @bp.route("/api/core/processes/<process_id>", methods=["DELETE"])
    @requires_auth
    @requires_role(UserRole.ADMIN)
    def delete_process(process_id: str):
        """Delete a process.

        ADMIN-gated: cascades to delete every step and the entire ProcessVersion history
        for this process (DB ON DELETE CASCADE), a strictly more destructive blast radius
        than the single-file DELETE /api/core/process-docs/<doc_id>, which was already
        ADMIN-gated — this closes that asymmetry (security-audit F3, review-feature
        process-design audit, 2026-08-02).
        """
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
            logger.exception("Error deleting process")
            return jsonify({"error": "Failed to delete process"}), 500

    @bp.route("/api/core/processes/<process_id>", methods=["GET"])
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

        return jsonify(_serialize_process(process, with_steps=True)), 200

    @bp.route("/api/core/processes/<process_id>/steps", methods=["POST"])
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

    @bp.route("/api/core/processes/<process_id>/steps/<step_id>", methods=["PUT"])
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
                if_match=_if_match_token(),
            )
        except IntegrityError:
            db_session.rollback()
            return jsonify({"error": "Could not update step"}), 409

        if step == STALE_WRITE:
            db_session.rollback()  # release the FOR UPDATE lock the failed check took
            owning = repo.get_process_with_steps(process_uuid, org_id)
            current_step = next((s for s in owning.steps if s.id == step_uuid), None) if owning else None
            if not current_step:
                return jsonify({"error": "Step or process not found"}), 404
            return _stale_write_response(_serialize_step(current_step))

        if not step:
            return jsonify({"error": "Step or process not found"}), 404

        return (
            jsonify(_serialize_step(step)),
            200,
        )

    @bp.route("/api/core/processes/<process_id>/steps/reorder", methods=["POST"])
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
            if not _is_valid_step_position(position):
                return jsonify(
                    {"error": f"Invalid position: must be a positive, finite multiple of 1000 (got {pos!r})"}
                ), 400
            updates.append((step_uuid, position))

        # Optimistic concurrency: a reorder bumps each moved step's updated_at, so the newest
        # step updated_at across the process is the structural-version token -- it advances on
        # any reorder or step edit, which is exactly the staleness a reordering client cares
        # about. Opt-in via If-Match; absent header = unchanged behaviour. The token is
        # compared inside reorder_steps() *after* it takes the FOR UPDATE lock, in the same
        # write transaction -- not here on the request session before the write, which let two
        # racing reorders both pass and the last commit silently win.
        if_match = _if_match_token()

        # Use an isolated session for this write endpoint.
        # The app's before_request tenant middleware uses the scoped_session for reads and can leave
        # an open transaction on it; using a fresh SessionLocal avoids nested-transaction surprises
        # and ensures the commit persists.
        sess = SessionLocal()
        try:
            with sess.begin():
                repo = ProcessRepository(sess)
                error_code = repo.reorder_steps(process_uuid, org_id, updates, if_match=if_match)

            if error_code == "process_not_found":
                _log_process_access_denied(org_id, process_uuid)
                return jsonify({"error": "Process not found"}), 404
            if error_code == STALE_WRITE:
                current = ProcessRepository(db_session).get_process_with_steps(process_uuid, org_id)
                if not current:
                    return jsonify({"error": "Process not found"}), 404
                return _stale_write_response(_serialize_process(current, with_steps=True))
            if error_code == "no_steps":
                return jsonify({"error": "No steps to reorder"}), 400
            if error_code == "step_not_found":
                logger.warning(
                    "access_denied",
                    reason="step_not_in_process",
                    feature="process-design",
                    org_id=str(org_id),
                    process_id=str(process_uuid),
                    step_ids=[str(u) for u, _ in updates],
                    path=request.path,
                )
                return jsonify({"error": "Step not found"}), 404

            return jsonify({"message": "Reordered"}), 200
        except Exception as e:
            try:
                sess.rollback()
            except Exception:
                db_session.rollback()
            logger.exception("Failed to reorder steps process_id=%s", process_id)
            return jsonify({"error": "Failed to reorder steps", "details": str(e)}), 500
        finally:
            sess.close()

    @bp.route("/api/core/processes/<process_id>/steps/<step_id>", methods=["DELETE"])
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
