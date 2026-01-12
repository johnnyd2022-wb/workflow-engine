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
            }
        ),
        200,
    )


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
                "started_at": es.started_at.isoformat() if es.started_at else None,
                "completed_at": es.completed_at.isoformat() if es.completed_at else None,
                "step_name": es.step.name if es.step else None,
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

        # Create inventory items for outputs if specified
        if actual_outputs:
            inventory_repo = InventoryRepository(db_session)
            for output in actual_outputs:
                # Determine inventory type based on terminal step detection
                # Use is_terminal_step field for deterministic detection
                inventory_type = InventoryType.WORK_IN_PROGRESS.value
                if execution_step.is_terminal_step:
                    inventory_type = InventoryType.FINAL_PRODUCT.value

                inventory_repo.create_inventory_item(
                    org_id=org_id,
                    name=output.get("name", "Unknown"),
                    quantity=str(output.get("quantity", 0)),
                    unit=output.get("unit", "units"),
                    inventory_type=inventory_type,
                    source_execution_id=execution_uuid,
                    source_execution_step_id=execution_step_uuid,
                    source_step_name=execution_step.step.name if execution_step.step else None,
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

    result = []
    for item in items:
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
                "source_step_name": item.source_step_name,
                "created_at": item.created_at.isoformat() if item.created_at else None,
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
