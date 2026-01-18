"""Core backend API routes for process execution platform"""

import os
from datetime import datetime
from uuid import UUID

from flask import Blueprint, g, jsonify, render_template, request, send_from_directory

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


@core_bp.route("/static/js/<filename>")
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

    repo = ProcessRepository(db_session)
    try:
        process = repo.create_process(org_id=org_id, name=name, description=description, category=category)
        return (
            jsonify(
                {
                    "id": str(process.id),
                    "name": process.name,
                    "description": process.description,
                    "category": process.category.value if process.category else None,
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

        # Consume inventory for variable inputs
        if actual_inputs:
            inventory_repo = InventoryRepository(db_session)
            for input_data in actual_inputs:
                inventory_item_id = input_data.get("inventory_item_id")
                quantity_consumed = input_data.get("quantity", 0)
                consumed_unit = input_data.get("unit", "")

                if inventory_item_id:
                    try:
                        inventory_item = inventory_repo.get_inventory_item_by_id(UUID(inventory_item_id), org_id)
                        if inventory_item:
                            # Convert consumed quantity to inventory item's unit
                            current_quantity = float(inventory_item.quantity)
                            inventory_unit = inventory_item.unit or ""

                            # Check if units are compatible
                            if consumed_unit and inventory_unit:
                                if not are_units_compatible(consumed_unit, inventory_unit):
                                    import logging

                                    logger = logging.getLogger(__name__)
                                    logger.warning(
                                        f"Cannot consume {quantity_consumed} {consumed_unit} from inventory "
                                        f"item {inventory_item_id} with unit {inventory_unit}: units are incompatible"
                                    )
                                    continue

                                # Convert consumed quantity to inventory unit
                                try:
                                    quantity_consumed_converted = convert_to_inventory_unit(
                                        float(quantity_consumed), consumed_unit, inventory_unit
                                    )
                                except ValueError as conv_error:
                                    import logging

                                    logger = logging.getLogger(__name__)
                                    logger.warning(
                                        f"Failed to convert {quantity_consumed} {consumed_unit} to {inventory_unit}: {conv_error}"
                                    )
                                    continue
                            else:
                                # If no unit specified, assume same unit (backward compatibility)
                                quantity_consumed_converted = float(quantity_consumed)

                            # Decrease inventory quantity
                            new_quantity = max(0, current_quantity - quantity_consumed_converted)
                            # Format quantity to avoid floating point precision issues
                            # Always set to exactly "0" string if quantity is effectively zero
                            if abs(new_quantity) < 0.0001:
                                inventory_item.quantity = "0"
                            else:
                                # Format to remove unnecessary trailing zeros
                                formatted_qty = (
                                    str(new_quantity).rstrip("0").rstrip(".")
                                    if "." in str(new_quantity)
                                    else str(int(new_quantity))
                                )
                                # Ensure we don't end up with "0.0" or "0.00" etc.
                                if float(formatted_qty) == 0:
                                    inventory_item.quantity = "0"
                                else:
                                    inventory_item.quantity = formatted_qty
                            # Commit the quantity update immediately
                            db_session.commit()
                            # Refresh the item to ensure we have the latest quantity
                            db_session.refresh(inventory_item)
                    except Exception as e:
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(f"Failed to consume inventory {inventory_item_id}: {e}")

        # Create inventory items for outputs if specified
        # All non-terminal outputs are stored as intermediate products (WORK_IN_PROGRESS)
        # Terminal outputs are stored as FINAL_PRODUCT
        # This provides a live view of stock at any moment
        if actual_outputs:
            inventory_repo = InventoryRepository(db_session)
            for output in actual_outputs:
                output_quantity = output.get("quantity", 0)
                # Skip creating inventory items with zero or negative quantity
                try:
                    quantity_float = float(output_quantity)
                    if quantity_float <= 0:
                        continue
                except (ValueError, TypeError):
                    # If quantity is not a valid number, skip this output
                    continue

                # Determine inventory type based on terminal step detection
                # Use is_terminal_step field for deterministic detection
                # Non-terminal steps produce intermediate products (work_in_progress)
                # Terminal steps produce final products
                inventory_type = InventoryType.WORK_IN_PROGRESS.value
                if execution_step.is_terminal_step:
                    inventory_type = InventoryType.FINAL_PRODUCT.value

                # Store execution metadata in extra_data for traceability
                # This includes execution prompts, variable inputs, and variable outputs
                # Read from execution_step.execution_data (from DB) so existing entries can be updated
                extra_data = {}
                # Get execution_data from the execution_step (read from DB after refresh)
                step_execution_data = execution_step.execution_data if execution_step.execution_data else {}
                if step_execution_data:
                    # Store execution prompts (metadata captured during execution)
                    # Keep completed_by for user tracing, but filter out email and user_id
                    execution_prompts = {}
                    internal_fields = {"completed_by_email", "completed_by_user_id", "completed_at"}
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
                output_name = output.get("name", "Unknown")
                # Get actual_outputs from the execution_step (it was stored when the step was completed)
                step_actual_outputs = execution_step.actual_outputs if execution_step.actual_outputs else []
                if step_actual_outputs:
                    # Find the matching output in actual_outputs
                    matching_output = next((o for o in step_actual_outputs if o.get("name") == output_name), None)
                    if matching_output:
                        extra_data["variable_output"] = matching_output

                inventory_repo.create_inventory_item(
                    org_id=org_id,
                    name=output.get("name", "Unknown"),
                    quantity=str(output_quantity),
                    unit=output.get("unit", "units"),
                    inventory_type=inventory_type,
                    source_execution_id=execution_uuid,
                    source_execution_step_id=execution_step_uuid,
                    source_step_name=execution_step.step.name if execution_step.step else None,
                    extra_data=extra_data if extra_data else None,
                )

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
        # Handle string quantities like "0", "0.0", etc. more robustly
        try:
            qty_str = str(item.quantity).strip() if item.quantity else "0"
            quantity_float = float(qty_str)
            # Skip items with zero or negative quantity (including very small numbers)
            if quantity_float <= 0 or abs(quantity_float) < 0.0001:
                continue  # Skip this item
        except (ValueError, TypeError):
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
                def trace_step_chain(
                    inventory_item_id, input_name=None, input_quantity=None, input_unit=None, visited_ids=None
                ):
                    """Recursively trace back through all steps that produced this inventory item"""
                    if visited_ids is None:
                        visited_ids = set()

                    # Prevent infinite loops
                    if inventory_item_id in visited_ids:
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
                                prev_steps = trace_step_chain(
                                    prev_inventory_item_id,
                                    input_name=prev_input_data.get("name"),
                                    input_quantity=prev_input_data.get("quantity"),
                                    input_unit=prev_input_data.get("unit"),
                                    visited_ids=visited_ids,
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

        # Add previous_steps_data to extra_data if we found any
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
