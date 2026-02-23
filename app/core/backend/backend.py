"""Core backend API routes for process execution platform"""

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request, send_from_directory

from app.api.routes.auth_routes import limiter
from app.core.backend import corechecks, inventory_upload_routes, reconciliation_routes
from app.core.backend.reconciliation_service import _find_producing_step
from app.core.db import db_session
from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.process import ProcessCategory
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.wastage_repo import WastageRepository
from app.core.security.permissions import requires_auth
from app.core.utils.mock_data import DEMO_USER_EMAIL
from app.core.utils.unit_conversion import are_units_compatible, convert_to_inventory_unit_decimal
from app.utils.config_loader import config

# Create core blueprint
core_bp = Blueprint(
    "core",
    __name__,
    template_folder="../frontend",
    static_folder="../frontend",
    static_url_path="/static",
)


@core_bp.route("/core", methods=["GET"])
@requires_auth
def core():
    """Serve the core2.html frontend page"""
    user_email = getattr(g, "user_email", None)
    show_reset_db = config.environment in ("test", "local") and user_email == DEMO_USER_EMAIL
    return render_template("core2.html", active_page="core", show_reset_db=show_reset_db)


@core_bp.route("/core/flows", methods=["GET"])
@requires_auth
def flows():
    """Serve the flows2.html frontend page"""
    process_id = request.args.get("id")
    return render_template("flows2.html", active_page="core", process_id=process_id)


@core_bp.route("/core/flows/create", methods=["GET"])
@requires_auth
def flows_create():
    """Serve the process creation SPA (guided step flow as full page)."""
    process_id = request.args.get("id")
    return render_template("process-flow-spa.html", active_page="core", process_id=process_id)


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

    repo = ProcessRepository(db_session)
    step = repo.add_step(
        process_id=process_uuid,
        org_id=org_id,
        step_number=step_number,
        name=name,
        description=data.get("description"),
        inputs=data.get("inputs", []),
        outputs=data.get("outputs", []),
        execution_prompts=data.get("execution_prompts", []),
    )

    if not step:
        return jsonify({"error": "Process not found"}), 404

    return (
        jsonify(
            {
                "id": str(step.id),
                "step_number": step.step_number,
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
    repo = ProcessRepository(db_session)
    step = repo.update_step(
        step_id=step_uuid,
        process_id=process_uuid,
        org_id=org_id,
        step_number=data.get("step_number"),
        name=data.get("name"),
        description=data.get("description"),
        inputs=data.get("inputs"),
        outputs=data.get("outputs"),
        execution_prompts=data.get("execution_prompts"),
    )

    if not step:
        return jsonify({"error": "Step or process not found"}), 404

    return (
        jsonify(
            {
                "id": str(step.id),
                "step_number": step.step_number,
                "name": step.name,
                "description": step.description,
                "inputs": step.inputs or [],
                "outputs": step.outputs or [],
                "execution_prompts": step.execution_prompts or [],
            }
        ),
        200,
    )


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

    return (
        jsonify(
            {
                "id": str(execution.id),
                "process_id": str(execution.process_id),
                "status": execution.status.value,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                "execution_steps": execution_steps,
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

    data = request.get_json()
    actual_inputs = data.get("actual_inputs", [])
    actual_outputs = data.get("actual_outputs", [])
    execution_data = data.get("execution_data", {})

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
        # TRANSACTION INTEGRITY: Collect all inventory updates first, then commit atomically
        inventory_updates = []
        if actual_inputs:
            for input_data in actual_inputs:
                inventory_item_id = input_data.get("inventory_item_id")
                quantity_consumed = input_data.get("quantity", 0)
                consumed_unit = input_data.get("unit", "")

                if inventory_item_id:
                    try:
                        inventory_item = inventory_repo.get_inventory_item_by_id(UUID(inventory_item_id), org_id)
                        if not inventory_item:
                            execution_warnings.append(
                                f"Inventory item {inventory_item_id} not found for input '{input_data.get('name', 'Unknown')}'"
                            )
                            continue

                        # QUANTITY PRECISION: Use Decimal for safe arithmetic.
                        # TODO: Standardize all inventory quantity handling on Decimal; some paths still use float(quantity).
                        # Current usage here is arithmetic; elsewhere may be comparison-only. Do not refactor broadly yet.
                        try:
                            current_quantity = Decimal(str(inventory_item.quantity))
                        except (InvalidOperation, ValueError, TypeError):
                            execution_errors.append(
                                f"Invalid quantity format for inventory item {inventory_item_id}: {inventory_item.quantity}"
                            )
                            continue

                        inventory_unit = inventory_item.unit or ""

                        # Check if units are compatible
                        if consumed_unit and inventory_unit:
                            if not are_units_compatible(consumed_unit, inventory_unit):
                                execution_errors.append(
                                    f"Cannot consume {quantity_consumed} {consumed_unit} from inventory "
                                    f"item {inventory_item_id} (unit: {inventory_unit}): units are incompatible"
                                )
                                continue

                            # Convert consumed quantity to inventory unit (Decimal-only for precision)
                            try:
                                quantity_consumed_decimal = Decimal(str(quantity_consumed))
                                quantity_consumed_converted = convert_to_inventory_unit_decimal(
                                    quantity_consumed_decimal, consumed_unit, inventory_unit
                                )
                            except (ValueError, InvalidOperation) as conv_error:
                                execution_errors.append(
                                    f"Failed to convert {quantity_consumed} {consumed_unit} to {inventory_unit}: {conv_error}"
                                )
                                continue
                        else:
                            # If no unit specified, assume same unit (backward compatibility)
                            try:
                                quantity_consumed_converted = Decimal(str(quantity_consumed))
                            except (InvalidOperation, ValueError, TypeError):
                                execution_errors.append(
                                    f"Invalid quantity format for input '{input_data.get('name', 'Unknown')}': {quantity_consumed}"
                                )
                                continue

                        # Decrease inventory quantity using Decimal arithmetic
                        new_quantity = max(Decimal("0"), current_quantity - quantity_consumed_converted)

                        # Format quantity deterministically (audit-safe)
                        # Always set to exactly "0" string if quantity is effectively zero
                        if abs(new_quantity) < Decimal("0.0001"):
                            formatted_qty = "0"
                        else:
                            # Format to remove unnecessary trailing zeros while preserving precision
                            formatted_qty = str(new_quantity.normalize())
                            # Remove trailing .0 if present
                            if formatted_qty.endswith(".0"):
                                formatted_qty = formatted_qty[:-2]

                        # Store update for atomic commit
                        inventory_updates.append((inventory_item, formatted_qty))

                    except Exception as e:
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.exception(f"Unexpected error consuming inventory {inventory_item_id}")
                        execution_errors.append(f"Failed to consume inventory {inventory_item_id}: {str(e)}")

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
                # - variable_inputs: Source data from execution_step.actual_inputs (what was consumed)
                # - variable_output: Source data from execution_step.actual_outputs (this specific output)
                # NOTE: previous_steps_data is derived/read-only and should NEVER be persisted here
                extra_data = {}
                # Get execution_data from the execution_step (read from DB after refresh)
                step_execution_data = execution_step.execution_data if execution_step.execution_data else {}
                if step_execution_data:
                    # Store execution prompts (metadata captured during execution)
                    # Keep completed_by for user tracing, but filter out email and user_id
                    execution_prompts = {}
                    internal_fields = {
                        "completed_by_email",
                        "completed_by_user_id",
                        "completed_at",
                        "execution_errors",
                        "execution_warnings",
                    }
                    for key, value in step_execution_data.items():
                        if key not in internal_fields and value is not None and value != "":
                            execution_prompts[key] = value
                    if execution_prompts:
                        extra_data["execution_prompts"] = execution_prompts

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
                output_creations.append(
                    {
                        "org_id": org_id,
                        "name": output_name,
                        "quantity": str(quantity_decimal),  # Convert Decimal to string for storage
                        "unit": output.get("unit", "units"),
                        "inventory_type": inventory_type,
                        "source_execution_id": execution_uuid,
                        "source_execution_step_id": execution_step_uuid,
                        "source_step_name": execution_step.step.name if execution_step.step else None,
                        "extra_data": extra_data if extra_data else None,
                        "untracked_item_id": untracked_item_id_uuid,
                        "quantity_decimal": quantity_decimal,
                    }
                )

        # FAILURE HANDLING: Persist warnings to execution_data for audit trail
        if execution_warnings:
            if not execution_step.execution_data:
                execution_step.execution_data = {}
            execution_step.execution_data["execution_warnings"] = execution_warnings

        # TRANSACTION INTEGRITY: Commit all inventory operations atomically
        # This ensures inventory consumption and output creation are atomic per execution step
        try:
            # Apply inventory updates
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
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        # Log the full error for debugging but return generic message to client
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Error creating process")
        return jsonify({"error": "Failed to create process"}), 500


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
            qty_str = str(item.quantity).strip() if item.quantity else "0"
            quantity_decimal = Decimal(qty_str)
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
                    # Build execution_prompts from execution_data, keeping completed_by for tracing
                    execution_prompts = {}
                    internal_fields = {"completed_by_email", "completed_by_user_id", "completed_at"}
                    for key, value in execution_step.execution_data.items():
                        if key not in internal_fields and value is not None and value != "":
                            execution_prompts[key] = value
                    if execution_prompts:
                        extra_data["execution_prompts"] = execution_prompts

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

                    # Add execution prompts from this step
                    if input_execution_step.execution_data:
                        prev_execution_prompts = {}
                        # Exclude internal fields and completed_by (we display it separately)
                        internal_fields = {
                            "completed_by",
                            "completed_by_email",
                            "completed_by_user_id",
                            "completed_at",
                        }
                        for key, value in input_execution_step.execution_data.items():
                            if key not in internal_fields and value is not None and value != "":
                                prev_execution_prompts[key] = value
                        if prev_execution_prompts:
                            step_data["execution_prompts"] = prev_execution_prompts
                        # Include completed_by for tracing (displayed separately)
                        if "completed_by" in input_execution_step.execution_data:
                            step_data["completed_by"] = input_execution_step.execution_data["completed_by"]

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
                "quantity": item.quantity,
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
                "process_name": process_name,
                "producing_step_id": str(producing_step_id) if producing_step_id else None,
                "producing_step_name": producing_step_name,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "extra_data": extra_data,
                "system_findings": findings_by_id.get(str(item.id), []),
            }
        )

    return jsonify({"inventory_items": result}), 200


@core_bp.route("/api/core/inventory/wastage", methods=["POST"])
@requires_auth
def record_wastage():
    """Record wastage for one or more inventory items. Deducts quantity; items at zero disappear from list."""
    org_id = UUID(g.org_id)
    data = request.get_json() or {}
    entries = data.get("entries")
    if not entries or not isinstance(entries, list):
        return jsonify({"error": "entries (array of {inventory_item_id, quantity_wasted}) required"}), 400

    inventory_repo = InventoryRepository(db_session)
    recorded_by = getattr(g, "user_email", None) or getattr(g, "username", None)

    result_records = []
    errors = []

    for idx, entry in enumerate(entries):
        item_id_str = entry.get("inventory_item_id")
        qty_wasted = entry.get("quantity_wasted")
        if not item_id_str:
            errors.append(f"Entry {idx + 1}: inventory_item_id required")
            continue
        try:
            item_id = UUID(item_id_str)
        except (ValueError, TypeError):
            errors.append(f"Entry {idx + 1}: invalid inventory_item_id")
            continue
        item = inventory_repo.get_inventory_item_by_id(item_id, org_id)
        if not item:
            errors.append(f"Entry {idx + 1}: inventory item not found or access denied")
            continue
        try:
            current_str = str(item.quantity).strip() if item.quantity else "0"
            current_qty = Decimal(current_str)
        except (InvalidOperation, ValueError, TypeError):
            errors.append(f"Entry {idx + 1}: invalid current quantity for item")
            continue
        try:
            waste_decimal = Decimal(str(qty_wasted)).quantize(Decimal("0.0001"))
        except (InvalidOperation, ValueError, TypeError):
            errors.append(f"Entry {idx + 1}: quantity_wasted must be a number")
            continue
        if waste_decimal <= 0:
            errors.append(f"Entry {idx + 1}: quantity_wasted must be positive")
            continue
        actual_waste = min(waste_decimal, current_qty)
        if actual_waste <= 0:
            errors.append(f"Entry {idx + 1}: item has no quantity to waste")
            continue
        new_qty = current_qty - actual_waste
        if new_qty < 0:
            new_qty = Decimal("0")
        new_qty_str = str(new_qty.quantize(Decimal("0.0001"))).rstrip("0").rstrip(".")
        if new_qty_str == "" or new_qty_str == "-":
            new_qty_str = "0"
        unit = (item.unit or "units").strip() or "units"
        try:
            item.quantity = new_qty_str
            record = InventoryWastage(
                org_id=org_id,
                inventory_item_id=item.id,
                quantity_wasted=str(actual_waste),
                unit=unit,
                recorded_by=recorded_by,
            )
            db_session.add(record)
            db_session.flush()
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
        except Exception as e:
            db_session.rollback()
            return jsonify({"error": "Failed to record wastage", "details": str(e)}), 500

    if errors and not result_records:
        return jsonify({"error": "Validation failed", "details": errors}), 400
    try:
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": "Failed to save wastage", "details": str(e)}), 500
    return jsonify({"wastage_records": result_records, "errors": errors}), 201


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
        # Only include items with exactly zero quantity
        try:
            qty_str = str(item.quantity).strip() if item.quantity else "0"
            quantity_decimal = Decimal(qty_str)
            # Only include items with exactly zero quantity
            if quantity_decimal != Decimal("0"):
                continue  # Skip items with any stock remaining
        except (InvalidOperation, ValueError, TypeError):
            continue

        result.append(
            {
                "id": str(item.id),
                "name": item.name,
                "quantity": item.quantity,
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
    """Create a new inventory item (typically raw material)"""
    org_id = UUID(g.org_id)
    data = request.get_json()

    name = data.get("name")
    quantity = data.get("quantity")
    unit = data.get("unit")
    inventory_type = data.get("inventory_type", InventoryType.RAW_MATERIAL.value)

    if not all([name, quantity, unit]):
        return jsonify({"error": "name, quantity, and unit are required"}), 400
    try:
        qty_val = float(quantity)
        if qty_val <= 0:
            return jsonify({"error": "quantity must be greater than 0"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be a valid number"}), 400

    repo = InventoryRepository(db_session)
    try:
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

        item = repo.create_inventory_item(
            org_id=org_id,
            name=name,
            quantity=str(quantity),
            unit=unit,
            inventory_type=inventory_type,
            supplier=data.get("supplier"),
            purchase_date=purchase_date,
            supplier_batch_number=data.get("supplier_batch_number"),
            expiry_date=expiry_date,
            source_execution_id=source_execution_id,
            source_execution_step_id=source_execution_step_id,
            source_output_id=source_output_id,
            extra_data=extra_data if extra_data else None,
        )

        return (
            jsonify(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "quantity": item.quantity,
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
        item.quantity = str(quantity)
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
                    "quantity": item.quantity,
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
        "quantity": raw_material.quantity,
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
            "quantity": traced_item.quantity,
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
