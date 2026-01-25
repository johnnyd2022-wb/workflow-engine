"""Core backend API routes for process execution platform"""

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request, send_from_directory

from app.api.routes.auth_routes import limiter
from app.core.db import db_session
from app.core.db.models.execution import ExecutionStatus
from app.core.db.models.inventory_item import InventoryType
from app.core.db.models.process import ProcessCategory
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.security.permissions import requires_auth
from app.core.utils.mock_data import (
    get_mock_executions,
    get_mock_inventory,
    get_mock_metrics,
    get_mock_process,
    get_mock_processes,
    is_demo_user,
)
from app.core.utils.unit_conversion import are_units_compatible, convert_to_inventory_unit

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
    return render_template("core2.html", active_page="core")


@core_bp.route("/core/flows", methods=["GET"])
@requires_auth
def flows():
    """Serve the flows2.html frontend page"""
    process_id = request.args.get("id")
    return render_template("flows2.html", active_page="core", process_id=process_id)


@core_bp.route("/core/sitemap", methods=["GET"])
@requires_auth
def sitemap():
    """Serve the sitemap.html frontend page"""
    return render_template("sitemap.html", active_page="core")


@core_bp.route("/static/js/<filename>")
@limiter.limit("10000 per minute")  # Very high limit to effectively exempt from rate limiting
@requires_auth
def serve_core_js(filename):
    """Serve JavaScript files from core frontend - requires authentication"""
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
@limiter.limit("10000 per minute")  # Very high limit to effectively exempt from rate limiting
@requires_auth
def serve_core_css(filename):
    """Serve CSS files from core frontend - requires authentication"""
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
    # Check if demo user - return mock data
    user_email = getattr(g, "user_email", None)
    if is_demo_user(user_email):
        mock_processes = get_mock_processes()
        result = []
        for process in mock_processes:
            result.append(
                {
                    "id": process["id"],
                    "name": process["name"],
                    "description": process["description"],
                    "category": process["category"],
                    "step_count": len(process["steps"]),
                    "active_executions": process["active_executions"],
                    "completed_executions": process["completed_executions"],
                    "created_at": process["created_at"],
                }
            )
        return jsonify({"processes": result}), 200

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
    # Check if demo user - return mock data
    user_email = getattr(g, "user_email", None)
    if is_demo_user(user_email):
        mock_process = get_mock_process(process_id)
        if not mock_process:
            return jsonify({"error": "Process not found"}), 404

        steps = []
        for step in mock_process["steps"]:
            steps.append(
                {
                    "id": step["id"],
                    "step_number": step["step_number"],
                    "name": step["name"],
                    "description": step["description"],
                    "inputs": step["inputs"],
                    "outputs": step["outputs"],
                }
            )

        return (
            jsonify(
                {
                    "id": mock_process["id"],
                    "name": mock_process["name"],
                    "description": mock_process["description"],
                    "category": mock_process["category"],
                    "is_draft": mock_process.get("is_draft", False),
                    "steps": steps,
                    "created_at": mock_process["created_at"],
                }
            ),
            200,
        )

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
    # Check if demo user - return mock data
    user_email = getattr(g, "user_email", None)
    if is_demo_user(user_email):
        process_id_str = request.args.get("process_id")
        status_str = request.args.get("status")

        mock_executions = get_mock_executions(process_id_str if process_id_str else None)

        # Filter by status if provided
        if status_str:
            status_map = {
                "in_progress": "in_progress",
                "completed": "completed",
                "IN_PROGRESS": "in_progress",
                "COMPLETED": "completed",
            }
            target_status = status_map.get(status_str, status_str.lower())
            mock_executions = [e for e in mock_executions if e["status"] == target_status]

        return jsonify({"executions": mock_executions}), 200

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
        current_step = None
        ready_steps = [es for es in execution_steps if es.status.value == "ready"]
        completed_steps = [es for es in execution_steps if es.status.value == "completed"]

        if ready_steps:
            next_step = ready_steps[0]
            current_step = {
                "step_number": next_step.step_number,
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

                        # QUANTITY PRECISION: Use Decimal for safe arithmetic
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

                            # Convert consumed quantity to inventory unit
                            try:
                                quantity_consumed_decimal = Decimal(str(quantity_consumed))
                                quantity_consumed_converted = Decimal(
                                    str(
                                        convert_to_inventory_unit(
                                            float(quantity_consumed_decimal), consumed_unit, inventory_unit
                                        )
                                    )
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

            # Create inventory items for outputs
            for output_params in output_creations:
                inventory_repo.create_inventory_item(**output_params)

            # Single commit for all inventory operations
            db_session.commit()
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.exception("Failed to commit inventory operations atomically")
            db_session.rollback()
            return jsonify({"error": "Failed to update inventory", "details": str(e)}), 500

        return (
            jsonify(
                {
                    "id": str(execution_step.id),
                    "status": execution_step.status.value,
                    "completed_at": execution_step.completed_at.isoformat() if execution_step.completed_at else None,
                }
            ),
            200,
        )
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
    # Check if demo user - return mock data
    user_email = getattr(g, "user_email", None)
    if is_demo_user(user_email):
        inventory_type = request.args.get("type")
        mock_items = get_mock_inventory(inventory_type=inventory_type)
        return jsonify({"inventory_items": mock_items}), 200

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
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "extra_data": extra_data,
            }
        )

    return jsonify({"inventory_items": result}), 200


@core_bp.route("/api/core/inventory/out-of-stock", methods=["GET"])
@requires_auth
def list_out_of_stock_raw_materials():
    """List raw materials with zero quantity for recall/traceability purposes.

    Returns raw materials that have been fully consumed (quantity = 0) but may still
    need to be traced for supplier recall scenarios.
    """
    user_email = getattr(g, "user_email", None)
    if is_demo_user(user_email):
        return jsonify({"inventory_items": []}), 200

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

    repo = InventoryRepository(db_session)
    try:
        # Parse purchase date if provided
        purchase_date = None
        if data.get("purchase_date"):
            purchase_date = datetime.fromisoformat(data.get("purchase_date").replace("Z", "+00:00")).date()

        expiry_date = None
        if data.get("expiry_date"):
            expiry_date = datetime.fromisoformat(data.get("expiry_date").replace("Z", "+00:00")).date()

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
            extra_data=data.get("metadata", {}),  # Frontend sends 'metadata', we store as 'extra_data'
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
    org_id = UUID(g.org_id)
    try:
        raw_material_uuid = UUID(raw_material_id)
    except ValueError:
        return jsonify({"error": "Invalid raw material ID"}), 400

    # Import models
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.process import Process

    # Get the raw material
    raw_material = (
        db_session.query(InventoryItem)
        .filter(InventoryItem.id == raw_material_uuid, InventoryItem.org_id == org_id)
        .first()
    )

    if not raw_material:
        return jsonify({"error": "Raw material not found"}), 404

    # Helper function to trace forward from an inventory item
    def trace_forward(inventory_item_id, visited_step_ids=None, depth=0):
        """Recursively trace forward through execution steps to find connected inventory items

        Args:
            inventory_item_id: UUID of inventory item to trace from
            visited_step_ids: Set of visited execution step IDs to prevent cycles
            depth: Current recursion depth (for safety limits)

        Returns:
            Set of inventory item IDs that are connected
        """
        max_dag_depth = 50
        if depth > max_dag_depth:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"DAG forward traversal depth limit ({max_dag_depth}) reached")
            return set()

        if visited_step_ids is None:
            visited_step_ids = set()

        connected_items = set()

        # Find all execution steps that use this inventory item as input
        # Filter by org_id through the execution relationship
        from app.core.db.models.execution import Execution

        all_execution_steps = (
            db_session.query(ExecutionStep)
            .join(Execution, ExecutionStep.execution_id == Execution.id)
            .filter(Execution.org_id == org_id)
            .all()
        )
        steps_using_item = []

        for step in all_execution_steps:
            if step.id in visited_step_ids:
                continue
            if not step.actual_inputs:
                continue

            # Check if this step uses the inventory item
            uses_item = False
            for input_data in step.actual_inputs:
                input_item_id = input_data.get("inventory_item_id")
                if input_item_id and str(input_item_id) == str(inventory_item_id):
                    uses_item = True
                    break
                # Also check by name (for backward compatibility)
                input_name = input_data.get("name")
                if input_name:
                    # Convert inventory_item_id to UUID if it's a string
                    item_id_uuid = UUID(inventory_item_id) if isinstance(inventory_item_id, str) else inventory_item_id
                    item = (
                        db_session.query(InventoryItem)
                        .filter(InventoryItem.id == item_id_uuid)
                        .filter(InventoryItem.org_id == org_id)
                        .first()
                    )
                    if item and input_name.lower() == item.name.lower():
                        uses_item = True
                        break

            if uses_item:
                steps_using_item.append(step)
                visited_step_ids.add(step.id)

        # For each step that uses this item, find all inventory items it produces
        for step in steps_using_item:
            # Find all inventory items produced by this step
            # Don't filter by quantity here - we want to trace through all items
            # Filtering happens later when building the response
            produced_items = (
                db_session.query(InventoryItem)
                .filter(InventoryItem.source_execution_step_id == step.id, InventoryItem.org_id == org_id)
                .all()
            )

            for produced_item in produced_items:
                connected_items.add(produced_item.id)
                # Recursively trace forward from this produced item
                next_items = trace_forward(produced_item.id, visited_step_ids, depth + 1)
                connected_items.update(next_items)

        return connected_items

    # Trace forward from the raw material
    connected_item_ids = trace_forward(raw_material_uuid)

    # Helper function to trace backwards from an inventory item to find raw materials
    # This ensures we get direct connections based on execution_id
    def trace_backward(inventory_item_id, visited_item_ids=None, depth=0):
        """Recursively trace backwards through execution steps to find raw materials

        Args:
            inventory_item_id: UUID of inventory item to trace from
            visited_item_ids: Set of visited inventory item IDs to prevent cycles
            depth: Current recursion depth (for safety limits)

        Returns:
            Set of raw material IDs that this item traces back to
        """
        max_dag_depth = 50
        if depth > max_dag_depth:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"DAG backward traversal depth limit ({max_dag_depth}) reached")
            return set()

        if visited_item_ids is None:
            visited_item_ids = set()

        # Convert to string for set comparison
        item_id_str = str(inventory_item_id)
        if item_id_str in visited_item_ids:
            return set()  # Cycle detected
        visited_item_ids.add(item_id_str)

        raw_material_ids = set()

        # Get the inventory item - convert to UUID if needed
        item_id_uuid = UUID(inventory_item_id) if isinstance(inventory_item_id, str) else inventory_item_id
        item = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id == item_id_uuid)
            .filter(InventoryItem.org_id == org_id)
            .first()
        )

        if not item or not item.source_execution_step_id:
            return raw_material_ids

        # If this is a raw material, return it
        if item.inventory_type == InventoryType.RAW_MATERIAL.value:
            raw_material_ids.add(item.id)
            return raw_material_ids

        # Get the execution step that produced this item
        execution_step = (
            db_session.query(ExecutionStep).filter(ExecutionStep.id == item.source_execution_step_id).first()
        )

        if not execution_step or not execution_step.actual_inputs:
            return raw_material_ids

        # Check each input to see if it's a raw material or needs further tracing
        for input_data in execution_step.actual_inputs:
            input_item_id = input_data.get("inventory_item_id")
            if not input_item_id:
                continue

            # Get the input inventory item - convert to UUID if needed
            input_item_id_uuid = UUID(input_item_id) if isinstance(input_item_id, str) else input_item_id
            input_item = (
                db_session.query(InventoryItem)
                .filter(InventoryItem.id == input_item_id_uuid)
                .filter(InventoryItem.org_id == org_id)
                .first()
            )

            if not input_item:
                continue

            # If it's a raw material, add it
            if input_item.inventory_type == InventoryType.RAW_MATERIAL.value:
                raw_material_ids.add(input_item.id)
            else:
                # Recursively trace backwards from this intermediate
                prev_raw_materials = trace_backward(input_item.id, visited_item_ids, depth + 1)
                raw_material_ids.update(prev_raw_materials)

        return raw_material_ids

    # Build connection map: for each connected item, find which raw materials it traces back to
    # Only include connections where the raw material matches our traced raw material
    connections = []  # List of {from_id, to_id, execution_id} tuples

    # Get all connected inventory items
    connected_items = []
    if connected_item_ids:
        items = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id.in_(connected_item_ids), InventoryItem.org_id == org_id)
            .all()
        )

        for item in items:
            # Filter: only include items with quantity > 0, OR the raw material itself (for traceability)
            try:
                qty_str = str(item.quantity).strip() if item.quantity else "0"
                quantity_decimal = Decimal(qty_str)
                # Include if quantity > 0, or if it's the raw material itself (for consumed traceability)
                if quantity_decimal > 0 or item.id == raw_material_uuid:
                    # Build extra_data similar to list_inventory
                    extra_data = item.extra_data if item.extra_data else {}

                    # Get execution prompts from execution step if not in extra_data
                    if not extra_data.get("execution_prompts") and item.source_execution_step_id:
                        try:
                            execution_step = (
                                db_session.query(ExecutionStep)
                                .filter(ExecutionStep.id == item.source_execution_step_id)
                                .first()
                            )
                            if execution_step and execution_step.execution_data:
                                execution_prompts = {}
                                internal_fields = {"completed_by_email", "completed_by_user_id", "completed_at"}
                                for key, value in execution_step.execution_data.items():
                                    if key not in internal_fields and value is not None and value != "":
                                        execution_prompts[key] = value
                                if execution_prompts:
                                    extra_data["execution_prompts"] = execution_prompts

                                # Include variable inputs and outputs
                                if not extra_data.get("variable_inputs") and execution_step.actual_inputs:
                                    extra_data["variable_inputs"] = execution_step.actual_inputs
                                if not extra_data.get("variable_output") and execution_step.actual_outputs:
                                    output_name = item.name
                                    matching_output = next(
                                        (o for o in execution_step.actual_outputs if o.get("name") == output_name), None
                                    )
                                    if matching_output:
                                        extra_data["variable_output"] = matching_output
                        except Exception:
                            pass

                    # Get process name
                    process_name = None
                    if item.source_execution_id:
                        try:
                            execution = (
                                db_session.query(Execution).filter(Execution.id == item.source_execution_id).first()
                            )
                            if execution and execution.process_id:
                                process = db_session.query(Process).filter(Process.id == execution.process_id).first()
                                if process:
                                    process_name = process.name
                        except Exception:
                            pass

                    # Trace backwards to verify this item connects to our raw material
                    traced_raw_materials = trace_backward(item.id)

                    # Only include if it traces back to our raw material
                    if raw_material_uuid in traced_raw_materials:
                        # Add connection: raw material -> this item (based on execution_id)
                        if item.source_execution_id:
                            connections.append(
                                {
                                    "from_id": str(raw_material_uuid),
                                    "to_id": str(item.id),
                                    "execution_id": str(item.source_execution_id),
                                }
                            )

                        connected_items.append(
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
                                "source_execution_id": str(item.source_execution_id)
                                if item.source_execution_id
                                else None,
                                "source_execution_step_id": str(item.source_execution_step_id)
                                if item.source_execution_step_id
                                else None,
                                "source_step_name": item.source_step_name,
                                "process_name": process_name,
                                "created_at": item.created_at.isoformat() if item.created_at else None,
                                "extra_data": extra_data,
                            }
                        )
            except (InvalidOperation, ValueError, TypeError):
                continue

    # Build intermediate-to-output connections using execution_id as the core tracing mechanism
    # Items in the same execution with sequential steps are connected through the execution flow
    #
    # Strategy: Group all connected items by execution_id, then within each execution,
    # connect items based on step sequence and actual_inputs verification
    non_raw_items = [item for item in connected_items if item["inventory_type"] != InventoryType.RAW_MATERIAL.value]

    # Group items by execution_id
    items_by_execution = {}
    for item in non_raw_items:
        exec_id = item.get("source_execution_id")
        if exec_id:
            if exec_id not in items_by_execution:
                items_by_execution[exec_id] = []
            items_by_execution[exec_id].append(item)

    # For each execution, build connections based on step sequence
    for exec_id, items in items_by_execution.items():
        if len(items) < 2:
            continue  # Need at least 2 items to have a connection

        # Get step numbers for all items in this execution
        step_info = {}
        for item in items:
            step_id = item.get("source_execution_step_id")
            if step_id:
                step = db_session.query(ExecutionStep).filter(ExecutionStep.id == UUID(step_id)).first()
                if step:
                    step_info[item["id"]] = {
                        "item": item,
                        "step": step,
                        "step_number": step.step_number,
                    }

        # Sort items by step number
        sorted_items = sorted(step_info.values(), key=lambda x: x["step_number"])

        # Connect items based on actual_inputs - the step that produces an output
        # should reference its inputs via inventory_item_id
        for i, later_info in enumerate(sorted_items):
            later_step = later_info["step"]
            later_item = later_info["item"]

            if not later_step.actual_inputs:
                continue

            # Check which earlier items were used as inputs to this step
            for earlier_info in sorted_items[:i]:
                earlier_item = earlier_info["item"]

                # Verify the later step actually used this earlier item as input
                uses_earlier = any(
                    input_data.get("inventory_item_id")
                    and str(input_data.get("inventory_item_id")) == earlier_item["id"]
                    for input_data in later_step.actual_inputs
                )

                if uses_earlier:
                    # Add connection if not already exists
                    if not any(
                        c["from_id"] == earlier_item["id"] and c["to_id"] == later_item["id"] for c in connections
                    ):
                        connections.append(
                            {
                                "from_id": earlier_item["id"],
                                "to_id": later_item["id"],
                                "execution_id": exec_id,
                            }
                        )

    # Always include the raw material itself (even if consumed) for traceability
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

    # Check if raw material is already in connected_items
    if not any(item["id"] == str(raw_material.id) for item in connected_items):
        connected_items.insert(0, raw_material_data)

    # Separate into intermediates and finals
    intermediates = [item for item in connected_items if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value]
    finals = [item for item in connected_items if item["inventory_type"] == InventoryType.FINAL_PRODUCT.value]

    return jsonify(
        {
            "raw_material": raw_material_data,
            "intermediates": intermediates,
            "finals": finals,
            "all_items": connected_items,
            "connections": connections,  # Direct connections based on execution_id
        }
    ), 200


@core_bp.route("/api/core/inventory/trace-backward/<inventory_item_id>", methods=["GET"])
@requires_auth
def trace_inventory_backward(inventory_item_id: str):
    """Trace backward from any inventory item (raw, intermediate, or final) to find all source items

    Uses DAG traversal to find all inventory items that contributed to this item.
    Returns only items with quantity > 0, except for the traced item itself (if consumed).
    """
    org_id = UUID(g.org_id)
    try:
        item_uuid = UUID(inventory_item_id)
    except ValueError:
        return jsonify({"error": "Invalid inventory item ID"}), 400

    # Import models
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.process import Process

    # Get the inventory item
    traced_item = (
        db_session.query(InventoryItem).filter(InventoryItem.id == item_uuid, InventoryItem.org_id == org_id).first()
    )

    if not traced_item:
        return jsonify({"error": "Inventory item not found"}), 404

    # Helper function to trace backward from an inventory item
    def trace_backward(inventory_item_id, visited_item_ids=None, depth=0):
        """Recursively trace backwards through execution steps to find source items

        Args:
            inventory_item_id: UUID of inventory item to trace from
            visited_item_ids: Set of visited inventory item IDs to prevent cycles
            depth: Current recursion depth (for safety limits)

        Returns:
            Set of source inventory item IDs (raw materials and intermediates)
        """
        max_dag_depth = 50
        if depth > max_dag_depth:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"DAG backward traversal depth limit ({max_dag_depth}) reached")
            return set()

        if visited_item_ids is None:
            visited_item_ids = set()

        # Convert to string for set comparison
        item_id_str = str(inventory_item_id)
        if item_id_str in visited_item_ids:
            return set()  # Cycle detected
        visited_item_ids.add(item_id_str)

        source_item_ids = set()

        # Get the inventory item - convert to UUID if needed
        item_id_uuid = UUID(inventory_item_id) if isinstance(inventory_item_id, str) else inventory_item_id
        item = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id == item_id_uuid)
            .filter(InventoryItem.org_id == org_id)
            .first()
        )

        if not item or not item.source_execution_step_id:
            return source_item_ids

        # Get the execution step that produced this item
        execution_step = (
            db_session.query(ExecutionStep).filter(ExecutionStep.id == item.source_execution_step_id).first()
        )

        if not execution_step or not execution_step.actual_inputs:
            return source_item_ids

        # Check each input to find source items
        for input_data in execution_step.actual_inputs:
            input_item_id = input_data.get("inventory_item_id")
            if not input_item_id:
                continue

            # Get the input inventory item - convert to UUID if needed
            input_item_id_uuid = UUID(input_item_id) if isinstance(input_item_id, str) else input_item_id
            input_item = (
                db_session.query(InventoryItem)
                .filter(InventoryItem.id == input_item_id_uuid)
                .filter(InventoryItem.org_id == org_id)
                .first()
            )

            if not input_item:
                continue

            # Add this source item
            source_item_ids.add(input_item.id)
            # Recursively trace backwards from this source item
            prev_source_items = trace_backward(input_item.id, visited_item_ids, depth + 1)
            source_item_ids.update(prev_source_items)

        return source_item_ids

    # Trace backward from the item
    source_item_ids = trace_backward(item_uuid)

    # Build connection map: for each source item, create connection to traced item
    connections = []  # List of {from_id, to_id, execution_id} tuples

    # Get all source inventory items
    source_items = []
    if source_item_ids:
        items = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id.in_(source_item_ids), InventoryItem.org_id == org_id)
            .all()
        )

        for item in items:
            # Filter: only include items with quantity > 0, OR the traced item itself (for traceability)
            try:
                qty_str = str(item.quantity).strip() if item.quantity else "0"
                quantity_decimal = Decimal(qty_str)
                # Include if quantity > 0, or if it's the traced item itself (for consumed traceability)
                if quantity_decimal > 0 or item.id == item_uuid:
                    # Build extra_data similar to list_inventory
                    extra_data = item.extra_data if item.extra_data else {}

                    # Get execution prompts from execution step if not in extra_data
                    if not extra_data.get("execution_prompts") and item.source_execution_step_id:
                        try:
                            execution_step = (
                                db_session.query(ExecutionStep)
                                .filter(ExecutionStep.id == item.source_execution_step_id)
                                .first()
                            )
                            if execution_step and execution_step.execution_data:
                                execution_prompts = {}
                                internal_fields = {"completed_by_email", "completed_by_user_id", "completed_at"}
                                for key, value in execution_step.execution_data.items():
                                    if key not in internal_fields and value is not None and value != "":
                                        execution_prompts[key] = value
                                if execution_prompts:
                                    extra_data["execution_prompts"] = execution_prompts

                                # Include variable inputs and outputs
                                if not extra_data.get("variable_inputs") and execution_step.actual_inputs:
                                    extra_data["variable_inputs"] = execution_step.actual_inputs
                                if not extra_data.get("variable_output") and execution_step.actual_outputs:
                                    output_name = item.name
                                    matching_output = next(
                                        (o for o in execution_step.actual_outputs if o.get("name") == output_name), None
                                    )
                                    if matching_output:
                                        extra_data["variable_output"] = matching_output
                        except Exception:
                            pass

                    # Get process name
                    process_name = None
                    if item.source_execution_id:
                        try:
                            execution = (
                                db_session.query(Execution).filter(Execution.id == item.source_execution_id).first()
                            )
                            if execution and execution.process_id:
                                process = db_session.query(Process).filter(Process.id == execution.process_id).first()
                                if process:
                                    process_name = process.name
                        except Exception:
                            pass

                    # Add connection: source item -> traced item (based on execution_id)
                    # Use the traced item's execution_id if available
                    if traced_item.source_execution_id:
                        connections.append(
                            {
                                "from_id": str(item.id),
                                "to_id": str(traced_item.id),
                                "execution_id": str(traced_item.source_execution_id),
                            }
                        )

                    source_items.append(
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
                            "created_at": item.created_at.isoformat() if item.created_at else None,
                            "extra_data": extra_data,
                        }
                    )
            except (InvalidOperation, ValueError, TypeError):
                continue

    # Always include the traced item itself (even if consumed) for traceability
    traced_item_extra_data = traced_item.extra_data if traced_item.extra_data else {}
    if not traced_item_extra_data.get("execution_prompts") and traced_item.source_execution_step_id:
        try:
            execution_step = (
                db_session.query(ExecutionStep).filter(ExecutionStep.id == traced_item.source_execution_step_id).first()
            )
            if execution_step and execution_step.execution_data:
                execution_prompts = {}
                internal_fields = {"completed_by_email", "completed_by_user_id", "completed_at"}
                for key, value in execution_step.execution_data.items():
                    if key not in internal_fields and value is not None and value != "":
                        execution_prompts[key] = value
                if execution_prompts:
                    traced_item_extra_data["execution_prompts"] = execution_prompts
        except Exception:
            pass

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
        "extra_data": traced_item_extra_data,
    }

    # Check if traced item is already in source_items
    # Exclude the traced item from source_items if it's already there (to avoid duplicates)
    # The traced item will be returned separately in the response
    source_items_without_traced = [item for item in source_items if item["id"] != str(traced_item.id)]

    # Separate into raw materials and intermediates (excluding the traced item itself)
    raw_materials = [
        item for item in source_items_without_traced if item["inventory_type"] == InventoryType.RAW_MATERIAL.value
    ]
    intermediates = [
        item for item in source_items_without_traced if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value
    ]

    return jsonify(
        {
            "traced_item": traced_item_data,
            "raw_materials": raw_materials,
            "intermediates": intermediates,
            "all_items": source_items_without_traced,  # Exclude traced item to avoid duplicates
            "connections": connections,  # Direct connections based on execution_id
        }
    ), 200


@core_bp.route("/api/core/execution-metadata", methods=["GET"])
@requires_auth
def get_execution_metadata():
    """Get unique execution metadata values for search/tracing.
    Returns all unique key-value pairs from execution_data across all execution steps.
    """
    from app.core.db.models.inventory_item import InventoryItem

    user_email = getattr(g, "user_email", None)
    if is_demo_user(user_email):
        # Return mock data for demo
        return jsonify({"metadata": []}), 200

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
    # Check if demo user - return mock data
    user_email = getattr(g, "user_email", None)
    if is_demo_user(user_email):
        mock_metrics = get_mock_metrics()
        return jsonify(mock_metrics), 200

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
