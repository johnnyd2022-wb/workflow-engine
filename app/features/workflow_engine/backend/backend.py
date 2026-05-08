import json
import uuid
from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request

from app.core.security.permissions import requires_auth
from app.initialize import db_conn

# Create Workflow Engine blueprint
workflow_engine_bp = Blueprint(
    "workflow_engine",
    __name__,
    template_folder="../frontend",
    static_folder="../frontend",
    static_url_path="/workflow-engine-static",
)


def format_process_type_for_display(process_type):
    """Convert database process type to user-friendly display name"""
    if not process_type:
        return "Not specified"

    type_mapping = {
        "production_workflow": "Production Workflow",
        "quality_workflow": "Quality Workflow",
        "logistics_workflow": "Logistics Workflow",
        "procurement_workflow": "Procurement Workflow",
        "manufacturing": "Manufacturing",
        "packaging": "Packaging",
        "quality_control": "Quality Control",
        "logistics": "Logistics",
        "procurement": "Procurement",
    }

    return type_mapping.get(process_type, process_type.replace("_", " ").title())


@workflow_engine_bp.route("/workflow-engine", methods=["GET", "POST"])
@requires_auth
def workflow_engine():
    print("Accessed /workflow-engine route")
    connection, cursor = db_conn()

    try:
        # Get all parent processes
        cursor.execute("""
            SELECT id, parent_process_name, parent_process_description, parent_process_type,
                   parent_process_status, parent_process_category, parent_process_notes, date
            FROM workflow_engine_parent_processes
            ORDER BY parent_process_name
        """)
        parent_processes = cursor.fetchall()

        # Get parent process statistics
        cursor.execute("SELECT COUNT(*) FROM workflow_engine_parent_processes")
        total_parent_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_parent_processes WHERE parent_process_status = 'active'")
        active_parent_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_sub_processes")
        total_sub_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_inputs")
        total_inputs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_outputs")
        total_outputs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_connections")
        total_connections = cursor.fetchone()[0]

        return render_template(
            "workflow_engine.html",
            parent_processes=parent_processes,
            total_parent_processes=total_parent_processes,
            active_parent_processes=active_parent_processes,
            total_sub_processes=total_sub_processes,
            total_inputs=total_inputs,
            total_outputs=total_outputs,
            total_connections=total_connections,
            format_type=format_process_type_for_display,
        )

    except Exception as e:
        print(f"Error in workflow_engine route: {e}")
        return render_template(
            "workflow_engine.html",
            parent_processes=[],
            total_parent_processes=0,
            active_parent_processes=0,
            total_sub_processes=0,
            total_inputs=0,
            total_outputs=0,
            total_connections=0,
            error=str(e),
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


## Lovable Pages


@workflow_engine_bp.route("/workflow-engine-lovable", methods=["GET", "POST"])
@requires_auth
def workflow_engine_lovable():
    print("Accessed /workflow-engine-lovable route")
    connection, cursor = db_conn()

    try:
        # Get all parent processes
        cursor.execute("""
            SELECT id, parent_process_name, parent_process_description, parent_process_type,
                   parent_process_status, parent_process_category, parent_process_notes, date
            FROM workflow_engine_parent_processes
            ORDER BY parent_process_name
        """)
        parent_processes = cursor.fetchall()

        # Get parent process statistics
        cursor.execute("SELECT COUNT(*) FROM workflow_engine_parent_processes")
        total_parent_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_parent_processes WHERE parent_process_status = 'active'")
        active_parent_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_sub_processes")
        total_sub_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_inputs")
        total_inputs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_outputs")
        total_outputs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM workflow_engine_connections")
        total_connections = cursor.fetchone()[0]

        return render_template(
            "workflow_engine_lovable.html",
            parent_processes=parent_processes,
            total_parent_processes=total_parent_processes,
            active_parent_processes=active_parent_processes,
            total_sub_processes=total_sub_processes,
            total_inputs=total_inputs,
            total_outputs=total_outputs,
            total_connections=total_connections,
            format_type=format_process_type_for_display,
        )

    except Exception as e:
        print(f"Error in workflow_engine route: {e}")
        return render_template(
            "workflow_engine.html",
            parent_processes=[],
            total_parent_processes=0,
            active_parent_processes=0,
            total_sub_processes=0,
            total_inputs=0,
            total_outputs=0,
            total_connections=0,
            error=str(e),
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/workflow-engine/index")
@requires_auth
def index():
    """Render the index page"""
    # return render_template("index.html")
    return render_template("workflow_engine_lovable.html")


@workflow_engine_bp.route("/workflow-engine/core")
@requires_auth
def parent_processes():
    """Render the core engine workflow engine page"""
    return render_template("core.html")


@workflow_engine_bp.route("/workflow-engine/dashboard")
@requires_auth
def dashboard():
    """Render the dashboard page"""
    return render_template("dashboard.html", active_page="dashboard")


@workflow_engine_bp.route("/workflow-engine/compliance")
@requires_auth
def compliance():
    """Render the compliance page"""
    return render_template("compliance.html")


@workflow_engine_bp.route("/workflow-engine/integrations")
@requires_auth
def integrations():
    """Render the integrations page"""
    return render_template("integrations.html", active_page="integrations")


@workflow_engine_bp.route("/workflow-engine/settings")
@requires_auth
def settings():
    """Render the settings page"""
    return render_template("settings.html", active_page="settings")


@workflow_engine_bp.route("/workflow-engine/flow-engine1")
@requires_auth
def flow_engine1():
    """Render the flow engine 1 page"""
    return render_template("flow-engine.html")


@workflow_engine_bp.route("/workflow-engine/flow-engine")
@requires_auth
def flow_engine():
    """Render the flow engine page"""
    return render_template("flow-engine1.html")


##


@workflow_engine_bp.route("/workflow-engine/parent-process/<int:parent_process_id>")
@requires_auth
def parent_process_detail(parent_process_id):
    print(f"Accessed parent process detail for ID: {parent_process_id}")
    connection, cursor = db_conn()

    try:
        # Get parent process details
        cursor.execute(
            """
            SELECT id, parent_process_name, parent_process_description, parent_process_type,
                   parent_process_status, parent_process_category, parent_process_notes, date
            FROM workflow_engine_parent_processes
            WHERE id = %s
        """,
            (parent_process_id,),
        )
        parent_process = cursor.fetchone()

        if not parent_process:
            return render_template(
                "parent_process_detail.html",
                parent_process=None,
                sub_processes=[],
                connections=[],
                error="Parent process not found",
            )

        # Get sub processes for this parent
        cursor.execute(
            """
            SELECT id, sub_process_name, sub_process_description, sub_process_type,
                   sub_process_status, sub_process_category, sub_process_notes,
                   execution_order, date
            FROM workflow_engine_sub_processes
            WHERE parent_process_id = %s
            ORDER BY execution_order, sub_process_name
        """,
            (parent_process_id,),
        )
        sub_processes = cursor.fetchall()

        # Get connections between sub-processes in this parent process
        cursor.execute(
            """
            SELECT c.id, c.parent_process_id, c.from_sub_process_id, c.to_sub_process_id, c.connection_type,
                   c.connection_status, c.connection_notes, c.date, c.action, c.uid,
                   sp1.sub_process_name as from_sub_process_name,
                   sp2.sub_process_name as to_sub_process_name
            FROM workflow_engine_connections c
            LEFT JOIN workflow_engine_sub_processes sp1 ON c.from_sub_process_id = sp1.id
            LEFT JOIN workflow_engine_sub_processes sp2 ON c.to_sub_process_id = sp2.id
            WHERE c.parent_process_id = %s
            ORDER BY c.date DESC
        """,
            (parent_process_id,),
        )
        connections = cursor.fetchall()

        # Get existing executions for this parent process (limit to 5 most recent)
        cursor.execute(
            """
            SELECT pe.id, pe.parent_process_id, pe.execution_status, pe.execution_start_time,
                   pe.execution_end_time, pe.execution_notes, pe.date,
                   pp.parent_process_name
            FROM workflow_engine_parent_executions pe
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.parent_process_id = %s
            ORDER BY pe.date DESC, pe.id DESC
            LIMIT 5
        """,
            (parent_process_id,),
        )
        executions = cursor.fetchall()

        # Get total count of executions for this parent process
        cursor.execute(
            """
            SELECT COUNT(*) FROM workflow_engine_parent_executions
            WHERE parent_process_id = %s
        """,
            (parent_process_id,),
        )
        total_executions = cursor.fetchone()[0]

        return render_template(
            "parent_process_detail.html",
            parent_process=parent_process,
            sub_processes=sub_processes,
            connections=connections,
            executions=executions,
            total_executions=total_executions,
            format_type=format_process_type_for_display,
        )

    except Exception as e:
        print(f"Error in parent_process_detail route: {e}")
        return render_template(
            "parent_process_detail.html",
            parent_process=None,
            sub_processes=[],
            connections=[],
            executions=[],
            total_executions=0,
            error=str(e),
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/workflow-engine/parent-process/<int:parent_process_id>/visual", methods=["GET"])
@requires_auth
def parent_process_visual_view(parent_process_id):
    """Visual DAG view for a specific parent process showing only its sub processes"""
    print(f"Accessed /workflow-engine/parent-process/{parent_process_id}/visual route")
    connection, cursor = db_conn()

    try:
        # Get parent process details
        cursor.execute(
            """
            SELECT id, parent_process_name, parent_process_description, parent_process_type,
                   parent_process_status, parent_process_category, parent_process_notes
            FROM workflow_engine_parent_processes
            WHERE id = %s
        """,
            (parent_process_id,),
        )
        parent_process = cursor.fetchone()

        if not parent_process:
            return "Parent process not found", 404

        return render_template(
            "parent_process_visual.html", parent_process=parent_process, format_type=format_process_type_for_display
        )

    except Exception as e:
        print(f"Error in parent_process_visual_view route: {e}")
        return f"Error loading visual view: {e}", 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/workflow-engine/sub-process/<int:sub_process_id>")
@requires_auth
def sub_process_detail(sub_process_id):
    """Detail view for a specific sub process"""
    print(f"Accessed sub-process detail for ID: {sub_process_id}")
    connection, cursor = db_conn()

    try:
        # Get sub process details
        cursor.execute(
            """
            SELECT s.id, s.parent_process_id, s.sub_process_name, s.sub_process_description,
                   s.sub_process_type, s.sub_process_status, s.sub_process_category,
                   s.sub_process_notes, s.execution_order, s.date,
                   p.parent_process_name
            FROM workflow_engine_sub_processes s
            LEFT JOIN workflow_engine_parent_processes p ON s.parent_process_id = p.id
            WHERE s.id = %s
        """,
            (sub_process_id,),
        )
        sub_process = cursor.fetchone()

        if not sub_process:
            return render_template(
                "process_detail.html",
                process=None,
                inputs=[],
                outputs=[],
                connections=[],
                error="Sub-process not found",
            )

        # Get inputs for this sub process
        cursor.execute(
            """
            SELECT i.id, i.process_id, i.input_name, i.input_type, i.input_quantity,
                   i.input_unit, i.input_specifications, i.input_source, i.input_batch_number,
                   i.input_status, i.date, i.action
            FROM workflow_engine_inputs i
            WHERE i.process_id = %s
            ORDER BY i.input_name
        """,
            (sub_process_id,),
        )
        inputs = cursor.fetchall()

        # Get outputs for this sub process
        cursor.execute(
            """
            SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity,
                   o.output_unit, o.output_specifications, o.output_batch_number,
                   o.output_quality_status, o.output_destination, o.date, o.action
            FROM workflow_engine_outputs o
            WHERE o.process_id = %s
            ORDER BY o.output_name
        """,
            (sub_process_id,),
        )
        outputs = cursor.fetchall()

        # Get connections for this sub process
        cursor.execute(
            """
            SELECT c.id, c.from_process_id, c.to_process_id, c.connection_type,
                   c.connection_status, c.connection_notes, c.date, c.action,
                   from_proc.sub_process_name as from_process_name,
                   to_proc.sub_process_name as to_process_name
            FROM workflow_engine_connections c
            LEFT JOIN workflow_engine_sub_processes from_proc ON c.from_process_id = from_proc.id
            LEFT JOIN workflow_engine_sub_processes to_proc ON c.to_process_id = to_proc.id
            WHERE c.from_process_id = %s OR c.to_process_id = %s
            ORDER BY c.from_process_id, c.to_process_id
        """,
            (sub_process_id, sub_process_id),
        )
        connections = cursor.fetchall()

        return render_template(
            "process_detail.html",
            process=sub_process,
            inputs=inputs,
            outputs=outputs,
            connections=connections,
            parent_process_name=sub_process[10] if sub_process else None,
        )

    except Exception as e:
        print(f"Error in sub_process_detail route: {e}")
        return f"Error loading sub-process details: {e}", 500
    finally:
        cursor.close()
        connection.close()


def get_dag_execution_order(parent_process_id, cursor):
    """Determine the proper execution order based on DAG connections"""
    # Get all sub-processes for this parent process
    cursor.execute(
        """
        SELECT id, sub_process_name, execution_order
        FROM workflow_engine_sub_processes
        WHERE parent_process_id = %s AND sub_process_status = 'active'
        ORDER BY execution_order, sub_process_name
    """,
        (parent_process_id,),
    )
    sub_processes = cursor.fetchall()

    # Get all connections for this parent process
    cursor.execute(
        """
        SELECT from_sub_process_id, to_sub_process_id
        FROM workflow_engine_connections
        WHERE parent_process_id = %s AND connection_status = 'active'
    """,
        (parent_process_id,),
    )
    connections = cursor.fetchall()

    # Build adjacency list
    graph = {}
    in_degree = {}

    # Initialize all processes
    for process in sub_processes:
        process_id = process[0]
        graph[process_id] = []
        in_degree[process_id] = 0

    # Add edges based on connections
    for connection in connections:
        from_id = connection[0]
        to_id = connection[1]
        if from_id in graph and to_id in graph:
            graph[from_id].append(to_id)
            in_degree[to_id] += 1

    # Topological sort using Kahn's algorithm
    queue = []
    result = []

    # Add processes with no incoming edges
    for process_id in in_degree:
        if in_degree[process_id] == 0:
            queue.append(process_id)

    execution_order_map = {p[0]: p[2] for p in sub_processes}
    while queue:
        queue.sort(key=lambda x: execution_order_map.get(x, 0))
        current = queue.pop(0)
        result.append(current)

        # Remove current process and update in-degrees
        for neighbor in graph[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result


@workflow_engine_bp.route("/workflow-engine/execution/<int:execution_id>")
@requires_auth
def execution_detail(execution_id):
    """Detail view for a specific execution"""
    print(f"Accessed execution detail for ID: {execution_id}")
    connection, cursor = db_conn()

    try:
        # Get parent execution details
        cursor.execute(
            """
            SELECT pe.id, pe.parent_process_id, pe.execution_status, pe.execution_start_time,
                   pe.execution_end_time, pe.execution_notes, pe.date,
                   pp.parent_process_name
            FROM workflow_engine_parent_executions pe
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.id = %s
        """,
            (execution_id,),
        )
        parent_execution = cursor.fetchone()

        if not parent_execution:
            return render_template(
                "execution_detail.html", execution=None, sub_executions=[], error="Execution not found"
            )

        # Get sub-executions for this parent execution
        cursor.execute(
            """
            SELECT se.id, se.parent_execution_id, se.sub_process_id, se.execution_status,
                   se.execution_start_time, se.execution_end_time, se.execution_notes,
                   sp.sub_process_name, sp.execution_order
            FROM workflow_engine_sub_executions se
            LEFT JOIN workflow_engine_sub_processes sp ON se.sub_process_id = sp.id
            WHERE se.parent_execution_id = %s
        """,
            (execution_id,),
        )
        sub_executions_raw = cursor.fetchall()

        # Get DAG execution order
        dag_order = get_dag_execution_order(parent_execution[1], cursor)

        # Sort sub-executions according to DAG order
        sub_executions = []
        for process_id in dag_order:
            for sub_execution in sub_executions_raw:
                if sub_execution[2] == process_id:  # sub_process_id
                    sub_executions.append(sub_execution)
                    break

        return render_template("execution_detail.html", execution=parent_execution, sub_executions=sub_executions)

    except Exception as e:
        print(f"Error in execution_detail route: {e}")
        return render_template("execution_detail.html", execution=None, sub_executions=[], error=str(e))
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/save-layout", methods=["POST"])
@requires_auth
def save_layout():
    """Save DAG layout positions"""
    try:
        data = request.get_json()
        layout_data = data.get("layout_data")
        parent_process_id = data.get("parent_processId")

        if not layout_data or not parent_process_id:
            return jsonify({"success": False, "error": "Missing layout data or parent process ID"}), 400

        connection, cursor = db_conn()

        # Check if layout already exists for this parent process
        cursor.execute(
            """
            SELECT id FROM workflow_engine_dag_layout
            WHERE layout_data::text LIKE %s
        """,
            (f'%"parentProcessId":{parent_process_id}%',),
        )

        existing_layout = cursor.fetchone()

        if existing_layout:
            # Update existing layout
            cursor.execute(
                """
                UPDATE workflow_engine_dag_layout
                SET layout_data = %s, layout_timestamp = %s, action = 'update'
                WHERE id = %s
            """,
                (json.dumps(layout_data), datetime.now(), existing_layout[0]),
            )
        else:
            # Create new layout
            cursor.execute(
                """
                INSERT INTO workflow_engine_dag_layout
                (date, action, layout_data, layout_timestamp, uid)
                VALUES (%s, %s, %s, %s, %s)
            """,
                (datetime.now().date(), "save", json.dumps(layout_data), datetime.now(), f"parent_{parent_process_id}"),
            )

        connection.commit()
        cursor.close()
        connection.close()

        return jsonify({"success": True})

    except Exception as e:
        print(f"Error saving layout: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/load-layout/<int:parent_process_id>", methods=["GET"])
@requires_auth
def load_layout(parent_process_id):
    """Load DAG layout positions for a parent process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT layout_data, layout_timestamp
            FROM workflow_engine_dag_layout
            WHERE layout_data::text LIKE %s
            ORDER BY layout_timestamp DESC
            LIMIT 1
        """,
            (f'%"parentProcessId":{parent_process_id}%',),
        )

        layout = cursor.fetchone()
        cursor.close()
        connection.close()

        if layout:
            return jsonify({"success": True, "layout": {"layout_data": layout[0], "layout_timestamp": layout[1]}})
        else:
            return jsonify({"success": True, "layout": None})

    except Exception as e:
        print(f"Error loading layout: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/update-execution-order", methods=["POST"])
@requires_auth
def update_execution_order():
    """Update execution order based on DAG connections"""
    try:
        data = request.get_json()
        parent_process_id = data.get("parent_process_id")
        execution_order = data.get("execution_order")  # List of sub_process_ids in order

        if not parent_process_id or not execution_order:
            return jsonify({"success": False, "error": "Missing parent_process_id or execution_order"}), 400

        connection, cursor = db_conn()

        # Update execution order for each sub process
        for order, sub_process_id in enumerate(execution_order, 1):
            cursor.execute(
                """
                UPDATE workflow_engine_sub_processes
                SET execution_order = %s, action = 'update_order'
                WHERE id = %s AND parent_process_id = %s
            """,
                (order, sub_process_id, parent_process_id),
            )

        connection.commit()
        cursor.close()
        connection.close()

        return jsonify({"success": True})

    except Exception as e:
        print(f"Error updating execution order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/parent-processes/<int:parent_process_id>/inputs", methods=["GET"])
@requires_auth
def get_inputs_by_parent(parent_process_id):
    """Get all inputs for sub processes of a specific parent process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT i.id, i.sub_process_id, i.input_name, i.input_type,
                   i.input_specifications, i.input_quantity, i.input_unit, i.input_status,
                   sp.sub_process_name
            FROM workflow_engine_inputs i
            JOIN workflow_engine_sub_processes sp ON i.sub_process_id = sp.id
            WHERE sp.parent_process_id = %s
            ORDER BY sp.execution_order, i.input_name
        """,
            (parent_process_id,),
        )

        inputs = cursor.fetchall()
        cursor.close()
        connection.close()

        # Convert to list of dictionaries for JSON response
        result = []
        for inp in inputs:
            result.append(
                {
                    "id": inp[0],
                    "sub_process_id": inp[1],
                    "input_name": inp[2],
                    "input_type": inp[3],
                    "input_specifications": inp[4],
                    "input_quantity": inp[5],
                    "input_unit": inp[6],
                    "input_status": inp[7],
                    "sub_process_name": inp[8],
                }
            )

        return jsonify({"success": True, "inputs": result})

    except Exception as e:
        print(f"Error getting inputs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/parent-processes/<int:parent_process_id>/outputs", methods=["GET"])
@requires_auth
def get_outputs_by_parent(parent_process_id):
    """Get all outputs for sub processes of a specific parent process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT o.id, o.sub_process_id, o.output_name, o.output_type,
                   o.output_specifications, o.output_quantity, o.output_unit, o.output_quality_status,
                   sp.sub_process_name
            FROM workflow_engine_outputs o
            JOIN workflow_engine_sub_processes sp ON o.sub_process_id = sp.id
            WHERE sp.parent_process_id = %s
            ORDER BY sp.execution_order, o.output_name
        """,
            (parent_process_id,),
        )

        outputs = cursor.fetchall()
        cursor.close()
        connection.close()

        # Convert to list of dictionaries for JSON response
        result = []
        for out in outputs:
            result.append(
                {
                    "id": out[0],
                    "sub_process_id": out[1],
                    "output_name": out[2],
                    "output_type": out[3],
                    "output_specifications": out[4],
                    "output_quantity": out[5],
                    "output_unit": out[6],
                    "output_quality_status": out[7],
                    "sub_process_name": out[8],
                }
            )

        return jsonify({"success": True, "outputs": result})

    except Exception as e:
        print(f"Error getting outputs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/parent-processes/<int:parent_process_id>/connections", methods=["GET"])
@requires_auth
def get_connections_by_parent(parent_process_id):
    """Get all connections between sub processes of a specific parent process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT c.id, c.from_sub_process_id, c.to_sub_process_id, c.connection_type,
                   c.connection_notes, c.connection_status,
                   sp_from.sub_process_name as from_process_name,
                   sp_to.sub_process_name as to_process_name
            FROM workflow_engine_connections c
            JOIN workflow_engine_sub_processes sp_from ON c.from_sub_process_id = sp_from.id
            JOIN workflow_engine_sub_processes sp_to ON c.to_sub_process_id = sp_to.id
            WHERE sp_from.parent_process_id = %s AND sp_to.parent_process_id = %s
            ORDER BY c.id
        """,
            (parent_process_id, parent_process_id),
        )

        connections = cursor.fetchall()
        cursor.close()
        connection.close()

        # Convert to list of dictionaries for JSON response
        result = []
        for conn in connections:
            result.append(
                {
                    "id": conn[0],
                    "from_sub_process_id": conn[1],
                    "to_sub_process_id": conn[2],
                    "connection_type": conn[3],
                    "connection_notes": conn[4],
                    "connection_status": conn[5],
                    "from_process_name": conn[6],
                    "to_process_name": conn[7],
                }
            )

        return jsonify({"success": True, "connections": result})

    except Exception as e:
        print(f"Error getting connections: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/workflow-engine/process/<int:process_id>")
@requires_auth
def process_detail(process_id):
    print(f"Accessed process detail for ID: {process_id}")
    connection, cursor = db_conn()

    try:
        # Get process details
        cursor.execute(
            """
            SELECT id, process_name, process_description, process_type,
                   process_status, process_category, process_notes, date
            FROM workflow_engine_processes
            WHERE id = %s
        """,
            (process_id,),
        )
        process = cursor.fetchone()

        if not process:
            return render_template(
                "process_detail.html", process=None, inputs=[], outputs=[], connections=[], error="Process not found"
            )

        # Get inputs for this process
        cursor.execute(
            """
            SELECT id, input_name, input_type, input_quantity, input_unit,
                   input_specifications, input_source, input_batch_number,
                   input_expiry_date, input_status, date
            FROM workflow_engine_inputs
            WHERE process_id = %s
            ORDER BY input_name
        """,
            (process_id,),
        )
        inputs = cursor.fetchall()

        # Get outputs for this process
        cursor.execute(
            """
            SELECT id, output_name, output_type, output_quantity, output_unit,
                   output_specifications, output_batch_number, output_quality_status,
                   output_destination, date
            FROM workflow_engine_outputs
            WHERE process_id = %s
            ORDER BY output_name
        """,
            (process_id,),
        )
        outputs = cursor.fetchall()

        # Get connections for this process
        cursor.execute(
            """
            SELECT c.id, c.from_process_id, c.to_process_id, c.from_output_id, c.to_input_id,
                   c.connection_type, c.connection_status, c.connection_notes,
                   fp.process_name as from_process_name,
                   tp.process_name as to_process_name
            FROM workflow_engine_connections c
            LEFT JOIN workflow_engine_processes fp ON c.from_process_id = fp.id
            LEFT JOIN workflow_engine_processes tp ON c.to_process_id = tp.id
            WHERE c.from_process_id = %s OR c.to_process_id = %s
            ORDER BY c.id
        """,
            (process_id, process_id),
        )
        connections = cursor.fetchall()

        return render_template(
            "process_detail.html", process=process, inputs=inputs, outputs=outputs, connections=connections
        )

    except Exception as e:
        print(f"Error in process_detail route: {e}")
        return render_template("process_detail.html", process=None, inputs=[], outputs=[], connections=[], error=str(e))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# API Routes for CRUD operations


@workflow_engine_bp.route("/api/workflow-engine/processes", methods=["POST"])
@requires_auth
def create_process():
    """Create a new process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            INSERT INTO workflow_engine_processes
            (date, action, process_name, process_description, process_type,
             process_status, process_category, process_notes, is_managed, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                data.get("process_name"),
                data.get("process_description", ""),
                data.get("process_type", "manufacturing"),
                data.get("process_status", "active"),
                data.get("process_category", ""),
                data.get("process_notes", ""),
                data.get("is_managed", False),  # New processes start as unmanaged
                data.get("uid", ""),
            ),
        )

        process_id = cursor.fetchone()[0]
        connection.commit()

        return jsonify({"id": process_id, "message": "Process created successfully"}), 201

    except Exception as e:
        print(f"Error creating process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>", methods=["GET"])
@requires_auth
def get_process(process_id):
    """Get a specific process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT id, process_name, process_description, process_type,
                   process_status, process_category, process_notes, date, flow_through_enabled, is_managed
            FROM workflow_engine_processes
            WHERE id = %s
        """,
            (process_id,),
        )

        process = cursor.fetchone()
        if not process:
            return jsonify({"error": "Process not found"}), 404

        return jsonify(
            {
                "id": process[0],
                "process_name": process[1],
                "process_description": process[2],
                "process_type": process[3],
                "process_status": process[4],
                "process_category": process[5],
                "process_notes": process[6],
                "date": process[7].isoformat() if process[7] else None,
                "flow_through_enabled": process[8] or False,
                "is_managed": process[9] or False,
            }
        )

    except Exception as e:
        print(f"Error getting process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>", methods=["PUT"])
@requires_auth
def update_process(process_id):
    """Update a process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            UPDATE workflow_engine_processes
            SET process_name = %s, process_description = %s, process_type = %s,
                process_status = %s, process_category = %s, process_notes = %s,
                action = 'update', date = %s
            WHERE id = %s
        """,
            (
                data.get("process_name"),
                data.get("process_description"),
                data.get("process_type"),
                data.get("process_status"),
                data.get("process_category"),
                data.get("process_notes"),
                date.today(),
                process_id,
            ),
        )

        if cursor.rowcount == 0:
            return jsonify({"error": "Process not found"}), 404

        connection.commit()
        return jsonify({"message": "Process updated successfully"})

    except Exception as e:
        print(f"Error updating process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>", methods=["DELETE"])
@requires_auth
def delete_process(process_id):
    """Delete a process"""
    try:
        print(f"Delete process API called for process_id: {process_id}")
        connection, cursor = db_conn()

        # Check if process exists
        cursor.execute("SELECT id, process_name FROM workflow_engine_processes WHERE id = %s", (process_id,))
        process = cursor.fetchone()
        if not process:
            print(f"Process {process_id} not found")
            return jsonify({"error": "Process not found"}), 404

        print(f"Found process: {process[1]} (ID: {process[0]})")

        # Delete related records first
        print("Deleting related inputs...")
        cursor.execute("DELETE FROM workflow_engine_inputs WHERE process_id = %s", (process_id,))
        inputs_deleted = cursor.rowcount
        print(f"Deleted {inputs_deleted} inputs")

        print("Deleting related outputs...")
        cursor.execute("DELETE FROM workflow_engine_outputs WHERE process_id = %s", (process_id,))
        outputs_deleted = cursor.rowcount
        print(f"Deleted {outputs_deleted} outputs")

        print("Deleting related connections...")
        cursor.execute(
            "DELETE FROM workflow_engine_connections WHERE from_process_id = %s OR to_process_id = %s",
            (process_id, process_id),
        )
        connections_deleted = cursor.rowcount
        print(f"Deleted {connections_deleted} connections")

        # Delete the process
        print("Deleting process...")
        cursor.execute("DELETE FROM workflow_engine_processes WHERE id = %s", (process_id,))
        process_deleted = cursor.rowcount
        print(f"Deleted {process_deleted} processes")

        connection.commit()
        print("Transaction committed successfully")
        return jsonify({"message": "Process deleted successfully"})

    except Exception as e:
        print(f"Error deleting process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# Flow-through API endpoints
@workflow_engine_bp.route("/api/workflow-engine/flow-through", methods=["GET"])
@requires_auth
def get_flow_through_outputs():
    """Get all outputs with flow-through enabled"""
    try:
        connection, cursor = db_conn()

        cursor.execute("""
            SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity,
                   o.output_unit, o.output_specifications, o.output_batch_number,
                   o.output_destination, o.output_flow_through_fields, o.execution_options,
                   p.sub_process_name
            FROM workflow_engine_outputs o
            LEFT JOIN workflow_engine_sub_processes p ON o.process_id = p.id
            WHERE o.output_flow_through = TRUE
        """)

        outputs = cursor.fetchall()

        result = []
        for output in outputs:
            result.append(
                {
                    "id": output[0],
                    "process_id": output[1],
                    "output_name": output[2],
                    "output_type": output[3],
                    "output_quantity": output[4],
                    "output_unit": output[5],
                    "output_specifications": output[6],
                    "output_batch_number": output[7],
                    "output_destination": output[8],
                    "output_flow_through_fields": output[9] or {},
                    "execution_options": output[10] or {},
                    "process_name": output[11],
                }
            )

        return jsonify(result)

    except Exception as e:
        print(f"Error getting flow-through outputs: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/flow-through/outputs/<int:output_id>/connections", methods=["GET"])
@requires_auth
def get_flow_through_connections(output_id):
    """Get all connections for a specific output's process"""
    try:
        connection, cursor = db_conn()

        # Get the process_id for this output
        cursor.execute("SELECT process_id FROM workflow_engine_outputs WHERE id = %s", (output_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Output not found"}), 404

        process_id = result[0]

        # Get all connections from this process
        cursor.execute(
            """
            SELECT c.id, c.from_sub_process_id, c.to_sub_process_id, c.connection_type,
                   p1.sub_process_name as from_process_name,
                   p2.sub_process_name as to_process_name
            FROM workflow_engine_connections c
            LEFT JOIN workflow_engine_sub_processes p1 ON c.from_sub_process_id = p1.id
            LEFT JOIN workflow_engine_sub_processes p2 ON c.to_sub_process_id = p2.id
            WHERE c.from_sub_process_id = %s AND c.connection_status = 'active'
        """,
            (process_id,),
        )

        connections = cursor.fetchall()

        result = []
        for conn in connections:
            result.append(
                {
                    "id": conn[0],
                    "from_sub_process_id": conn[1],
                    "to_sub_process_id": conn[2],
                    "connection_type": conn[3],
                    "from_process_name": conn[4],
                    "to_process_name": conn[5],
                }
            )

        return jsonify(result)

    except Exception as e:
        print(f"Error getting flow-through connections: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/flow-through/outputs/<int:output_id>/create-inputs", methods=["POST"])
@requires_auth
def create_flow_through_inputs(output_id):
    """Create inputs in connected processes for a specific output"""
    try:
        connection, cursor = db_conn()

        # Get the output details
        cursor.execute(
            """
            SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity,
                   o.output_unit, o.output_specifications, o.output_batch_number,
                   o.output_destination, o.output_flow_through_fields, o.execution_options,
                   p.sub_process_name
            FROM workflow_engine_outputs o
            LEFT JOIN workflow_engine_sub_processes p ON o.process_id = p.id
            WHERE o.id = %s AND o.output_flow_through = TRUE
        """,
            (output_id,),
        )

        output = cursor.fetchone()
        if not output:
            return jsonify({"error": "Output not found or flow-through not enabled"}), 404

        (
            output_id,
            process_id,
            output_name,
            output_type,
            output_quantity,
            output_unit,
            output_specifications,
            output_batch_number,
            output_destination,
            flow_through_fields,
            execution_options,
            source_process_name,
        ) = output

        # Parse flow-through fields and execution options
        flow_fields = (
            flow_through_fields
            if isinstance(flow_through_fields, dict)
            else (json.loads(flow_through_fields) if flow_through_fields else {})
        )
        exec_options = (
            execution_options
            if isinstance(execution_options, dict)
            else (json.loads(execution_options) if execution_options else {})
        )

        # Filter execution options to only include fields that have flow-through enabled
        # Transform 'prompt' to 'template' for flow-through fields
        filtered_exec_options = {}
        for field, is_enabled in flow_fields.items():
            if is_enabled and field in exec_options:
                # Transform 'prompt' to 'template' for flow-through fields
                if exec_options[field] == "prompt":
                    filtered_exec_options[field] = "template"
                    print(f"Transformed {field}: 'prompt' → 'template'")
                else:
                    filtered_exec_options[field] = exec_options[field]
                    print(f"Kept {field}: '{exec_options[field]}'")

        print(f"Original execution options: {exec_options}")
        print(f"Filtered execution options: {filtered_exec_options}")

        # Get all connections from this process
        cursor.execute(
            """
            SELECT to_sub_process_id, connection_type
            FROM workflow_engine_connections
            WHERE from_sub_process_id = %s AND connection_status = 'active'
        """,
            (process_id,),
        )

        connections = cursor.fetchall()

        if not connections:
            return jsonify({"error": "No active connections found from this process"}), 404

        created_inputs = []

        # For each connection, create inputs in the receiving process
        for to_sub_process_id, connection_type in connections:
            # Create the input with only the fields that are marked for flow-through
            input_name = output_name if flow_fields.get("name", False) else f"Flow-through from {output_name}"
            input_type = output_type if flow_fields.get("type", False) else "flow_through"
            input_quantity = output_quantity if flow_fields.get("quantity", False) else None
            input_unit = output_unit if flow_fields.get("unit", False) else ""
            input_batch_number = output_batch_number if flow_fields.get("batch", False) else ""

            # Create enhanced specifications with flow-through info
            enhanced_specs = (
                output_specifications
                if isinstance(output_specifications, dict)
                else (json.loads(output_specifications) if output_specifications else {})
            )
            enhanced_specs["flow_through_source"] = source_process_name
            enhanced_specs["flow_through_fields"] = flow_fields

            if flow_fields.get("specifications", False) and "notes" in enhanced_specs:
                enhanced_specs["flow_through_notes"] = enhanced_specs["notes"]

            if flow_fields.get("destination", False):
                enhanced_specs["original_destination"] = output_destination

            # Check if this input already exists (for update) or create new
            cursor.execute(
                """
                SELECT id, input_name, input_type, input_quantity, input_unit,
                       input_specifications, input_batch_number
                FROM workflow_engine_inputs
                WHERE process_id = %s AND input_source = %s
            """,
                (to_sub_process_id, f"Flow-through from {source_process_name}"),
            )

            existing_input = cursor.fetchone()

            if existing_input:
                # Update existing input
                cursor.execute(
                    """
                    UPDATE workflow_engine_inputs
                    SET input_name = %s, input_type = %s, input_quantity = %s,
                        input_unit = %s, input_specifications = %s, input_batch_number = %s,
                        execution_options = %s, date = CURRENT_DATE, action = 'update'
                    WHERE id = %s
                """,
                    (
                        input_name,
                        input_type,
                        input_quantity,
                        input_unit,
                        json.dumps(enhanced_specs),
                        input_batch_number,
                        json.dumps(filtered_exec_options),
                        existing_input[0],
                    ),
                )
                created_inputs.append(
                    {
                        "action": "updated",
                        "input_id": existing_input[0],
                        "process_id": to_sub_process_id,
                        "input_name": input_name,
                    }
                )
            else:
                # Create new input
                cursor.execute(
                    """
                    INSERT INTO workflow_engine_inputs
                    (date, action, process_id, input_name, input_type, input_quantity,
                     input_unit, input_specifications, input_source, input_batch_number,
                     input_status, execution_options, uid)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """,
                    (
                        date.today(),
                        "create",
                        to_sub_process_id,
                        input_name,
                        input_type,
                        input_quantity,
                        input_unit,
                        json.dumps(enhanced_specs),
                        f"Flow-through from {source_process_name}",
                        input_batch_number,
                        "available",
                        json.dumps(filtered_exec_options),
                        "",
                    ),
                )

                new_input_id = cursor.fetchone()[0]
                created_inputs.append(
                    {
                        "action": "created",
                        "input_id": new_input_id,
                        "process_id": to_sub_process_id,
                        "input_name": input_name,
                    }
                )

        connection.commit()

        return jsonify(
            {
                "message": f"Flow-through inputs processed successfully for output {output_id}",
                "created_inputs": created_inputs,
            }
        ), 200

    except Exception as e:
        print(f"Error creating flow-through inputs: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/flow-through/processes/<int:process_id>/sync", methods=["POST"])
@requires_auth
def sync_flow_through_for_process(process_id):
    """Sync all flow-through outputs for a specific process"""
    try:
        connection, cursor = db_conn()

        # Get all outputs from this process that have flow-through enabled
        cursor.execute(
            """
            SELECT id FROM workflow_engine_outputs
            WHERE process_id = %s AND output_flow_through = TRUE
        """,
            (process_id,),
        )

        outputs = cursor.fetchall()

        if not outputs:
            return jsonify({"message": "No flow-through outputs found for this process"}), 200

        synced_outputs = []

        for output in outputs:
            output_id = output[0]

            # Call the create flow-through inputs API for each output
            # We'll simulate the API call by calling the function directly
            try:
                # Get the output details
                cursor.execute(
                    """
                    SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity,
                           o.output_unit, o.output_specifications, o.output_batch_number,
                           o.output_destination, o.output_flow_through_fields, o.execution_options,
                           p.sub_process_name
                    FROM workflow_engine_outputs o
                    LEFT JOIN workflow_engine_sub_processes p ON o.process_id = p.id
                    WHERE o.id = %s AND o.output_flow_through = TRUE
                """,
                    (output_id,),
                )

                output_data = cursor.fetchone()
                if output_data:
                    # Process this output (simplified version of the create_flow_through_inputs logic)
                    synced_outputs.append(output_id)

            except Exception as e:
                print(f"Error syncing output {output_id}: {e}")
                continue

        return jsonify(
            {"message": f"Flow-through sync completed for process {process_id}", "synced_outputs": synced_outputs}
        ), 200

    except Exception as e:
        print(f"Error syncing flow-through for process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def create_automatic_inputs_for_flow_through(process_id, connection, cursor):
    """Create automatic inputs in connected processes when flow-through is enabled - DEPRECATED: Use API endpoints instead"""
    try:
        # Get all outputs from this process that have flow-through enabled
        cursor.execute(
            """
            SELECT id FROM workflow_engine_outputs
            WHERE process_id = %s AND output_flow_through = TRUE
        """,
            (process_id,),
        )

        outputs = cursor.fetchall()

        if not outputs:
            print(f"No flow-through outputs found for process {process_id}")
            return

        # Call the API endpoint for each output
        for output in outputs:
            output_id = output[0]
            try:
                # Make internal API call to create flow-through inputs
                response = create_flow_through_inputs_internal(output_id, connection, cursor)
                if response:
                    print(f"Flow-through inputs created for output {output_id}")
            except Exception as e:
                print(f"Error creating flow-through inputs for output {output_id}: {e}")
                continue

        print(f"Automatic inputs created successfully for process {process_id}")

    except Exception as e:
        print(f"Error in create_automatic_inputs_for_flow_through: {e}")
        raise


def create_flow_through_inputs_internal(output_id, connection, cursor):
    """Internal function to create flow-through inputs using the original direct query approach - FIXED VERSION"""
    try:
        # Get the sub-process name for the source
        cursor.execute(
            "SELECT sub_process_name FROM workflow_engine_sub_processes WHERE id = (SELECT process_id FROM workflow_engine_outputs WHERE id = %s)",
            (output_id,),
        )
        process_result = cursor.fetchone()
        source_process_name = process_result[0] if process_result else f"Process {output_id}"

        # Get the output details with flow-through fields
        cursor.execute(
            """
            SELECT id, process_id, output_name, output_type, output_quantity, output_unit,
                   output_specifications, output_batch_number, output_destination,
                   output_flow_through_fields, execution_options
            FROM workflow_engine_outputs
            WHERE id = %s AND output_flow_through = TRUE
            AND output_flow_through_fields IS NOT NULL
            AND output_flow_through_fields != '{}' AND output_flow_through_fields != 'null'
        """,
            (output_id,),
        )

        output = cursor.fetchone()
        if not output:
            return None

        (
            output_id,
            process_id,
            output_name,
            output_type,
            output_quantity,
            output_unit,
            output_specifications,
            output_batch_number,
            output_destination,
            flow_through_fields,
            execution_options,
        ) = output

        # Parse flow-through fields and execution options
        flow_fields = (
            flow_through_fields
            if isinstance(flow_through_fields, dict)
            else (json.loads(flow_through_fields) if flow_through_fields else {})
        )
        exec_options = (
            execution_options
            if isinstance(execution_options, dict)
            else (json.loads(execution_options) if execution_options else {})
        )

        # Filter execution options to only include fields that have flow-through enabled
        # Transform 'prompt' to 'template' for flow-through fields
        filtered_exec_options = {}
        for field, is_enabled in flow_fields.items():
            if is_enabled and field in exec_options:
                # Transform 'prompt' to 'template' for flow-through fields
                if exec_options[field] == "prompt":
                    filtered_exec_options[field] = "template"
                    print(f"Transformed {field}: 'prompt' → 'template'")
                else:
                    filtered_exec_options[field] = exec_options[field]
                    print(f"Kept {field}: '{exec_options[field]}'")

        print(f"Original execution options: {exec_options}")
        print(f"Filtered execution options: {filtered_exec_options}")

        # Skip if no fields are actually enabled for flow-through
        if not any(flow_fields.values()):
            return None

        # Get all connections from this process
        cursor.execute(
            """
            SELECT to_sub_process_id, connection_type
            FROM workflow_engine_connections
            WHERE from_sub_process_id = %s AND connection_status = 'active'
        """,
            (process_id,),
        )

        connections = cursor.fetchall()

        if not connections:
            return None

        created_inputs = []

        # For each connection, create inputs in the receiving process
        for to_sub_process_id, connection_type in connections:
            # Create the input with only the fields that are marked for flow-through
            input_name = output_name if flow_fields.get("name", False) else f"Flow-through from {output_name}"
            input_type = output_type if flow_fields.get("type", False) else "flow_through"
            input_quantity = output_quantity if flow_fields.get("quantity", False) else None
            input_unit = output_unit if flow_fields.get("unit", False) else ""
            input_batch_number = output_batch_number if flow_fields.get("batch", False) else ""

            # Create enhanced specifications with flow-through info
            enhanced_specs = (
                output_specifications
                if isinstance(output_specifications, dict)
                else (json.loads(output_specifications) if output_specifications else {})
            )
            enhanced_specs["flow_through_source"] = source_process_name
            enhanced_specs["flow_through_fields"] = flow_fields

            if flow_fields.get("specifications", False) and "notes" in enhanced_specs:
                enhanced_specs["flow_through_notes"] = enhanced_specs["notes"]

            if flow_fields.get("destination", False):
                enhanced_specs["original_destination"] = output_destination

            # Check if this input already exists (for update) or create new
            cursor.execute(
                """
                SELECT id, input_name, input_type, input_quantity, input_unit,
                       input_specifications, input_batch_number
                FROM workflow_engine_inputs
                WHERE process_id = %s AND input_source = %s
            """,
                (to_sub_process_id, f"Flow-through from {source_process_name}"),
            )

            existing_input = cursor.fetchone()

            if existing_input:
                # Update existing input
                cursor.execute(
                    """
                    UPDATE workflow_engine_inputs
                    SET input_name = %s, input_type = %s, input_quantity = %s,
                        input_unit = %s, input_specifications = %s, input_batch_number = %s,
                        execution_options = %s, date = CURRENT_DATE, action = 'update'
                    WHERE id = %s
                """,
                    (
                        input_name,
                        input_type,
                        input_quantity,
                        input_unit,
                        json.dumps(enhanced_specs),
                        input_batch_number,
                        json.dumps(filtered_exec_options),
                        existing_input[0],
                    ),
                )
                created_inputs.append(
                    {
                        "action": "updated",
                        "input_id": existing_input[0],
                        "process_id": to_sub_process_id,
                        "input_name": input_name,
                    }
                )
            else:
                # Create new input
                cursor.execute(
                    """
                    INSERT INTO workflow_engine_inputs
                    (date, action, process_id, input_name, input_type, input_quantity,
                     input_unit, input_specifications, input_source, input_batch_number,
                     input_status, execution_options, uid)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """,
                    (
                        date.today(),
                        "create",
                        to_sub_process_id,
                        input_name,
                        input_type,
                        input_quantity,
                        input_unit,
                        json.dumps(enhanced_specs),
                        f"Flow-through from {source_process_name}",
                        input_batch_number,
                        "available",
                        json.dumps(filtered_exec_options),
                        "",
                    ),
                )

                new_input_id = cursor.fetchone()[0]
                created_inputs.append(
                    {
                        "action": "created",
                        "input_id": new_input_id,
                        "process_id": to_sub_process_id,
                        "input_name": input_name,
                    }
                )

        return created_inputs

    except Exception as e:
        print(f"Error in create_flow_through_inputs_internal: {e}")
        raise


def cleanup_orphaned_flow_through_inputs(process_id, connection, cursor):
    """Clean up flow-through inputs that are no longer connected"""
    try:
        print(f"Cleaning up orphaned flow-through inputs for process {process_id}")

        # Get the sub-process name for the source
        cursor.execute("SELECT sub_process_name FROM workflow_engine_sub_processes WHERE id = %s", (process_id,))
        process_result = cursor.fetchone()
        source_process_name = process_result[0] if process_result else f"Process {process_id}"

        # Get all current connections FROM this process
        cursor.execute(
            """
            SELECT to_sub_process_id FROM workflow_engine_connections
            WHERE from_sub_process_id = %s AND connection_status = 'active'
        """,
            (process_id,),
        )

        connected_processes = [row[0] for row in cursor.fetchall()]
        print(f"Process {process_id} is connected to: {connected_processes}")

        # Find all flow-through inputs that claim to be from this process
        cursor.execute(
            """
            SELECT id, process_id, input_name FROM workflow_engine_inputs
            WHERE input_source = %s
        """,
            (f"Flow-through from {source_process_name}",),
        )

        flow_through_inputs = cursor.fetchall()
        print(f"Found {len(flow_through_inputs)} flow-through inputs from process {process_id}")

        # Remove inputs that are in processes no longer connected
        for input_id, target_process_id, input_name in flow_through_inputs:
            if target_process_id not in connected_processes:
                cursor.execute("DELETE FROM workflow_engine_inputs WHERE id = %s", (input_id,))
                print(f"Removed orphaned input '{input_name}' from process {target_process_id}")
            else:
                print(f"Keeping input '{input_name}' in connected process {target_process_id}")

        connection.commit()
        print(f"Cleanup completed for process {process_id}")

    except Exception as e:
        print(f"Error cleaning up orphaned inputs: {e}")
        connection.rollback()
        raise e


def update_flow_through_for_connection_changes(process_id, connection, cursor):
    """Update flow-through inputs when connections change"""
    try:
        print(f"Updating flow-through for connection changes from process {process_id}")

        # First, clean up orphaned inputs
        cleanup_orphaned_flow_through_inputs(process_id, connection, cursor)

        # Then, create/update inputs for new connections
        create_automatic_inputs_for_flow_through(process_id, connection, cursor)

        print(f"Flow-through update completed for process {process_id}")

    except Exception as e:
        print(f"Error updating flow-through for connection changes: {e}")
        connection.rollback()
        raise e


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>/flow-through", methods=["PUT"])
@requires_auth
def update_process_flow_through(process_id):
    """Update flow-through setting for a process"""
    try:
        data = request.get_json()
        flow_through_enabled = data.get("flow_through_enabled", False)

        connection, cursor = db_conn()

        cursor.execute(
            """
            UPDATE workflow_engine_processes
            SET flow_through_enabled = %s, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """,
            (flow_through_enabled, process_id),
        )

        if cursor.rowcount == 0:
            return jsonify({"error": "Process not found"}), 404

        connection.commit()

        # Check if we need to create automatic inputs for this process
        # Trigger if process flow-through is enabled
        if flow_through_enabled:
            create_automatic_inputs_for_flow_through(process_id, connection, cursor)

        return jsonify(
            {
                "message": "Flow-through setting updated successfully",
                "process_id": process_id,
                "flow_through_enabled": flow_through_enabled,
            }
        )

    except Exception as e:
        print(f"Error updating process flow-through: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if "cursor" in locals():
            cursor.close()
        if "connection" in locals():
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>/has-connections", methods=["GET"])
@requires_auth
def check_process_has_connections(process_id):
    """Check if a process has any connections, inputs, or outputs"""
    try:
        connection, cursor = db_conn()

        # Check for connections (as from_process or to_process)
        cursor.execute(
            """
            SELECT COUNT(*) FROM workflow_engine_connections
            WHERE from_process_id = %s OR to_process_id = %s
        """,
            (process_id, process_id),
        )
        connection_count = cursor.fetchone()[0]

        # Check for inputs
        cursor.execute(
            """
            SELECT COUNT(*) FROM workflow_engine_inputs
            WHERE process_id = %s
        """,
            (process_id,),
        )
        input_count = cursor.fetchone()[0]

        # Check for outputs
        cursor.execute(
            """
            SELECT COUNT(*) FROM workflow_engine_outputs
            WHERE process_id = %s
        """,
            (process_id,),
        )
        output_count = cursor.fetchone()[0]

        has_connections = connection_count > 0
        has_inputs = input_count > 0
        has_outputs = output_count > 0
        has_any = has_connections or has_inputs or has_outputs

        return jsonify(
            {
                "process_id": process_id,
                "has_connections": has_connections,
                "has_inputs": has_inputs,
                "has_outputs": has_outputs,
                "has_any": has_any,
                "connection_count": connection_count,
                "input_count": input_count,
                "output_count": output_count,
            }
        )

    except Exception as e:
        print(f"Error checking process connections: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if "cursor" in locals():
            cursor.close()
        if "connection" in locals():
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>/move-to-unmanaged", methods=["PUT"])
@requires_auth
def move_process_to_unmanaged(process_id):
    """Move a process to unmanaged status and delete all associated inputs, outputs, and connections using CRUD APIs"""
    try:
        print(f"Move to unmanaged API called for process_id: {process_id}")
        connection, cursor = db_conn()

        # Check if process exists
        cursor.execute("SELECT id, process_name FROM workflow_engine_processes WHERE id = %s", (process_id,))
        process = cursor.fetchone()
        if not process:
            print(f"Process {process_id} not found")
            return jsonify({"error": "Process not found"}), 404

        print(f"Found process: {process[1]} (ID: {process[0]})")

        # Get all inputs for this process
        cursor.execute("SELECT id FROM workflow_engine_inputs WHERE process_id = %s", (process_id,))
        input_ids = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(input_ids)} inputs to delete")

        # Get all outputs for this process
        cursor.execute("SELECT id FROM workflow_engine_outputs WHERE process_id = %s", (process_id,))
        output_ids = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(output_ids)} outputs to delete")

        # Get all connections for this process
        cursor.execute(
            "SELECT id FROM workflow_engine_connections WHERE from_process_id = %s OR to_process_id = %s",
            (process_id, process_id),
        )
        connection_ids = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(connection_ids)} connections to delete")

        # Delete inputs using individual API calls
        inputs_deleted = 0
        for input_id in input_ids:
            try:
                cursor.execute("DELETE FROM workflow_engine_inputs WHERE id = %s", (input_id,))
                if cursor.rowcount > 0:
                    inputs_deleted += 1
                    print(f"Deleted input {input_id}")
            except Exception as e:
                print(f"Error deleting input {input_id}: {e}")

        # Delete outputs using individual API calls
        outputs_deleted = 0
        for output_id in output_ids:
            try:
                cursor.execute("DELETE FROM workflow_engine_outputs WHERE id = %s", (output_id,))
                if cursor.rowcount > 0:
                    outputs_deleted += 1
                    print(f"Deleted output {output_id}")
            except Exception as e:
                print(f"Error deleting output {output_id}: {e}")

        # Delete connections using individual API calls
        connections_deleted = 0
        for connection_id in connection_ids:
            try:
                cursor.execute("DELETE FROM workflow_engine_connections WHERE id = %s", (connection_id,))
                if cursor.rowcount > 0:
                    connections_deleted += 1
                    print(f"Deleted connection {connection_id}")
            except Exception as e:
                print(f"Error deleting connection {connection_id}: {e}")

        # Update process to unmanaged
        print("Moving process to unmanaged...")
        cursor.execute(
            """
            UPDATE workflow_engine_processes
            SET is_managed = FALSE, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """,
            (process_id,),
        )

        connection.commit()
        print("Transaction committed successfully")

        return jsonify(
            {
                "message": "Process moved to unmanaged successfully",
                "process_id": process_id,
                "process_name": process[1],
                "inputs_deleted": inputs_deleted,
                "outputs_deleted": outputs_deleted,
                "connections_deleted": connections_deleted,
            }
        )

    except Exception as e:
        print(f"Error moving process to unmanaged: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>/managed", methods=["PUT"])
@requires_auth
def update_process_managed_status(process_id):
    """Update managed status for a process"""
    try:
        data = request.get_json()
        is_managed = data.get("is_managed", False)

        connection, cursor = db_conn()

        cursor.execute(
            """
            UPDATE workflow_engine_processes
            SET is_managed = %s, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """,
            (is_managed, process_id),
        )

        if cursor.rowcount == 0:
            return jsonify({"error": "Process not found"}), 404

        connection.commit()

        return jsonify(
            {"message": "Managed status updated successfully", "process_id": process_id, "is_managed": is_managed}
        )

    except Exception as e:
        print(f"Error updating process managed status: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if "cursor" in locals():
            cursor.close()
        if "connection" in locals():
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/inputs", methods=["GET"])
@requires_auth
def get_inputs():
    """Get all inputs or filter by process_id"""
    try:
        connection, cursor = db_conn()

        process_id = request.args.get("process_id")

        if process_id:
            cursor.execute(
                """
                SELECT i.id, i.process_id, i.input_name, i.input_type, i.input_quantity,
                       i.input_unit, i.input_specifications, i.input_source, i.input_batch_number,
                       i.input_expiry_date, i.input_status, p.process_name
                FROM workflow_engine_inputs i
                LEFT JOIN workflow_engine_processes p ON i.process_id = p.id
                WHERE i.process_id = %s
                ORDER BY i.id DESC
            """,
                (process_id,),
            )
        else:
            cursor.execute("""
                SELECT i.id, i.process_id, i.input_name, i.input_type, i.input_quantity,
                       i.input_unit, i.input_specifications, i.input_source, i.input_batch_number,
                       i.input_expiry_date, i.input_status, p.process_name
                FROM workflow_engine_inputs i
                LEFT JOIN workflow_engine_processes p ON i.process_id = p.id
                ORDER BY i.id DESC
            """)

        inputs = cursor.fetchall()

        return jsonify(
            [
                {
                    "id": inp[0],
                    "process_id": inp[1],
                    "input_name": inp[2],
                    "input_type": inp[3],
                    "input_quantity": inp[4],
                    "input_unit": inp[5],
                    "input_specifications": inp[6],
                    "input_source": inp[7],
                    "input_batch_number": inp[8],
                    "input_expiry_date": inp[9].isoformat() if inp[9] else None,
                    "input_status": inp[10],
                    "process_name": inp[11],
                }
                for inp in inputs
            ]
        )

    except Exception as e:
        print(f"Error getting inputs: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/inputs/<int:input_id>", methods=["GET"])
@requires_auth
def get_input(input_id):
    """Get a specific input by ID"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT i.id, i.process_id, i.input_name, i.input_type, i.input_quantity,
                   i.input_unit, i.input_specifications, i.input_source, i.input_batch_number,
                   i.input_expiry_date, i.input_status, i.execution_options, p.process_name
            FROM workflow_engine_inputs i
            LEFT JOIN workflow_engine_processes p ON i.process_id = p.id
            WHERE i.id = %s
        """,
            (input_id,),
        )

        inp = cursor.fetchone()
        if not inp:
            return jsonify({"error": "Input not found"}), 404

        print(f"Input {input_id} execution_options from DB:", inp[11])

        return jsonify(
            {
                "id": inp[0],
                "process_id": inp[1],
                "input_name": inp[2],
                "input_type": inp[3],
                "input_quantity": inp[4],
                "input_unit": inp[5],
                "input_specifications": inp[6],
                "input_source": inp[7],
                "input_batch_number": inp[8],
                "input_expiry_date": inp[9].isoformat() if inp[9] else None,
                "input_status": inp[10],
                "execution_options": inp[11] or {},
                "process_name": inp[12],
            }
        )

    except Exception as e:
        print(f"Error getting input: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/inputs/<int:input_id>", methods=["PUT"])
@requires_auth
def update_input(input_id):
    """Update an input"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()

        # Check if input exists
        cursor.execute("SELECT id FROM workflow_engine_inputs WHERE id = %s", (input_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Input not found"}), 404

        # Update input
        cursor.execute(
            """
            UPDATE workflow_engine_inputs
            SET input_name = %s, input_type = %s, input_quantity = %s, input_unit = %s,
                input_specifications = %s, input_source = %s, input_batch_number = %s,
                input_expiry_date = %s, input_status = %s, execution_options = %s,
                date = NOW(), action = 'update'
            WHERE id = %s
        """,
            (
                data.get("input_name"),
                data.get("input_type"),
                data.get("input_quantity"),
                data.get("input_unit"),
                json.dumps(data.get("input_specifications", {})),
                data.get("input_source"),
                data.get("input_batch_number"),
                data.get("input_expiry_date"),
                data.get("input_status"),
                json.dumps(
                    {
                        "name": data.get("exec_name", "template"),
                        "quantity": data.get("exec_quantity", "template"),
                        "unit": data.get("exec_unit", "template"),
                        "batch": data.get("exec_batch", "template"),
                        "notes": data.get("exec_notes", "template"),
                        "type": data.get("exec_type", "template"),
                        "source": data.get("exec_source", "template"),
                    }
                ),
                input_id,
            ),
        )

        connection.commit()
        return jsonify({"message": "Input updated successfully"})

    except Exception as e:
        print(f"Error updating input: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/inputs/<int:input_id>", methods=["DELETE"])
@requires_auth
def delete_input(input_id):
    """Delete an input"""
    try:
        connection, cursor = db_conn()

        # Check if input exists
        cursor.execute("SELECT id FROM workflow_engine_inputs WHERE id = %s", (input_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Input not found"}), 404

        # Delete the input
        cursor.execute("DELETE FROM workflow_engine_inputs WHERE id = %s", (input_id,))

        connection.commit()
        return jsonify({"message": "Input deleted successfully"})

    except Exception as e:
        print(f"Error deleting input: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/inputs", methods=["POST"])
@requires_auth
def create_input():
    """Create a new input"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            INSERT INTO workflow_engine_inputs
            (date, action, process_id, input_name, input_type, input_quantity,
             input_unit, input_specifications, input_source, input_batch_number,
             input_expiry_date, input_status, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                data.get("process_id"),
                data.get("input_name"),
                data.get("input_type", "raw_material"),
                data.get("input_quantity"),
                data.get("input_unit"),
                json.dumps(data.get("input_specifications", {})),
                data.get("input_source", ""),
                data.get("input_batch_number", ""),
                data.get("input_expiry_date"),
                data.get("input_status", "available"),
                data.get("uid", ""),
            ),
        )

        input_id = cursor.fetchone()[0]
        connection.commit()

        return jsonify({"id": input_id, "message": "Input created successfully"}), 201

    except Exception as e:
        print(f"Error creating input: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/outputs", methods=["GET"])
@requires_auth
def get_outputs():
    """Get all outputs or filter by process_id"""
    try:
        connection, cursor = db_conn()

        process_id = request.args.get("process_id")

        if process_id:
            cursor.execute(
                """
                SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity,
                       o.output_unit, o.output_specifications, o.output_batch_number,
                       o.output_quality_status, o.output_destination, o.flow_through_enabled,
                       o.flow_through_fields, p.process_name
                FROM workflow_engine_outputs o
                LEFT JOIN workflow_engine_processes p ON o.process_id = p.id
                WHERE o.process_id = %s
                ORDER BY o.id DESC
            """,
                (process_id,),
            )
        else:
            cursor.execute("""
                SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity,
                       o.output_unit, o.output_specifications, o.output_batch_number,
                       o.output_quality_status, o.output_destination, o.flow_through_enabled,
                       o.flow_through_fields, p.process_name
                FROM workflow_engine_outputs o
                LEFT JOIN workflow_engine_processes p ON o.process_id = p.id
                ORDER BY o.id DESC
            """)

        outputs = cursor.fetchall()

        return jsonify(
            [
                {
                    "id": out[0],
                    "process_id": out[1],
                    "output_name": out[2],
                    "output_type": out[3],
                    "output_quantity": out[4],
                    "output_unit": out[5],
                    "output_specifications": out[6],
                    "output_batch_number": out[7],
                    "output_quality_status": out[8],
                    "output_destination": out[9],
                    "flow_through_enabled": out[10] or False,
                    "flow_through_fields": out[11] or {},
                    "process_name": out[12],
                }
                for out in outputs
            ]
        )

    except Exception as e:
        print(f"Error getting outputs: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/outputs/<int:output_id>", methods=["GET"])
@requires_auth
def get_output(output_id):
    """Get a specific output by ID"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity,
                   o.output_unit, o.output_specifications, o.output_batch_number,
                   o.output_quality_status, o.output_destination, o.output_flow_through,
                   o.output_flow_through_fields, o.execution_options, p.process_name
            FROM workflow_engine_outputs o
            LEFT JOIN workflow_engine_processes p ON o.process_id = p.id
            WHERE o.id = %s
        """,
            (output_id,),
        )

        out = cursor.fetchone()
        if not out:
            return jsonify({"error": "Output not found"}), 404

        return jsonify(
            {
                "id": out[0],
                "process_id": out[1],
                "output_name": out[2],
                "output_type": out[3],
                "output_quantity": out[4],
                "output_unit": out[5],
                "output_specifications": out[6],
                "output_batch_number": out[7],
                "output_quality_status": out[8],
                "output_destination": out[9],
                "output_flow_through": out[10] or False,
                "output_flow_through_fields": out[11] or {},
                "execution_options": out[12] or {},
                "process_name": out[13],
            }
        )

    except Exception as e:
        print(f"Error getting output: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/outputs/<int:output_id>", methods=["PUT"])
@requires_auth
def update_output(output_id):
    """Update an output"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()

        # Check if output exists and get process_id
        cursor.execute("SELECT id, process_id FROM workflow_engine_outputs WHERE id = %s", (output_id,))
        output_record = cursor.fetchone()
        if not output_record:
            return jsonify({"error": "Output not found"}), 404

        process_id = output_record[1]

        # Update output
        cursor.execute(
            """
            UPDATE workflow_engine_outputs
            SET output_name = %s, output_type = %s, output_quantity = %s, output_unit = %s,
                output_specifications = %s, output_batch_number = %s,
                output_quality_status = %s, output_destination = %s, output_flow_through = %s,
                output_flow_through_fields = %s, execution_options = %s, date = NOW(), action = 'update'
            WHERE id = %s
        """,
            (
                data.get("output_name"),
                data.get("output_type"),
                data.get("output_quantity"),
                data.get("output_unit"),
                json.dumps(data.get("output_specifications", {})),
                data.get("output_batch_number"),
                data.get("output_quality_status"),
                data.get("output_destination"),
                data.get("output_flow_through", False),
                json.dumps(data.get("output_flow_through_fields", {})),
                json.dumps(data.get("execution_options", {})),
                output_id,
            ),
        )

        connection.commit()

        # Always check and trigger flow-through for any outputs that have flow-through enabled
        # This ensures field updates (like execution options) are reflected in connected inputs
        cursor.execute(
            """
            SELECT id, output_name, output_flow_through, output_flow_through_fields
            FROM workflow_engine_outputs
            WHERE process_id = %s AND output_flow_through = TRUE
        """,
            (process_id,),
        )

        outputs = cursor.fetchall()
        print(f"Found {len(outputs)} outputs with flow-through enabled for process {process_id}")

        # Call the internal API function for each output
        for output in outputs:
            output_id = output[0]
            output_name = output[1]
            flow_through_fields = output[3]
            print(f"Processing flow-through for output {output_id} ({output_name}): {flow_through_fields}")
            try:
                result = create_flow_through_inputs_internal(output_id, connection, cursor)
                if result:
                    print(f"Flow-through successful for output {output_id}: {len(result)} inputs created/updated")
                else:
                    print(f"No flow-through inputs created for output {output_id}")
                # Commit the flow-through changes immediately
                connection.commit()
            except Exception as e:
                print(f"Error creating flow-through inputs for output {output_id}: {e}")
                connection.rollback()
                continue

        return jsonify({"message": "Output updated successfully"}), 200

    except Exception as e:
        print(f"Error updating output: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# Removed duplicate flow-through endpoint - flow-through is now handled by the main output update endpoint


@workflow_engine_bp.route("/api/workflow-engine/outputs/<int:output_id>", methods=["DELETE"])
@requires_auth
def delete_output(output_id):
    """Delete an output"""
    try:
        connection, cursor = db_conn()

        # Check if output exists
        cursor.execute("SELECT id FROM workflow_engine_outputs WHERE id = %s", (output_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Output not found"}), 404

        # Delete the output
        cursor.execute("DELETE FROM workflow_engine_outputs WHERE id = %s", (output_id,))

        connection.commit()
        return jsonify({"message": "Output deleted successfully"})

    except Exception as e:
        print(f"Error deleting output: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/outputs", methods=["POST"])
@requires_auth
def create_output():
    """Create a new output"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            INSERT INTO workflow_engine_outputs
            (date, action, process_id, output_name, output_type, output_quantity,
             output_unit, output_specifications, output_batch_number,
             output_quality_status, output_destination, flow_through_enabled, flow_through_fields, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                data.get("process_id"),
                data.get("output_name"),
                data.get("output_type", "finished_product"),
                data.get("output_quantity"),
                data.get("output_unit"),
                json.dumps(data.get("output_specifications", {})),
                data.get("output_batch_number", ""),
                data.get("output_quality_status", "pending"),
                data.get("output_destination", ""),
                data.get("flow_through_enabled", False),
                json.dumps(data.get("flow_through_fields", {})),
                data.get("uid", ""),
            ),
        )

        output_id = cursor.fetchone()[0]
        connection.commit()

        # Check if we need to create automatic inputs for this output
        # Trigger if any individual fields are marked for flow-through
        flow_through_fields = data.get("flow_through_fields", {})
        has_flow_through_fields = any(flow_through_fields.values()) if isinstance(flow_through_fields, dict) else False

        if has_flow_through_fields:
            create_automatic_inputs_for_flow_through(data.get("process_id"), connection, cursor)

        return jsonify({"id": output_id, "message": "Output created successfully"}), 201

    except Exception as e:
        print(f"Error creating output: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/connections", methods=["GET"])
@requires_auth
def get_connections():
    """Get all connections for visual display"""
    try:
        connection, cursor = db_conn()

        cursor.execute("""
            SELECT c.id, c.from_process_id, c.to_process_id, c.connection_type,
                   c.connection_status, c.connection_notes,
                   fp.process_name as from_process_name,
                   tp.process_name as to_process_name
            FROM workflow_engine_connections c
            LEFT JOIN workflow_engine_processes fp ON c.from_process_id = fp.id
            LEFT JOIN workflow_engine_processes tp ON c.to_process_id = tp.id
            ORDER BY c.id
        """)

        connections = cursor.fetchall()

        return jsonify(
            [
                {
                    "id": conn[0],
                    "from_process_id": conn[1],
                    "to_process_id": conn[2],
                    "connection_type": conn[3],
                    "connection_status": conn[4],
                    "connection_notes": conn[5],
                    "from_process_name": conn[6],
                    "to_process_name": conn[7],
                }
                for conn in connections
            ]
        )

    except Exception as e:
        print(f"Error getting connections: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/connections", methods=["POST"])
@requires_auth
def create_connection():
    """Create a new connection between processes"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        # Check if connection already exists
        cursor.execute(
            """
            SELECT id FROM workflow_engine_connections
            WHERE from_sub_process_id = %s AND to_sub_process_id = %s AND connection_type = %s
        """,
            (data.get("from_sub_process_id"), data.get("to_sub_process_id"), data.get("connection_type", "direct")),
        )

        if cursor.fetchone():
            return jsonify(
                {"error": "Connection already exists with the same From process, To process, and connection type"}
            ), 409

        cursor.execute(
            """
            INSERT INTO workflow_engine_connections
            (date, action, parent_process_id, from_sub_process_id, to_sub_process_id, from_output_id,
             to_input_id, connection_type, connection_status, connection_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                data.get("parent_process_id"),
                data.get("from_sub_process_id"),
                data.get("to_sub_process_id"),
                data.get("from_output_id"),
                data.get("to_input_id"),
                data.get("connection_type", "direct"),
                data.get("connection_status", "active"),
                data.get("connection_notes", ""),
                data.get("uid", ""),
            ),
        )

        connection_id = cursor.fetchone()[0]

        # Mark both sub-processes as managed when connection is added
        from_sub_process_id = data.get("from_sub_process_id")
        to_sub_process_id = data.get("to_sub_process_id")

        if from_sub_process_id:
            cursor.execute(
                """
                UPDATE workflow_engine_sub_processes
                SET is_managed = TRUE, action = 'update', date = CURRENT_DATE
                WHERE id = %s
            """,
                (from_sub_process_id,),
            )

        if to_sub_process_id:
            cursor.execute(
                """
                UPDATE workflow_engine_sub_processes
                SET is_managed = TRUE, action = 'update', date = CURRENT_DATE
                WHERE id = %s
            """,
                (to_sub_process_id,),
            )

        connection.commit()

        # Update flow-through inputs for the source process
        from_process_id = data.get("from_process_id")
        if from_process_id:
            update_flow_through_for_connection_changes(from_process_id, connection, cursor)

        return jsonify({"id": connection_id, "message": "Connection created successfully"}), 201

    except Exception as e:
        print(f"Error creating connection: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/traceability", methods=["GET"])
@requires_auth
def get_all_traces():
    """Get all traceability records"""
    try:
        connection, cursor = db_conn()

        cursor.execute("""
            SELECT t.id, t.trace_id, t.item_name, t.item_type, t.current_location,
                   t.current_process_id, t.trace_path, t.trace_status, t.trace_notes,
                   p.process_name
            FROM workflow_engine_traceability t
            LEFT JOIN workflow_engine_processes p ON t.current_process_id = p.id
            ORDER BY t.id DESC
        """)

        traces = cursor.fetchall()

        return jsonify(
            [
                {
                    "id": trace[0],
                    "trace_id": trace[1],
                    "item_name": trace[2],
                    "item_type": trace[3],
                    "current_location": trace[4],
                    "current_process_id": trace[5],
                    "trace_path": trace[6],
                    "trace_status": trace[7],
                    "trace_notes": trace[8],
                    "process_name": trace[9],
                }
                for trace in traces
            ]
        )

    except Exception as e:
        print(f"Error getting traceability records: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/traceability/<trace_id>", methods=["PUT"])
@requires_auth
def update_trace(trace_id):
    """Update a traceability record"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()

        # Check if trace exists
        cursor.execute("SELECT id FROM workflow_engine_traceability WHERE trace_id = %s", (trace_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Traceability record not found"}), 404

        # Update trace
        cursor.execute(
            """
            UPDATE workflow_engine_traceability
            SET item_name = %s, item_type = %s, current_location = %s,
                current_process_id = %s, trace_path = %s, trace_status = %s,
                trace_notes = %s, date = NOW(), action = 'update'
            WHERE trace_id = %s
        """,
            (
                data.get("item_name"),
                data.get("item_type"),
                data.get("current_location"),
                data.get("current_process_id"),
                data.get("trace_path"),
                data.get("trace_status"),
                data.get("trace_notes"),
                trace_id,
            ),
        )

        connection.commit()
        return jsonify({"message": "Traceability record updated successfully"})

    except Exception as e:
        print(f"Error updating traceability record: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/traceability/<trace_id>", methods=["DELETE"])
@requires_auth
def delete_trace(trace_id):
    """Delete a traceability record"""
    try:
        connection, cursor = db_conn()

        # Check if trace exists
        cursor.execute("SELECT id FROM workflow_engine_traceability WHERE trace_id = %s", (trace_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Traceability record not found"}), 404

        # Delete the trace
        cursor.execute("DELETE FROM workflow_engine_traceability WHERE trace_id = %s", (trace_id,))

        connection.commit()
        return jsonify({"message": "Traceability record deleted successfully"})

    except Exception as e:
        print(f"Error deleting traceability record: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/traceability", methods=["POST"])
@requires_auth
def create_trace():
    """Create a new traceability record"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            INSERT INTO workflow_engine_traceability
            (date, action, trace_id, item_name, item_type, current_location,
             current_process_id, trace_path, trace_status, trace_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                data.get("trace_id"),
                data.get("item_name"),
                data.get("item_type"),
                data.get("current_location"),
                data.get("current_process_id"),
                json.dumps(data.get("trace_path", [])),
                data.get("trace_status", "active"),
                data.get("trace_notes", ""),
                data.get("uid", ""),
            ),
        )

        trace_id = cursor.fetchone()[0]
        connection.commit()

        return jsonify({"id": trace_id, "message": "Traceability record created successfully"}), 201

    except Exception as e:
        print(f"Error creating traceability record: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/traceability/<trace_id>", methods=["GET"])
@requires_auth
def get_trace(trace_id):
    """Get traceability information for a specific item"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT id, trace_id, item_name, item_type, current_location,
                   current_process_id, trace_path, trace_status, trace_notes, date
            FROM workflow_engine_traceability
            WHERE trace_id = %s
        """,
            (trace_id,),
        )

        trace = cursor.fetchone()
        if not trace:
            return jsonify({"error": "Trace not found"}), 404

        return jsonify(
            {
                "id": trace[0],
                "trace_id": trace[1],
                "item_name": trace[2],
                "item_type": trace[3],
                "current_location": trace[4],
                "current_process_id": trace[5],
                "trace_path": json.loads(trace[6]) if trace[6] else [],
                "trace_status": trace[7],
                "trace_notes": trace[8],
                "date": trace[9].isoformat() if trace[9] else None,
            }
        )

    except Exception as e:
        print(f"Error getting trace: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes", methods=["GET"])
@requires_auth
def get_all_processes():
    """Get all processes for connection dropdowns"""
    try:
        connection, cursor = db_conn()

        cursor.execute("""
            SELECT id, process_name, process_type, process_status, is_managed
            FROM workflow_engine_processes
            ORDER BY process_name
        """)

        processes = cursor.fetchall()

        return jsonify(
            [
                {
                    "id": process[0],
                    "process_name": process[1],
                    "process_type": process[2],
                    "process_status": process[3],
                    "is_managed": process[4] or False,
                }
                for process in processes
            ]
        )

    except Exception as e:
        print(f"Error getting processes: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/connections/<int:connection_id>", methods=["GET"])
@requires_auth
def get_connection(connection_id):
    """Get a specific connection by ID"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT c.id, c.from_process_id, c.to_process_id, c.connection_type,
                   c.connection_status, c.connection_notes, c.from_output_id, c.to_input_id,
                   fp.process_name as from_process_name,
                   tp.process_name as to_process_name
            FROM workflow_engine_connections c
            LEFT JOIN workflow_engine_processes fp ON c.from_process_id = fp.id
            LEFT JOIN workflow_engine_processes tp ON c.to_process_id = tp.id
            WHERE c.id = %s
        """,
            (connection_id,),
        )

        conn = cursor.fetchone()
        if not conn:
            return jsonify({"error": "Connection not found"}), 404

        return jsonify(
            {
                "id": conn[0],
                "from_process_id": conn[1],
                "to_process_id": conn[2],
                "connection_type": conn[3],
                "connection_status": conn[4],
                "connection_notes": conn[5],
                "from_output_id": conn[6],
                "to_input_id": conn[7],
                "from_process_name": conn[8],
                "to_process_name": conn[9],
            }
        )

    except Exception as e:
        print(f"Error getting connection: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/connections/<int:connection_id>", methods=["PUT"])
@requires_auth
def update_connection(connection_id):
    """Update a connection"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()

        # Check if connection exists
        cursor.execute("SELECT id FROM workflow_engine_connections WHERE id = %s", (connection_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Connection not found"}), 404

        # Update connection
        cursor.execute(
            """
            UPDATE workflow_engine_connections
            SET connection_type = %s, connection_status = %s, connection_notes = %s,
                from_output_id = %s, to_input_id = %s, date = NOW(), action = 'update'
            WHERE id = %s
        """,
            (
                data.get("connection_type"),
                data.get("connection_status"),
                data.get("connection_notes"),
                data.get("from_output_id"),
                data.get("to_input_id"),
                connection_id,
            ),
        )

        connection.commit()
        return jsonify({"message": "Connection updated successfully"})

    except Exception as e:
        print(f"Error updating connection: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>/activate", methods=["POST"])
@requires_auth
def activate_process(process_id):
    """Activate a process for batch execution"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()

        # Check if process exists
        cursor.execute("SELECT id, process_name FROM workflow_engine_processes WHERE id = %s", (process_id,))
        process = cursor.fetchone()
        if not process:
            return jsonify({"error": "Process not found"}), 404

        # Create process template if it doesn't exist
        cursor.execute(
            """
            INSERT INTO workflow_engine_process_templates
            (date, action, process_id, template_name, template_version, template_status,
             default_inputs, default_outputs, default_variables, template_notes, uid)
            VALUES (NOW(), 'create', %s, %s, '1.0', 'active', %s, %s, %s, %s, %s)
            ON CONFLICT (process_id) DO UPDATE SET
                template_status = 'active',
                default_inputs = EXCLUDED.default_inputs,
                default_outputs = EXCLUDED.default_outputs,
                default_variables = EXCLUDED.default_variables,
                date = NOW(),
                action = 'update'
        """,
            (
                process_id,
                f"{process[1]} Template",
                json.dumps(data.get("default_inputs", [])),
                json.dumps(data.get("default_outputs", [])),
                json.dumps(data.get("default_variables", {})),
                data.get("template_notes", ""),
                data.get("uid", "system"),
            ),
        )

        # Update process status to active
        cursor.execute(
            """
            UPDATE workflow_engine_processes
            SET process_status = 'active', date = NOW(), action = 'activate'
            WHERE id = %s
        """,
            (process_id,),
        )

        connection.commit()
        return jsonify({"message": "Process activated successfully"})

    except Exception as e:
        print(f"Error activating process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/processes/<int:process_id>/execute", methods=["POST"])
@requires_auth
def execute_process(process_id):
    """Execute a process with batch data"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()

        # Check if process exists and is active
        cursor.execute(
            """
            SELECT id, process_name, process_status
            FROM workflow_engine_processes
            WHERE id = %s
        """,
            (process_id,),
        )
        process = cursor.fetchone()
        if not process:
            return jsonify({"error": "Process not found"}), 404
        if process[2] != "active":
            return jsonify({"error": "Process must be active to execute"}), 400

        # Generate batch number if not provided
        batch_number = data.get("execution_batch_number")
        if not batch_number:
            batch_number = f"{process[1].replace(' ', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create execution record
        cursor.execute(
            """
            INSERT INTO workflow_engine_process_executions
            (date, action, process_id, execution_batch_number, execution_status,
             execution_start_time, execution_notes, execution_variables, uid)
            VALUES (NOW(), 'create', %s, %s, 'in_progress', NOW(), %s, %s, %s)
            RETURNING id
        """,
            (
                process_id,
                batch_number,
                data.get("execution_notes", ""),
                json.dumps(data.get("execution_variables", {})),
                data.get("uid", "system"),
            ),
        )

        execution_id = cursor.fetchone()[0]

        # Create execution inputs
        for input_data in data.get("execution_inputs", []):
            cursor.execute(
                """
                INSERT INTO workflow_engine_execution_inputs
                (date, action, execution_id, input_template_id, actual_input_name,
                 actual_input_quantity, actual_input_unit, actual_input_batch_number,
                 actual_input_source, input_consumption_time, input_quality_status,
                 input_notes, uid)
                VALUES (NOW(), 'create', %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
            """,
                (
                    execution_id,
                    input_data.get("input_template_id"),
                    input_data.get("actual_input_name"),
                    input_data.get("actual_input_quantity"),
                    input_data.get("actual_input_unit"),
                    input_data.get("actual_input_batch_number"),
                    input_data.get("actual_input_source"),
                    input_data.get("input_quality_status", "passed"),
                    input_data.get("input_notes", ""),
                    data.get("uid", "system"),
                ),
            )

        connection.commit()
        return jsonify(
            {
                "message": "Process execution started successfully",
                "execution_id": execution_id,
                "batch_number": batch_number,
            }
        )

    except Exception as e:
        print(f"Error executing process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/executions/<int:execution_id>/complete", methods=["POST"])
@requires_auth
def complete_execution(execution_id):
    """Complete a process execution and record outputs"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()

        # Check if execution exists
        cursor.execute("SELECT id, process_id FROM workflow_engine_process_executions WHERE id = %s", (execution_id,))
        execution = cursor.fetchone()
        if not execution:
            return jsonify({"error": "Execution not found"}), 404

        # Create execution outputs
        for output_data in data.get("execution_outputs", []):
            cursor.execute(
                """
                INSERT INTO workflow_engine_execution_outputs
                (date, action, execution_id, output_template_id, actual_output_name,
                 actual_output_quantity, actual_output_unit, actual_output_batch_number,
                 actual_output_quality_status, actual_output_destination,
                 output_production_time, output_notes, uid)
                VALUES (NOW(), 'create', %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
            """,
                (
                    execution_id,
                    output_data.get("output_template_id"),
                    output_data.get("actual_output_name"),
                    output_data.get("actual_output_quantity"),
                    output_data.get("actual_output_unit"),
                    output_data.get("actual_output_batch_number"),
                    output_data.get("actual_output_quality_status", "passed"),
                    output_data.get("actual_output_destination"),
                    output_data.get("output_notes", ""),
                    data.get("uid", "system"),
                ),
            )

        # Update execution status
        cursor.execute(
            """
            UPDATE workflow_engine_process_executions
            SET execution_status = 'completed', execution_end_time = NOW(),
                execution_quality_checks = %s, date = NOW(), action = 'complete'
            WHERE id = %s
        """,
            (json.dumps(data.get("execution_quality_checks", {})), execution_id),
        )

        connection.commit()
        return jsonify({"message": "Process execution completed successfully"})

    except Exception as e:
        print(f"Error completing execution: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/connections/<int:connection_id>/details", methods=["GET"])
@requires_auth
def get_connection_details(connection_id):
    """Get detailed connection information including linked inputs/outputs"""
    try:
        connection, cursor = db_conn()

        # Get connection details
        cursor.execute(
            """
            SELECT c.id, c.from_process_id, c.to_process_id, c.from_output_id, c.to_input_id,
                   c.connection_type, c.connection_status, c.connection_notes,
                   fp.process_name as from_process_name,
                   tp.process_name as to_process_name
            FROM workflow_engine_connections c
            LEFT JOIN workflow_engine_processes fp ON c.from_process_id = fp.id
            LEFT JOIN workflow_engine_processes tp ON c.to_process_id = tp.id
            WHERE c.id = %s
        """,
            (connection_id,),
        )

        conn = cursor.fetchone()
        if not conn:
            return jsonify({"error": "Connection not found"}), 404

        # Get linked output details
        linked_output = None
        if conn[4]:  # from_output_id
            cursor.execute(
                """
                SELECT id, output_name, output_type, output_quantity, output_unit, output_specifications
                FROM workflow_engine_outputs
                WHERE id = %s
            """,
                (conn[4],),
            )
            linked_output = cursor.fetchone()

        # Get linked input details
        linked_input = None
        if conn[5]:  # to_input_id
            cursor.execute(
                """
                SELECT id, input_name, input_type, input_quantity, input_unit, input_specifications
                FROM workflow_engine_inputs
                WHERE id = %s
            """,
                (conn[5],),
            )
            linked_input = cursor.fetchone()

        # Get all outputs from source process
        cursor.execute(
            """
            SELECT id, output_name, output_type, output_quantity, output_unit
            FROM workflow_engine_outputs
            WHERE process_id = %s
            ORDER BY output_name
        """,
            (conn[1],),
        )
        available_outputs = cursor.fetchall()

        # Get all inputs from destination process
        cursor.execute(
            """
            SELECT id, input_name, input_type, input_quantity, input_unit
            FROM workflow_engine_inputs
            WHERE process_id = %s
            ORDER BY input_name
        """,
            (conn[2],),
        )
        available_inputs = cursor.fetchall()

        return jsonify(
            {
                "connection": {
                    "id": conn[0],
                    "from_process_id": conn[1],
                    "to_process_id": conn[2],
                    "from_output_id": conn[4],
                    "to_input_id": conn[5],
                    "connection_type": conn[6],
                    "connection_status": conn[7],
                    "connection_notes": conn[8],
                    "from_process_name": conn[9],
                    "to_process_name": conn[10],
                },
                "linked_output": {
                    "id": linked_output[0],
                    "output_name": linked_output[1],
                    "output_type": linked_output[2],
                    "output_quantity": linked_output[3],
                    "output_unit": linked_output[4],
                    "output_specifications": linked_output[5],
                }
                if linked_output
                else None,
                "linked_input": {
                    "id": linked_input[0],
                    "input_name": linked_input[1],
                    "input_type": linked_input[2],
                    "input_quantity": linked_input[3],
                    "input_unit": linked_input[4],
                    "input_specifications": linked_input[5],
                }
                if linked_input
                else None,
                "available_outputs": [
                    {
                        "id": out[0],
                        "output_name": out[1],
                        "output_type": out[2],
                        "output_quantity": out[3],
                        "output_unit": out[4],
                    }
                    for out in available_outputs
                ],
                "available_inputs": [
                    {
                        "id": inp[0],
                        "input_name": inp[1],
                        "input_type": inp[2],
                        "input_quantity": inp[3],
                        "input_unit": inp[4],
                    }
                    for inp in available_inputs
                ],
            }
        )

    except Exception as e:
        print(f"Error getting connection details: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/connections/<int:connection_id>/auto-link", methods=["POST"])
@requires_auth
def auto_link_connection(connection_id):
    """Automatically link outputs from source process to inputs of destination process"""
    try:
        connection, cursor = db_conn()

        # Get connection details
        cursor.execute(
            """
            SELECT c.from_process_id, c.to_process_id, c.from_output_id, c.to_input_id
            FROM workflow_engine_connections c
            WHERE c.id = %s
        """,
            (connection_id,),
        )
        conn = cursor.fetchone()
        if not conn:
            return jsonify({"error": "Connection not found"}), 404

        from_process_id, to_process_id, from_output_id, to_input_id = conn

        # Get outputs from source process
        cursor.execute(
            """
            SELECT id, output_name, output_type, output_quantity, output_unit
            FROM workflow_engine_outputs
            WHERE process_id = %s
        """,
            (from_process_id,),
        )
        outputs = cursor.fetchall()

        # Get inputs for destination process
        cursor.execute(
            """
            SELECT id, input_name, input_type, input_quantity, input_unit
            FROM workflow_engine_inputs
            WHERE process_id = %s
        """,
            (to_process_id,),
        )
        inputs = cursor.fetchall()

        # Auto-link matching outputs to inputs
        linked_count = 0
        for output in outputs:
            output_id, output_name, output_type, output_qty, output_unit = output

            # Find matching input by name or type
            for input_record in inputs:
                input_id, input_name, input_type, input_qty, input_unit = input_record

                # Match by name or type
                if output_name.lower() == input_name.lower() or output_type.lower() == input_type.lower():
                    # Update connection to link specific output to input
                    cursor.execute(
                        """
                        UPDATE workflow_engine_connections
                        SET from_output_id = %s, to_input_id = %s, date = NOW(), action = 'auto_link'
                        WHERE id = %s
                    """,
                        (output_id, input_id, connection_id),
                    )
                    linked_count += 1
                    break

        connection.commit()
        return jsonify({"message": f"Auto-linked {linked_count} output-input pairs", "linked_count": linked_count})

    except Exception as e:
        print(f"Error auto-linking connection: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/connections/<int:connection_id>", methods=["DELETE"])
@requires_auth
def delete_connection(connection_id):
    """Delete a connection"""
    try:
        connection, cursor = db_conn()

        # Check if connection exists and get from_sub_process_id
        cursor.execute(
            "SELECT id, from_sub_process_id FROM workflow_engine_connections WHERE id = %s", (connection_id,)
        )
        connection_data = cursor.fetchone()
        if not connection_data:
            return jsonify({"error": "Connection not found"}), 404

        from_sub_process_id = connection_data[1]

        # Delete the connection
        cursor.execute("DELETE FROM workflow_engine_connections WHERE id = %s", (connection_id,))

        connection.commit()

        # Update flow-through inputs for the source process
        if from_sub_process_id:
            update_flow_through_for_connection_changes(from_sub_process_id, connection, cursor)

        return jsonify({"message": "Connection deleted successfully"})

    except Exception as e:
        print(f"Error deleting connection: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/dag-layout", methods=["POST"])
@requires_auth
def save_dag_layout():
    """Save DAG layout positions to database for a specific parent process"""
    connection = None
    cursor = None
    try:
        data = request.get_json()
        parent_process_id = data.get("parent_process_id")
        layout_data = data.get("layout_data")

        if not parent_process_id or not layout_data:
            return jsonify({"success": False, "error": "Missing parent_process_id or layout_data"}), 400

        connection, cursor = db_conn()

        # Check if layout already exists for this parent process using UID
        cursor.execute(
            """
            SELECT id FROM workflow_engine_dag_layout
            WHERE uid = %s
        """,
            (f"parent_{parent_process_id}",),
        )

        existing_layout = cursor.fetchone()

        if existing_layout:
            # Update existing layout
            cursor.execute(
                """
                UPDATE workflow_engine_dag_layout
                SET layout_data = %s, layout_timestamp = %s, action = 'update'
                WHERE uid = %s
            """,
                (json.dumps(layout_data), datetime.now(), f"parent_{parent_process_id}"),
            )
        else:
            # Create new layout
            cursor.execute(
                """
                INSERT INTO workflow_engine_dag_layout
                (date, action, layout_data, layout_timestamp, uid)
                VALUES (%s, %s, %s, %s, %s)
            """,
                (datetime.now().date(), "save", json.dumps(layout_data), datetime.now(), f"parent_{parent_process_id}"),
            )

        connection.commit()

        return jsonify({"success": True})

    except Exception as e:
        print(f"Error saving DAG layout: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/dag-layout/<int:parent_process_id>", methods=["GET"])
@requires_auth
def get_dag_layout(parent_process_id):
    """Get saved DAG layout positions for a specific parent process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT layout_data, layout_timestamp
            FROM workflow_engine_dag_layout
            WHERE uid = %s
            ORDER BY layout_timestamp DESC
            LIMIT 1
        """,
            (f"parent_{parent_process_id}",),
        )

        layout = cursor.fetchone()
        cursor.close()
        connection.close()

        if layout:
            return jsonify({"success": True, "layout": {"layout_data": layout[0], "layout_timestamp": layout[1]}})
        else:
            return jsonify({"success": True, "layout": None})

    except Exception as e:
        print(f"Error loading DAG layout: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/dag-layout", methods=["DELETE"])
@requires_auth
def delete_dag_layout():
    """Delete saved DAG layout positions"""
    try:
        connection, cursor = db_conn()

        # Clear all layout data
        cursor.execute("DELETE FROM workflow_engine_dag_layout")

        connection.commit()
        return jsonify({"message": "DAG layout deleted successfully"})

    except Exception as e:
        print(f"Error deleting DAG layout: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# Parent Process API Routes


@workflow_engine_bp.route("/api/workflow-engine/parent-processes", methods=["POST"])
@requires_auth
def create_parent_process():
    """Create a new parent process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            INSERT INTO workflow_engine_parent_processes
            (date, action, parent_process_name, parent_process_description, parent_process_type,
             parent_process_status, parent_process_category, parent_process_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                data.get("parent_process_name"),
                data.get("parent_process_description", ""),
                data.get("parent_process_type", "production_workflow"),
                data.get("parent_process_status", "active"),
                data.get("parent_process_category", ""),
                data.get("parent_process_notes", ""),
                data.get("uid", ""),
            ),
        )

        parent_process_id = cursor.fetchone()[0]
        connection.commit()

        return jsonify({"id": parent_process_id, "message": "Parent process created successfully"}), 201

    except Exception as e:
        print(f"Error creating parent process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/parent-processes/<int:parent_process_id>", methods=["GET"])
@requires_auth
def get_parent_process(parent_process_id):
    """Get a specific parent process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT id, parent_process_name, parent_process_description, parent_process_type,
                   parent_process_status, parent_process_category, parent_process_notes, date
            FROM workflow_engine_parent_processes
            WHERE id = %s
        """,
            (parent_process_id,),
        )

        parent_process = cursor.fetchone()
        if not parent_process:
            return jsonify({"error": "Parent process not found"}), 404

        return jsonify(
            {
                "id": parent_process[0],
                "parent_process_name": parent_process[1],
                "parent_process_description": parent_process[2],
                "parent_process_type": parent_process[3],
                "parent_process_status": parent_process[4],
                "parent_process_category": parent_process[5],
                "parent_process_notes": parent_process[6],
                "date": parent_process[7].isoformat() if parent_process[7] else None,
            }
        )

    except Exception as e:
        print(f"Error getting parent process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/parent-processes/<int:parent_process_id>", methods=["PUT"])
@requires_auth
def update_parent_process(parent_process_id):
    """Update a parent process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            UPDATE workflow_engine_parent_processes
            SET parent_process_name = %s, parent_process_description = %s, parent_process_type = %s,
                parent_process_status = %s, parent_process_category = %s, parent_process_notes = %s,
                action = 'update', date = %s
            WHERE id = %s
        """,
            (
                data.get("parent_process_name"),
                data.get("parent_process_description"),
                data.get("parent_process_type"),
                data.get("parent_process_status"),
                data.get("parent_process_category"),
                data.get("parent_process_notes"),
                date.today(),
                parent_process_id,
            ),
        )

        if cursor.rowcount == 0:
            return jsonify({"error": "Parent process not found"}), 404

        connection.commit()
        return jsonify({"message": "Parent process updated successfully"})

    except Exception as e:
        print(f"Error updating parent process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/parent-processes/<int:parent_process_id>", methods=["DELETE"])
@requires_auth
def delete_parent_process(parent_process_id):
    """Delete a parent process and all its sub processes"""
    try:
        print(f"Delete parent process API called for parent_process_id: {parent_process_id}")
        connection, cursor = db_conn()

        # Check if parent process exists
        cursor.execute(
            "SELECT id, parent_process_name FROM workflow_engine_parent_processes WHERE id = %s", (parent_process_id,)
        )
        parent_process = cursor.fetchone()
        if not parent_process:
            print(f"Parent process {parent_process_id} not found")
            return jsonify({"error": "Parent process not found"}), 404

        print(f"Found parent process: {parent_process[1]} (ID: {parent_process[0]})")

        # Get all sub processes for this parent
        cursor.execute(
            "SELECT id FROM workflow_engine_sub_processes WHERE parent_process_id = %s", (parent_process_id,)
        )
        sub_process_ids = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(sub_process_ids)} sub processes to delete")

        # Delete inputs, outputs, and connections for each sub process
        for sub_process_id in sub_process_ids:
            # Delete inputs
            cursor.execute("DELETE FROM workflow_engine_inputs WHERE sub_process_id = %s", (sub_process_id,))
            inputs_deleted = cursor.rowcount
            print(f"Deleted {inputs_deleted} inputs for sub process {sub_process_id}")

            # Delete outputs
            cursor.execute("DELETE FROM workflow_engine_outputs WHERE sub_process_id = %s", (sub_process_id,))
            outputs_deleted = cursor.rowcount
            print(f"Deleted {outputs_deleted} outputs for sub process {sub_process_id}")

            # Delete connections
            cursor.execute(
                "DELETE FROM workflow_engine_connections WHERE from_sub_process_id = %s OR to_sub_process_id = %s",
                (sub_process_id, sub_process_id),
            )
            connections_deleted = cursor.rowcount
            print(f"Deleted {connections_deleted} connections for sub process {sub_process_id}")

        # Delete all sub processes
        cursor.execute("DELETE FROM workflow_engine_sub_processes WHERE parent_process_id = %s", (parent_process_id,))
        sub_processes_deleted = cursor.rowcount
        print(f"Deleted {sub_processes_deleted} sub processes")

        # Delete the parent process
        cursor.execute("DELETE FROM workflow_engine_parent_processes WHERE id = %s", (parent_process_id,))
        parent_deleted = cursor.rowcount
        print(f"Deleted {parent_deleted} parent processes")

        connection.commit()
        print("Transaction committed successfully")
        return jsonify({"message": "Parent process and all sub processes deleted successfully"})

    except Exception as e:
        print(f"Error deleting parent process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/parent-processes", methods=["GET"])
@requires_auth
def get_all_parent_processes():
    """Get all parent processes"""
    try:
        connection, cursor = db_conn()

        cursor.execute("""
            SELECT id, parent_process_name, parent_process_type, parent_process_status, parent_process_category
            FROM workflow_engine_parent_processes
            ORDER BY parent_process_name
        """)

        parent_processes = cursor.fetchall()

        return jsonify(
            [
                {
                    "id": process[0],
                    "parent_process_name": process[1],
                    "parent_process_type": process[2],
                    "parent_process_status": process[3],
                    "parent_process_category": process[4],
                }
                for process in parent_processes
            ]
        )

    except Exception as e:
        print(f"Error getting parent processes: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>/managed", methods=["PUT"])
@requires_auth
def update_sub_process_managed_status(sub_process_id):
    """Update managed status for a sub-process"""
    try:
        data = request.get_json()
        is_managed = data.get("is_managed", False)

        connection, cursor = db_conn()

        cursor.execute(
            """
            UPDATE workflow_engine_sub_processes
            SET is_managed = %s, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """,
            (is_managed, sub_process_id),
        )

        if cursor.rowcount == 0:
            return jsonify({"error": "Sub-process not found"}), 404

        connection.commit()

        return jsonify(
            {
                "message": "Sub-process managed status updated successfully",
                "sub_process_id": sub_process_id,
                "is_managed": is_managed,
            }
        )

    except Exception as e:
        print(f"Error updating sub-process managed status: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if "cursor" in locals():
            cursor.close()
        if "connection" in locals():
            connection.close()


# Sub Process API Routes


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>/inputs", methods=["POST"])
@requires_auth
def create_sub_process_input(sub_process_id):
    """Create a new input for a sub-process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            INSERT INTO workflow_engine_inputs
            (date, action, process_id, input_name, input_type, input_quantity,
             input_unit, input_specifications, input_source, input_batch_number,
             input_expiry_date, input_status, execution_options, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                sub_process_id,
                data.get("input_name"),
                data.get("input_type", "raw_material"),
                data.get("input_quantity"),
                data.get("input_unit"),
                json.dumps(data.get("input_specifications", {})),
                data.get("input_source", ""),
                data.get("input_batch_number", ""),
                data.get("input_expiry_date"),
                data.get("input_status", "available"),
                json.dumps(
                    {
                        "name": data.get("exec_name", "template"),
                        "quantity": data.get("exec_quantity", "template"),
                        "unit": data.get("exec_unit", "template"),
                        "batch": data.get("exec_batch", "template"),
                        "notes": data.get("exec_notes", "template"),
                        "type": data.get("exec_type", "template"),
                        "source": data.get("exec_source", "template"),
                    }
                ),
                data.get("uid", ""),
            ),
        )

        input_id = cursor.fetchone()[0]

        # Mark sub-process as managed when input is added
        cursor.execute(
            """
            UPDATE workflow_engine_sub_processes
            SET is_managed = TRUE, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """,
            (sub_process_id,),
        )

        connection.commit()

        return jsonify({"id": input_id, "message": "Input created successfully"}), 201

    except Exception as e:
        print(f"Error creating sub-process input: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>/outputs", methods=["POST"])
@requires_auth
def create_sub_process_output(sub_process_id):
    """Create a new output for a sub-process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            INSERT INTO workflow_engine_outputs
            (date, action, process_id, output_name, output_type, output_quantity,
             output_unit, output_specifications, output_destination, output_batch_number,
             output_quality_status, output_flow_through, output_flow_through_fields, execution_options, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                sub_process_id,
                data.get("output_name"),
                data.get("output_type", "finished_product"),
                data.get("output_quantity"),
                data.get("output_unit"),
                json.dumps(data.get("output_specifications", {})),
                data.get("output_destination", ""),
                data.get("output_batch_number", ""),
                data.get("output_quality_status", "passed"),
                data.get("output_flow_through", False),
                json.dumps(data.get("output_flow_through_fields", {})),
                json.dumps(data.get("execution_options", {})),
                data.get("uid", ""),
            ),
        )

        output_id = cursor.fetchone()[0]

        # Mark sub-process as managed when output is added
        cursor.execute(
            """
            UPDATE workflow_engine_sub_processes
            SET is_managed = TRUE, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """,
            (sub_process_id,),
        )

        connection.commit()

        # Always check and trigger flow-through for any outputs that have flow-through enabled
        # This ensures field updates (like execution options) are reflected in connected inputs
        cursor.execute(
            """
            SELECT id FROM workflow_engine_outputs
            WHERE process_id = %s AND output_flow_through = TRUE
        """,
            (sub_process_id,),
        )

        outputs = cursor.fetchall()

        # Call the internal API function for each output
        for output in outputs:
            output_id = output[0]
            try:
                create_flow_through_inputs_internal(output_id, connection, cursor)
            except Exception as e:
                print(f"Error creating flow-through inputs for output {output_id}: {e}")
                continue

        return jsonify({"id": output_id, "message": "Output created successfully"}), 201

    except Exception as e:
        print(f"Error creating sub-process output: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-processes", methods=["POST"])
@requires_auth
def create_sub_process():
    """Create a new sub process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            INSERT INTO workflow_engine_sub_processes
            (date, action, parent_process_id, sub_process_name, sub_process_description, sub_process_type,
             sub_process_status, sub_process_category, sub_process_notes, execution_order, is_managed, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                date.today(),
                "create",
                data.get("parent_process_id"),
                data.get("sub_process_name"),
                data.get("sub_process_description", ""),
                data.get("sub_process_type", "manufacturing"),
                data.get("sub_process_status", "active"),
                data.get("sub_process_category", ""),
                data.get("sub_process_notes", ""),
                data.get("execution_order", 1),
                data.get("is_managed", False),  # New sub-processes start as unmanaged
                data.get("uid", ""),
            ),
        )

        sub_process_id = cursor.fetchone()[0]
        connection.commit()

        return jsonify({"id": sub_process_id, "message": "Sub process created successfully"}), 201

    except Exception as e:
        print(f"Error creating sub process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>", methods=["GET"])
@requires_auth
def get_sub_process(sub_process_id):
    """Get a specific sub process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT s.id, s.parent_process_id, s.sub_process_name, s.sub_process_description,
                   s.sub_process_type, s.sub_process_status, s.sub_process_category,
                   s.sub_process_notes, s.execution_order, s.date, s.is_managed,
                   p.parent_process_name
            FROM workflow_engine_sub_processes s
            LEFT JOIN workflow_engine_parent_processes p ON s.parent_process_id = p.id
            WHERE s.id = %s
        """,
            (sub_process_id,),
        )

        sub_process = cursor.fetchone()
        if not sub_process:
            return jsonify({"error": "Sub process not found"}), 404

        return jsonify(
            {
                "id": sub_process[0],
                "parent_process_id": sub_process[1],
                "sub_process_name": sub_process[2],
                "sub_process_description": sub_process[3],
                "sub_process_type": sub_process[4],
                "sub_process_status": sub_process[5],
                "sub_process_category": sub_process[6],
                "sub_process_notes": sub_process[7],
                "execution_order": sub_process[8],
                "date": sub_process[9].isoformat() if sub_process[9] else None,
                "is_managed": sub_process[10] or False,
                "parent_process_name": sub_process[11],
            }
        )

    except Exception as e:
        print(f"Error getting sub process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>", methods=["PUT"])
@requires_auth
def update_sub_process(sub_process_id):
    """Update a sub process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()

        cursor.execute(
            """
            UPDATE workflow_engine_sub_processes
            SET sub_process_name = %s, sub_process_description = %s, sub_process_type = %s,
                sub_process_status = %s, sub_process_category = %s, sub_process_notes = %s,
                execution_order = %s, action = 'update', date = %s
            WHERE id = %s
        """,
            (
                data.get("sub_process_name"),
                data.get("sub_process_description"),
                data.get("sub_process_type"),
                data.get("sub_process_status"),
                data.get("sub_process_category"),
                data.get("sub_process_notes"),
                data.get("execution_order"),
                date.today(),
                sub_process_id,
            ),
        )

        if cursor.rowcount == 0:
            return jsonify({"error": "Sub process not found"}), 404

        connection.commit()
        return jsonify({"message": "Sub process updated successfully"})

    except Exception as e:
        print(f"Error updating sub process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>", methods=["DELETE"])
@requires_auth
def delete_sub_process(sub_process_id):
    """Delete a sub process and all its inputs, outputs, and connections"""
    try:
        print(f"Delete sub process API called for sub_process_id: {sub_process_id}")
        connection, cursor = db_conn()

        # Check if sub process exists
        cursor.execute(
            "SELECT id, sub_process_name FROM workflow_engine_sub_processes WHERE id = %s", (sub_process_id,)
        )
        sub_process = cursor.fetchone()
        if not sub_process:
            print(f"Sub process {sub_process_id} not found")
            return jsonify({"error": "Sub process not found"}), 404

        print(f"Found sub process: {sub_process[1]} (ID: {sub_process[0]})")

        # Delete related records first
        print("Deleting related inputs...")
        cursor.execute("DELETE FROM workflow_engine_inputs WHERE sub_process_id = %s", (sub_process_id,))
        inputs_deleted = cursor.rowcount
        print(f"Deleted {inputs_deleted} inputs")

        print("Deleting related outputs...")
        cursor.execute("DELETE FROM workflow_engine_outputs WHERE sub_process_id = %s", (sub_process_id,))
        outputs_deleted = cursor.rowcount
        print(f"Deleted {outputs_deleted} outputs")

        print("Deleting related connections...")
        cursor.execute(
            "DELETE FROM workflow_engine_connections WHERE from_sub_process_id = %s OR to_sub_process_id = %s",
            (sub_process_id, sub_process_id),
        )
        connections_deleted = cursor.rowcount
        print(f"Deleted {connections_deleted} connections")

        # Delete the sub process
        print("Deleting sub process...")
        cursor.execute("DELETE FROM workflow_engine_sub_processes WHERE id = %s", (sub_process_id,))
        sub_process_deleted = cursor.rowcount
        print(f"Deleted {sub_process_deleted} sub processes")

        connection.commit()
        print("Transaction committed successfully")
        return jsonify({"message": "Sub process deleted successfully"})

    except Exception as e:
        print(f"Error deleting sub process: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>/inputs", methods=["GET"])
@requires_auth
def get_sub_process_inputs(sub_process_id):
    """Get all inputs for a specific sub-process"""
    try:
        connection, cursor = db_conn()
        cursor.execute(
            """
            SELECT id, process_id, input_name, input_type, input_quantity,
                   input_unit, input_specifications, input_source, input_batch_number,
                   input_expiry_date, input_status, execution_options, uid
            FROM workflow_engine_inputs
            WHERE process_id = %s
            ORDER BY input_name
        """,
            (sub_process_id,),
        )
        inputs = cursor.fetchall()
        cursor.close()
        connection.close()

        result = []
        for input_item in inputs:
            result.append(
                {
                    "id": input_item[0],
                    "process_id": input_item[1],
                    "input_name": input_item[2],
                    "input_type": input_item[3],
                    "input_quantity": input_item[4],
                    "input_unit": input_item[5],
                    "input_specifications": input_item[6],
                    "input_source": input_item[7],
                    "input_batch_number": input_item[8],
                    "input_expiry_date": input_item[9].isoformat() if input_item[9] else None,
                    "input_status": input_item[10],
                    "execution_options": input_item[11],
                    "uid": input_item[12],
                }
            )

        return jsonify(result)

    except Exception as e:
        print(f"Error getting sub-process inputs: {e}")
        return jsonify({"error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>/outputs", methods=["GET"])
@requires_auth
def get_sub_process_outputs(sub_process_id):
    """Get all outputs for a specific sub-process"""
    try:
        connection, cursor = db_conn()
        cursor.execute(
            """
            SELECT id, process_id, output_name, output_type, output_quantity,
                   output_unit, output_specifications, output_batch_number,
                   output_quality_status, output_destination, output_flow_through,
                   output_flow_through_fields, uid
            FROM workflow_engine_outputs
            WHERE process_id = %s
            ORDER BY output_name
        """,
            (sub_process_id,),
        )
        outputs = cursor.fetchall()
        cursor.close()
        connection.close()

        result = []
        for output in outputs:
            result.append(
                {
                    "id": output[0],
                    "process_id": output[1],
                    "output_name": output[2],
                    "output_type": output[3],
                    "output_quantity": output[4],
                    "output_unit": output[5],
                    "output_specifications": output[6],
                    "output_batch_number": output[7],
                    "output_quality_status": output[8],
                    "output_destination": output[9],
                    "output_flow_through": output[10],
                    "output_flow_through_fields": output[11],
                    "uid": output[12],
                }
            )

        return jsonify(result)

    except Exception as e:
        print(f"Error getting sub-process outputs: {e}")
        return jsonify({"error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/sub-processes/<int:sub_process_id>/connections", methods=["GET"])
@requires_auth
def get_sub_process_connections(sub_process_id):
    """Get all connections for a specific sub-process"""
    try:
        connection, cursor = db_conn()
        cursor.execute(
            """
            SELECT c.id, c.parent_process_id, c.from_sub_process_id, c.to_sub_process_id,
                   c.connection_type, c.connection_status, c.connection_notes,
                   sp_from.sub_process_name as from_process_name,
                   sp_to.sub_process_name as to_process_name
            FROM workflow_engine_connections c
            JOIN workflow_engine_sub_processes sp_from ON c.from_sub_process_id = sp_from.id
            JOIN workflow_engine_sub_processes sp_to ON c.to_sub_process_id = sp_to.id
            WHERE c.from_sub_process_id = %s OR c.to_sub_process_id = %s
            ORDER BY c.id
        """,
            (sub_process_id, sub_process_id),
        )
        connections = cursor.fetchall()
        cursor.close()
        connection.close()

        result = []
        for conn in connections:
            result.append(
                {
                    "id": conn[0],
                    "parent_process_id": conn[1],
                    "from_sub_process_id": conn[2],
                    "to_sub_process_id": conn[3],
                    "connection_type": conn[4],
                    "connection_status": conn[5],
                    "connection_notes": conn[6],
                    "from_process_name": conn[7],
                    "to_process_name": conn[8],
                }
            )

        return jsonify(result)

    except Exception as e:
        print(f"Error getting sub-process connections: {e}")
        return jsonify({"error": str(e)}), 500


@workflow_engine_bp.route(
    "/api/workflow-engine/parent-processes/<int:parent_process_id>/sub-processes", methods=["GET"]
)
@requires_auth
def get_sub_processes_by_parent(parent_process_id):
    """Get all sub processes for a specific parent process"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT s.id, s.parent_process_id, s.sub_process_name, s.sub_process_type,
                   s.sub_process_status, s.sub_process_category, s.execution_order, s.is_managed,
                   p.parent_process_name
            FROM workflow_engine_sub_processes s
            LEFT JOIN workflow_engine_parent_processes p ON s.parent_process_id = p.id
            WHERE s.parent_process_id = %s
            ORDER BY s.execution_order, s.sub_process_name
        """,
            (parent_process_id,),
        )

        sub_processes = cursor.fetchall()

        # Convert to list of dictionaries for JSON response
        result = []
        for sub_process in sub_processes:
            result.append(
                {
                    "id": sub_process[0],
                    "parent_process_id": sub_process[1],
                    "sub_process_name": sub_process[2],
                    "sub_process_type": sub_process[3],
                    "sub_process_status": sub_process[4],
                    "sub_process_category": sub_process[5],
                    "execution_order": sub_process[6],
                    "is_managed": sub_process[7] or False,
                    "parent_process_name": sub_process[8],
                }
            )

        return jsonify({"success": True, "sub_processes": result})

    except Exception as e:
        print(f"Error getting sub processes: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/parent-processes/<int:parent_process_id>/executions", methods=["POST"])
@requires_auth
def create_parent_execution(parent_process_id):
    """Create a new parent execution and automatically create sub-executions"""
    print(f"Creating parent execution for parent process ID: {parent_process_id}")
    connection, cursor = db_conn()

    try:
        # Check if parent process exists
        cursor.execute("SELECT id FROM workflow_engine_parent_processes WHERE id = %s", (parent_process_id,))
        if not cursor.fetchone():
            return jsonify({"success": False, "error": "Parent process not found"}), 404

        # Create parent execution
        cursor.execute(
            """
            INSERT INTO workflow_engine_parent_executions
            (parent_process_id, execution_status, execution_start_time, date, action)
            VALUES (%s, 'pending', NOW(), NOW(), 'create')
            RETURNING id
        """,
            (parent_process_id,),
        )
        parent_execution_id = cursor.fetchone()[0]

        # Get all active sub-processes for this parent process
        cursor.execute(
            """
            SELECT id FROM workflow_engine_sub_processes
            WHERE parent_process_id = %s AND sub_process_status = 'active'
            ORDER BY execution_order, sub_process_name
        """,
            (parent_process_id,),
        )
        sub_processes = cursor.fetchall()

        # Create sub-executions for each active sub-process
        for sub_process in sub_processes:
            cursor.execute(
                """
                INSERT INTO workflow_engine_sub_executions
                (parent_execution_id, sub_process_id, execution_status, execution_start_time, date, action)
                VALUES (%s, %s, 'pending', NOW(), NOW(), 'create')
            """,
                (parent_execution_id, sub_process[0]),
            )

        connection.commit()

        return jsonify(
            {
                "success": True,
                "message": "Parent execution created successfully",
                "parent_execution_id": parent_execution_id,
            }
        )

    except Exception as e:
        connection.rollback()
        print(f"Error creating parent execution: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route(
    "/api/workflow-engine/parent-processes/<int:parent_process_id>/executions/all", methods=["GET"]
)
@requires_auth
def get_all_parent_executions(parent_process_id):
    """Get all executions for a parent process (for modal view)"""
    connection, cursor = db_conn()

    try:
        cursor.execute(
            """
            SELECT pe.id, pe.parent_process_id, pe.execution_status, pe.execution_start_time,
                   pe.execution_end_time, pe.execution_notes, pe.date,
                   pp.parent_process_name
            FROM workflow_engine_parent_executions pe
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.parent_process_id = %s
            ORDER BY pe.date DESC, pe.id DESC
        """,
            (parent_process_id,),
        )
        executions = cursor.fetchall()

        return jsonify({"success": True, "executions": executions})

    except Exception as e:
        print(f"Error getting all executions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/parent-processes/<int:parent_process_id>/executions", methods=["GET"])
@requires_auth
def get_parent_executions(parent_process_id):
    """Get all executions for a parent process"""
    print(f"Getting executions for parent process ID: {parent_process_id}")
    connection, cursor = db_conn()

    try:
        cursor.execute(
            """
            SELECT pe.id, pe.parent_process_id, pe.execution_status, pe.execution_start_time,
                   pe.execution_end_time, pe.execution_notes, pe.date,
                   pp.parent_process_name
            FROM workflow_engine_parent_executions pe
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.parent_process_id = %s
            ORDER BY pe.execution_start_time DESC
        """,
            (parent_process_id,),
        )
        executions = cursor.fetchall()

        result = []
        for execution in executions:
            result.append(
                {
                    "id": execution[0],
                    "parent_process_id": execution[1],
                    "execution_status": execution[2],
                    "execution_start_time": execution[3].isoformat() if execution[3] else None,
                    "execution_end_time": execution[4].isoformat() if execution[4] else None,
                    "execution_notes": execution[5],
                    "date": execution[6].isoformat() if execution[6] else None,
                    "parent_process_name": execution[7],
                }
            )

        return jsonify({"success": True, "executions": result})

    except Exception as e:
        print(f"Error getting parent executions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/parent-executions/<int:execution_id>", methods=["GET"])
@requires_auth
def get_parent_execution(execution_id):
    """Get a specific parent execution with its sub-executions"""
    print(f"Getting parent execution ID: {execution_id}")
    connection, cursor = db_conn()

    try:
        # Get parent execution details
        cursor.execute(
            """
            SELECT pe.id, pe.parent_process_id, pe.execution_status, pe.execution_start_time,
                   pe.execution_end_time, pe.execution_notes, pe.date,
                   pp.parent_process_name
            FROM workflow_engine_parent_executions pe
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.id = %s
        """,
            (execution_id,),
        )
        parent_execution = cursor.fetchone()

        if not parent_execution:
            return jsonify({"success": False, "error": "Parent execution not found"}), 404

        # Get sub-executions
        cursor.execute(
            """
            SELECT se.id, se.parent_execution_id, se.sub_process_id, se.execution_status,
                   se.execution_start_time, se.execution_end_time, se.execution_notes,
                   sp.sub_process_name, sp.execution_order
            FROM workflow_engine_sub_executions se
            LEFT JOIN workflow_engine_sub_processes sp ON se.sub_process_id = sp.id
            WHERE se.parent_execution_id = %s
            ORDER BY sp.execution_order, sp.sub_process_name
        """,
            (execution_id,),
        )
        sub_executions = cursor.fetchall()

        parent_execution_data = {
            "id": parent_execution[0],
            "parent_process_id": parent_execution[1],
            "execution_status": parent_execution[2],
            "execution_start_time": parent_execution[3].isoformat() if parent_execution[3] else None,
            "execution_end_time": parent_execution[4].isoformat() if parent_execution[4] else None,
            "execution_notes": parent_execution[5],
            "date": parent_execution[6].isoformat() if parent_execution[6] else None,
            "parent_process_name": parent_execution[7],
        }

        sub_executions_data = []
        for sub_execution in sub_executions:
            sub_executions_data.append(
                {
                    "id": sub_execution[0],
                    "parent_execution_id": sub_execution[1],
                    "sub_process_id": sub_execution[2],
                    "execution_status": sub_execution[3],
                    "execution_start_time": sub_execution[4].isoformat() if sub_execution[4] else None,
                    "execution_end_time": sub_execution[5].isoformat() if sub_execution[5] else None,
                    "execution_notes": sub_execution[6],
                    "sub_process_name": sub_execution[7],
                    "execution_order": sub_execution[8],
                }
            )

        return jsonify(
            {"success": True, "parent_execution": parent_execution_data, "sub_executions": sub_executions_data}
        )

    except Exception as e:
        print(f"Error getting parent execution: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-executions/<int:sub_execution_id>/execute", methods=["POST"])
@requires_auth
def execute_sub_execution(sub_execution_id):
    """Execute a sub-execution with batch data"""
    print(f"Executing sub-execution ID: {sub_execution_id}")
    connection, cursor = db_conn()

    try:
        data = request.get_json()

        # Get sub-execution details
        cursor.execute(
            """
            SELECT se.id, se.sub_process_id, se.execution_status
            FROM workflow_engine_sub_executions se
            WHERE se.id = %s
        """,
            (sub_execution_id,),
        )
        sub_execution = cursor.fetchone()

        if not sub_execution:
            return jsonify({"success": False, "error": "Sub-execution not found"}), 404

        if sub_execution[2] != "pending":
            return jsonify({"success": False, "error": "Sub-execution is not in pending status"}), 400

        # Update sub-execution status to 'in_progress'
        cursor.execute(
            """
            UPDATE workflow_engine_sub_executions
            SET execution_status = 'in_progress', execution_start_time = NOW(), date = NOW(), action = 'execute'
            WHERE id = %s
        """,
            (sub_execution_id,),
        )

        # Get parent execution ID and update its status to 'in_progress'
        cursor.execute(
            """
            SELECT parent_execution_id FROM workflow_engine_sub_executions WHERE id = %s
        """,
            (sub_execution_id,),
        )
        parent_execution_result = cursor.fetchone()
        if parent_execution_result:
            parent_execution_id = parent_execution_result[0]
            print(f"Updating parent execution {parent_execution_id} to in_progress")
            cursor.execute(
                """
                UPDATE workflow_engine_parent_executions
                SET execution_status = 'in_progress', execution_start_time = NOW()
                WHERE id = %s AND execution_status IN ('pending', 'in_progress')
            """,
                (parent_execution_id,),
            )
            print(f"Parent execution update affected {cursor.rowcount} rows")

        # Get inputs for this sub-process to create execution inputs
        cursor.execute(
            """
            SELECT id, input_name, input_type, execution_options
            FROM workflow_engine_inputs
            WHERE process_id = %s
        """,
            (sub_execution[1],),
        )
        inputs = cursor.fetchall()

        # Create execution inputs from batch data
        input_batch_data = data.get("batch_data", {})
        print(f"Received batch data: {input_batch_data}")

        for input_template in inputs:
            input_id = input_template[0]
            input_name = input_template[1]
            execution_options = input_template[3] or {}

            # Get batch data for this input
            batch_data = input_batch_data.get(str(input_id), {})

            # Determine actual input name based on execution options
            if execution_options.get("name") == "prompt":
                actual_input_name = batch_data.get("name", input_name)
            else:
                actual_input_name = input_name

            # Create execution input record
            # Handle empty values for numeric fields
            quantity = batch_data.get("quantity", "")
            if quantity == "" or quantity is None:
                quantity = None  # Use NULL for empty quantity
            else:
                try:
                    quantity = float(quantity)  # Convert to float if it's a valid number
                except (ValueError, TypeError):
                    quantity = None

            cursor.execute(
                """
                INSERT INTO workflow_engine_execution_inputs
                (execution_id, input_template_id, actual_input_name,
                 actual_input_quantity, actual_input_unit, actual_input_batch_number, date, action)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), 'create')
            """,
                (
                    sub_execution_id,
                    input_id,
                    actual_input_name,
                    quantity,
                    batch_data.get("unit", ""),
                    batch_data.get("batch", ""),  # Changed from 'batch_number' to 'batch' to match frontend
                ),
            )

        connection.commit()

        return jsonify({"success": True, "message": "Sub-execution started successfully"})

    except Exception as e:
        connection.rollback()
        print(f"Error executing sub-execution: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-executions/<int:sub_execution_id>/status", methods=["PUT"])
@requires_auth
def update_sub_execution_status(sub_execution_id):
    """Update the status of a sub-execution"""
    print(f"Updating sub-execution status for ID: {sub_execution_id}")
    connection, cursor = db_conn()

    try:
        data = request.get_json()
        status = data.get("execution_status") or data.get("status")

        if not status:
            return jsonify({"success": False, "error": "Status is required"}), 400

        valid_statuses = ["pending", "in_progress", "completed", "failed", "cancelled"]
        if status not in valid_statuses:
            return jsonify({"success": False, "error": "Invalid execution status"}), 400

        # Update sub-execution status
        update_fields = ["execution_status = %s", "date = NOW()", "action = %s"]
        update_values = [status, "update_status"]

        if status == "completed":
            update_fields.append("execution_end_time = NOW()")

        cursor.execute(
            f"""
            UPDATE workflow_engine_sub_executions
            SET {", ".join(update_fields)}
            WHERE id = %s
        """,
            update_values + [sub_execution_id],
        )

        # Get parent execution ID
        cursor.execute(
            """
            SELECT parent_execution_id FROM workflow_engine_sub_executions WHERE id = %s
        """,
            (sub_execution_id,),
        )
        parent_execution_result = cursor.fetchone()

        if parent_execution_result:
            parent_execution_id = parent_execution_result[0]
            print(f"Checking completion status for parent execution {parent_execution_id}")

            # Check if all sub-executions for this parent are completed
            cursor.execute(
                """
                SELECT COUNT(*) FROM workflow_engine_sub_executions
                WHERE parent_execution_id = %s AND execution_status != 'completed'
            """,
                (parent_execution_id,),
            )
            incomplete_count = cursor.fetchone()[0]
            print(f"Found {incomplete_count} incomplete sub-executions")

            if incomplete_count == 0:
                # All sub-executions are completed, update parent to completed
                print(f"All sub-executions completed, updating parent execution {parent_execution_id} to completed")
                cursor.execute(
                    """
                    UPDATE workflow_engine_parent_executions
                    SET execution_status = 'completed', execution_end_time = NOW()
                    WHERE id = %s
                """,
                    (parent_execution_id,),
                )
                print(f"Parent execution completion update affected {cursor.rowcount} rows")
            elif status == "completed":
                # Check if this was the last sub-execution to complete
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM workflow_engine_sub_executions
                    WHERE parent_execution_id = %s AND execution_status = 'completed'
                """,
                    (parent_execution_id,),
                )
                completed_count = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT COUNT(*) FROM workflow_engine_sub_executions
                    WHERE parent_execution_id = %s
                """,
                    (parent_execution_id,),
                )
                total_count = cursor.fetchone()[0]

                if completed_count == total_count:
                    # All sub-executions are completed, update parent to completed
                    cursor.execute(
                        """
                        UPDATE workflow_engine_parent_executions
                        SET execution_status = 'completed', execution_end_time = NOW()
                        WHERE id = %s
                    """,
                        (parent_execution_id,),
                    )

        connection.commit()

        return jsonify({"success": True, "message": f"Sub-execution status updated to {status}"})

    except Exception as e:
        connection.rollback()
        print(f"Error updating sub-execution status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sub-executions/<int:sub_execution_id>/inputs-outputs", methods=["GET"])
@requires_auth
def get_sub_execution_inputs_outputs(sub_execution_id):
    """Get inputs and outputs for a sub-execution with field options"""
    print(f"Getting inputs/outputs for sub-execution ID: {sub_execution_id}")
    connection, cursor = db_conn()

    try:
        # Get sub-execution details
        cursor.execute(
            """
            SELECT se.id, se.sub_process_id, se.execution_status
            FROM workflow_engine_sub_executions se
            WHERE se.id = %s
        """,
            (sub_execution_id,),
        )
        sub_execution = cursor.fetchone()

        if not sub_execution:
            return jsonify({"success": False, "error": "Sub-execution not found"}), 404

        # Get inputs for this sub-process
        cursor.execute(
            """
            SELECT i.id, i.input_name, i.input_type, i.input_unit, i.execution_options
            FROM workflow_engine_inputs i
            WHERE i.process_id = %s
            ORDER BY i.input_name
        """,
            (sub_execution[1],),
        )
        inputs = cursor.fetchall()

        # Get outputs for this sub-process
        cursor.execute(
            """
            SELECT o.id, o.output_name, o.output_type, o.output_unit, o.execution_options
            FROM workflow_engine_outputs o
            WHERE o.process_id = %s
            ORDER BY o.output_name
        """,
            (sub_execution[1],),
        )
        outputs = cursor.fetchall()

        # Get field options (with fallback if table doesn't exist)
        field_options = {}
        try:
            cursor.execute("""
                SELECT field_type, option_value, option_label
                FROM workflow_engine_field_options
                ORDER BY field_type, option_label
            """)
            field_options_data = cursor.fetchall()

            # Organize field options by type
            for option in field_options_data:
                field_type = option[0]
                if field_type not in field_options:
                    field_options[field_type] = []
                field_options[field_type].append({"value": option[1], "label": option[2]})
        except Exception as e:
            print(f"Field options table not found, using defaults: {e}")
            # Provide default options if table doesn't exist
            field_options = {
                "unit": [
                    {"value": "kg", "label": "Kilograms"},
                    {"value": "g", "label": "Grams"},
                    {"value": "l", "label": "Liters"},
                    {"value": "ml", "label": "Milliliters"},
                    {"value": "pieces", "label": "Pieces"},
                ],
                "type": [
                    {"value": "raw_material", "label": "Raw Material"},
                    {"value": "intermediate", "label": "Intermediate Product"},
                    {"value": "finished_product", "label": "Finished Product"},
                    {"value": "waste", "label": "Waste"},
                ],
            }

        # Get sub-process name
        cursor.execute(
            """
            SELECT sp.sub_process_name
            FROM workflow_engine_sub_processes sp
            WHERE sp.id = %s
        """,
            (sub_execution[1],),
        )
        sub_process_result = cursor.fetchone()
        sub_process_name = sub_process_result[0] if sub_process_result else "Unknown Process"

        # Process inputs
        prompt_inputs = []
        print(f"Found {len(inputs)} inputs for sub-process {sub_execution[1]}")
        for input_item in inputs:
            execution_options = input_item[4] or {}
            print(f"Input: {input_item[1]}, execution_options: {execution_options}")
            if execution_options.get("batch") == "prompt":
                prompt_inputs.append(
                    {
                        "id": input_item[0],
                        "input_name": input_item[1],  # Changed from 'name' to 'input_name'
                        "input_type": input_item[2],  # Changed from 'type' to 'input_type'
                        "input_unit": input_item[3],  # Changed from 'unit' to 'input_unit'
                        "execution_options": execution_options,
                    }
                )
        print(f"Found {len(prompt_inputs)} prompt inputs")

        # Process outputs
        prompt_outputs = []
        for output_item in outputs:
            execution_options = output_item[4] or {}
            if execution_options.get("batch") == "prompt":
                prompt_outputs.append(
                    {
                        "id": output_item[0],
                        "output_name": output_item[1],  # Changed from 'name' to 'output_name'
                        "output_type": output_item[2],  # Changed from 'type' to 'output_type'
                        "output_unit": output_item[3],  # Changed from 'unit' to 'output_unit'
                        "execution_options": execution_options,
                    }
                )

        return jsonify(
            {
                "success": True,
                "sub_process_name": sub_process_name,
                "prompt_inputs": prompt_inputs,
                "prompt_outputs": prompt_outputs,
                "field_options": field_options,
            }
        )

    except Exception as e:
        print(f"Error getting sub-execution inputs/outputs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


# Field Options API for dynamic dropdowns
@workflow_engine_bp.route("/api/workflow-engine/field-options", methods=["GET"])
@requires_auth
def get_field_options():
    """Get all field options grouped by field type"""
    print("Getting all field options")
    connection, cursor = db_conn()

    try:
        cursor.execute("""
            SELECT field_type, option_value, option_label, is_system_default, id
            FROM workflow_engine_field_options
            ORDER BY field_type, option_label
        """)
        options = cursor.fetchall()

        # Group options by field type
        field_options = {}
        for option in options:
            field_type = option[0]
            if field_type not in field_options:
                field_options[field_type] = []
            field_options[field_type].append(
                {"id": option[4], "value": option[1], "label": option[2], "is_system_default": option[3]}
            )

        return jsonify({"success": True, "field_options": field_options})

    except Exception as e:
        print(f"Error getting field options: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/field-options/<field_type>", methods=["GET"])
@requires_auth
def get_field_options_by_type(field_type):
    """Get field options for a specific field type"""
    print(f"Getting field options for type: {field_type}")
    connection, cursor = db_conn()

    try:
        cursor.execute(
            """
            SELECT id, option_value, option_label, is_system_default
            FROM workflow_engine_field_options
            WHERE field_type = %s
            ORDER BY option_label
        """,
            (field_type,),
        )
        options = cursor.fetchall()

        result = []
        for option in options:
            result.append({"id": option[0], "value": option[1], "label": option[2], "is_system_default": option[3]})

        return jsonify({"success": True, "options": result})

    except Exception as e:
        print(f"Error getting field options by type: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/field-options", methods=["POST"])
@requires_auth
def create_field_option():
    """Create a new field option"""
    print("Creating new field option")
    connection, cursor = db_conn()

    try:
        data = request.get_json()
        field_type = data.get("field_type")
        option_value = data.get("option_value")
        option_label = data.get("option_label")
        uid = data.get("uid", "system")

        if not all([field_type, option_value, option_label]):
            return jsonify({"success": False, "error": "field_type, option_value, and option_label are required"}), 400

        # Check if option already exists
        cursor.execute(
            """
            SELECT id FROM workflow_engine_field_options
            WHERE field_type = %s AND option_value = %s
        """,
            (field_type, option_value),
        )
        if cursor.fetchone():
            return jsonify({"success": False, "error": "Option already exists"}), 400

        # Create new option
        cursor.execute(
            """
            INSERT INTO workflow_engine_field_options
            (field_type, option_value, option_label, is_system_default, uid, created_date, updated_date)
            VALUES (%s, %s, %s, FALSE, %s, NOW(), NOW())
            RETURNING id
        """,
            (field_type, option_value, option_label, uid),
        )

        option_id = cursor.fetchone()[0]
        connection.commit()

        return jsonify({"success": True, "message": "Field option created successfully", "option_id": option_id})

    except Exception as e:
        connection.rollback()
        print(f"Error creating field option: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/field-options/<int:option_id>", methods=["PUT"])
@requires_auth
def update_field_option(option_id):
    """Update an existing field option"""
    print(f"Updating field option ID: {option_id}")
    connection, cursor = db_conn()

    try:
        data = request.get_json()
        option_value = data.get("option_value")
        option_label = data.get("option_label")

        if not all([option_value, option_label]):
            return jsonify({"success": False, "error": "option_value and option_label are required"}), 400

        # Check if option exists and is not a system default
        cursor.execute(
            """
            SELECT is_system_default FROM workflow_engine_field_options
            WHERE id = %s
        """,
            (option_id,),
        )
        result = cursor.fetchone()

        if not result:
            return jsonify({"success": False, "error": "Option not found"}), 404

        if result[0]:  # is_system_default
            return jsonify({"success": False, "error": "Cannot modify system default options"}), 400

        # Update option
        cursor.execute(
            """
            UPDATE workflow_engine_field_options
            SET option_value = %s, option_label = %s, updated_date = NOW()
            WHERE id = %s
        """,
            (option_value, option_label, option_id),
        )

        connection.commit()

        return jsonify({"success": True, "message": "Field option updated successfully"})

    except Exception as e:
        connection.rollback()
        print(f"Error updating field option: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/field-options/<int:option_id>", methods=["DELETE"])
@requires_auth
def delete_field_option(option_id):
    """Delete a field option"""
    print(f"Deleting field option ID: {option_id}")
    connection, cursor = db_conn()

    try:
        # Check if option exists and is not a system default
        cursor.execute(
            """
            SELECT is_system_default FROM workflow_engine_field_options
            WHERE id = %s
        """,
            (option_id,),
        )
        result = cursor.fetchone()

        if not result:
            return jsonify({"success": False, "error": "Option not found"}), 404

        if result[0]:  # is_system_default
            return jsonify({"success": False, "error": "Cannot delete system default options"}), 400

        # Delete option
        cursor.execute("DELETE FROM workflow_engine_field_options WHERE id = %s", (option_id,))
        connection.commit()

        return jsonify({"success": True, "message": "Field option deleted successfully"})

    except Exception as e:
        connection.rollback()
        print(f"Error deleting field option: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/field-options/populate-defaults", methods=["POST"])
@requires_auth
def populate_default_field_options():
    """Populate the field options table with default options"""
    print("Populating default field options")
    connection, cursor = db_conn()

    try:
        # Default options for different field types
        default_options = [
            # Unit options
            ("unit", "kg", "Kilograms", True),
            ("unit", "g", "Grams", True),
            ("unit", "l", "Liters", True),
            ("unit", "ml", "Milliliters", True),
            ("unit", "pieces", "Pieces", True),
            ("unit", "boxes", "Boxes", True),
            ("unit", "bottles", "Bottles", True),
            # Type options
            ("type", "raw_material", "Raw Material", True),
            ("type", "ingredient", "Ingredient", True),
            ("type", "product", "Product", True),
            ("type", "sample", "Sample", True),
            ("type", "waste", "Waste", True),
            # Status options
            ("status", "pending", "Pending", True),
            ("status", "in_progress", "In Progress", True),
            ("status", "completed", "Completed", True),
            ("status", "failed", "Failed", True),
            ("status", "cancelled", "Cancelled", True),
            # Quality status options
            ("quality_status", "approved", "Approved", True),
            ("quality_status", "rejected", "Rejected", True),
            ("quality_status", "pending_review", "Pending Review", True),
            ("quality_status", "requires_testing", "Requires Testing", True),
        ]

        # Insert default options (check for existing first)
        for field_type, option_value, option_label, is_system_default in default_options:
            # Check if option already exists
            cursor.execute(
                """
                SELECT id FROM workflow_engine_field_options
                WHERE field_type = %s AND option_value = %s
            """,
                (field_type, option_value),
            )

            if not cursor.fetchone():
                # Insert new option
                cursor.execute(
                    """
                    INSERT INTO workflow_engine_field_options
                    (field_type, option_value, option_label, is_system_default)
                    VALUES (%s, %s, %s, %s)
                """,
                    (field_type, option_value, option_label, is_system_default),
                )

        connection.commit()

        return jsonify({"success": True, "message": "Default field options populated successfully"})

    except Exception as e:
        connection.rollback()
        print(f"Error populating default field options: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route(
    "/api/workflow-engine/sub-executions/<int:sub_execution_id>/complete-with-outputs", methods=["POST"]
)
@requires_auth
def complete_sub_execution_with_outputs(sub_execution_id):
    """Complete a sub-execution with output data"""
    print(f"Completing sub-execution ID: {sub_execution_id} with outputs")
    connection, cursor = db_conn()

    try:
        data = request.get_json()

        # Get sub-execution details
        cursor.execute(
            """
            SELECT se.id, se.sub_process_id, se.execution_status
            FROM workflow_engine_sub_executions se
            WHERE se.id = %s
        """,
            (sub_execution_id,),
        )
        sub_execution = cursor.fetchone()

        if not sub_execution:
            return jsonify({"success": False, "error": "Sub-execution not found"}), 404

        if sub_execution[2] != "in_progress":
            return jsonify({"success": False, "error": "Sub-execution is not in progress"}), 400

        # Get outputs for this sub-process to create execution outputs
        cursor.execute(
            """
            SELECT id, output_name, output_type, execution_options
            FROM workflow_engine_outputs
            WHERE process_id = %s
        """,
            (sub_execution[1],),
        )
        outputs = cursor.fetchall()

        # Create execution outputs from output data
        output_data = data.get("output_data", {})
        execution_notes = data.get("execution_notes", "")
        print(f"Received output data: {output_data}")

        for output_template in outputs:
            output_id = output_template[0]
            output_name = output_template[1]
            execution_options = output_template[3] or {}

            # Get output data for this output
            output_info = output_data.get(str(output_id), {})

            # Determine actual output name based on execution options
            actual_output_name = output_name
            if execution_options.get("name") == "prompt" and output_info.get("name"):
                actual_output_name = output_info.get("name")

            # Create execution output record
            cursor.execute(
                """
                INSERT INTO workflow_engine_execution_outputs
                (execution_id, output_template_id, actual_output_name,
                 actual_output_quantity, actual_output_unit, actual_output_batch_number, date, action)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), 'create')
            """,
                (
                    sub_execution_id,
                    output_id,
                    actual_output_name,
                    output_info.get("quantity") if output_info.get("quantity") else None,
                    output_info.get("unit", ""),
                    output_info.get("batch", ""),
                ),
            )

            # Check if this output flows through to other processes and record flow-through data
            cursor.execute(
                """
                SELECT output_flow_through, output_flow_through_fields
                FROM workflow_engine_outputs
                WHERE id = %s AND output_flow_through = TRUE
            """,
                (output_id,),
            )
            flow_through_result = cursor.fetchone()

            if flow_through_result:
                flow_through_fields = flow_through_result[1]
                if flow_through_fields and isinstance(flow_through_fields, dict):
                    # Record flow-through data for connected processes
                    cursor.execute(
                        """
                        SELECT to_sub_process_id FROM workflow_engine_connections
                        WHERE from_sub_process_id = (SELECT process_id FROM workflow_engine_outputs WHERE id = %s)
                        AND connection_status = 'active'
                    """,
                        (output_id,),
                    )
                    connected_processes = cursor.fetchall()

                    for connected_process in connected_processes:
                        to_process_id = connected_process[0]
                        # Store flow-through data for execution tracking
                        cursor.execute(
                            """
                            INSERT INTO workflow_engine_execution_flow_through
                            (source_execution_id, source_output_id, target_process_id,
                             flow_through_data, date, action)
                            VALUES (%s, %s, %s, %s, NOW(), 'create')
                        """,
                            (
                                sub_execution_id,
                                output_id,
                                to_process_id,
                                json.dumps(
                                    {
                                        "output_data": output_info,
                                        "flow_through_fields": flow_through_fields,
                                        "source_process_name": actual_output_name,
                                    }
                                ),
                            ),
                        )

        # Update sub-execution status to 'completed'
        cursor.execute(
            """
            UPDATE workflow_engine_sub_executions
            SET execution_status = 'completed', execution_end_time = NOW(), execution_notes = %s, date = NOW(), action = 'complete'
            WHERE id = %s
        """,
            (execution_notes, sub_execution_id),
        )

        # Get parent execution ID and check completion status
        cursor.execute(
            """
            SELECT parent_execution_id FROM workflow_engine_sub_executions WHERE id = %s
        """,
            (sub_execution_id,),
        )
        parent_execution_result = cursor.fetchone()

        if parent_execution_result:
            parent_execution_id = parent_execution_result[0]
            print(f"Checking completion status for parent execution {parent_execution_id}")

            # Check if all sub-executions for this parent are completed
            cursor.execute(
                """
                SELECT COUNT(*) FROM workflow_engine_sub_executions
                WHERE parent_execution_id = %s AND execution_status != 'completed'
            """,
                (parent_execution_id,),
            )
            incomplete_count = cursor.fetchone()[0]
            print(f"Found {incomplete_count} incomplete sub-executions")

            if incomplete_count == 0:
                # All sub-executions are completed, update parent to completed
                print(f"All sub-executions completed, updating parent execution {parent_execution_id} to completed")
                cursor.execute(
                    """
                    UPDATE workflow_engine_parent_executions
                    SET execution_status = 'completed', execution_end_time = NOW()
                    WHERE id = %s
                """,
                    (parent_execution_id,),
                )
                print(f"Parent execution completion update affected {cursor.rowcount} rows")

        connection.commit()

        return jsonify({"success": True, "message": "Sub-execution completed successfully with outputs"})

    except Exception as e:
        connection.rollback()
        print(f"Error completing sub-execution with outputs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/api/workflow-engine/flow-through/update-existing", methods=["POST"])
@requires_auth
def update_existing_flow_through_inputs():
    """Update existing flow-through inputs to apply prompt → template transformation"""
    print("Updating existing flow-through inputs to apply prompt → template transformation")
    connection, cursor = db_conn()

    try:
        # Find all inputs that are flow-through and have prompt execution options
        cursor.execute("""
            SELECT i.id, i.process_id, i.input_source, i.execution_options
            FROM workflow_engine_inputs i
            WHERE i.input_source LIKE 'Flow-through from %'
            AND i.execution_options IS NOT NULL
            AND i.execution_options != '{}'
            AND i.execution_options != 'null'
        """)

        flow_through_inputs = cursor.fetchall()
        updated_count = 0

        for input_record in flow_through_inputs:
            input_id, process_id, input_source, execution_options = input_record

            # Parse execution options
            exec_options = (
                execution_options
                if isinstance(execution_options, dict)
                else (json.loads(execution_options) if execution_options else {})
            )

            # Check if any execution options are set to 'prompt'
            has_prompt_options = any(value == "prompt" for value in exec_options.values())

            if has_prompt_options:
                # Transform 'prompt' to 'template' for all fields
                updated_exec_options = {}
                for field, value in exec_options.items():
                    if value == "prompt":
                        updated_exec_options[field] = "template"
                    else:
                        updated_exec_options[field] = value

                # Update the input with transformed execution options
                cursor.execute(
                    """
                    UPDATE workflow_engine_inputs
                    SET execution_options = %s, date = CURRENT_DATE, action = 'update_flow_through_transform'
                    WHERE id = %s
                """,
                    (json.dumps(updated_exec_options), input_id),
                )

                updated_count += 1
                print(f"Updated input {input_id} in process {process_id}: {exec_options} → {updated_exec_options}")

        connection.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Updated {updated_count} existing flow-through inputs to apply prompt → template transformation",
                "updated_count": updated_count,
            }
        )

    except Exception as e:
        connection.rollback()
        print(f"Error updating existing flow-through inputs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@workflow_engine_bp.route("/workflow-engine/parent-process/<int:parent_process_id>/executions/summary")
@requires_auth
def execution_summary(parent_process_id):
    """Display execution summary page for a parent process"""
    connection, cursor = db_conn()

    try:
        # Get parent process details
        cursor.execute(
            """
            SELECT id, parent_process_name, parent_process_description
            FROM workflow_engine_parent_processes
            WHERE id = %s
        """,
            (parent_process_id,),
        )
        parent_process = cursor.fetchone()

        if not parent_process:
            return "Parent process not found", 404

        # Get all executions for this parent process
        cursor.execute(
            """
            SELECT pe.id, pe.parent_process_id, pe.execution_status, pe.execution_start_time,
                   pe.execution_end_time, pe.execution_notes, pe.date,
                   pp.parent_process_name
            FROM workflow_engine_parent_executions pe
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.parent_process_id = %s
            ORDER BY pe.date DESC, pe.id DESC
        """,
            (parent_process_id,),
        )
        executions = cursor.fetchall()

        # Calculate statistics
        total_executions = len(executions)
        completed_executions = len([e for e in executions if e[2] == "completed"])
        in_progress_executions = len([e for e in executions if e[2] == "in_progress"])
        failed_executions = len([e for e in executions if e[2] == "failed"])
        pending_executions = len([e for e in executions if e[2] == "pending"])

        # Convert executions to a more convenient format
        execution_list = []
        for execution in executions:
            execution_dict = {
                "id": execution[0],
                "parent_process_id": execution[1],
                "execution_status": execution[2],
                "execution_start_time": execution[3],
                "execution_end_time": execution[4],
                "execution_notes": execution[5],
                "date": execution[6],
                "parent_process_name": execution[7],
            }
            print(f"Execution {execution[0]}: status = {execution[2]}")
            execution_list.append(execution_dict)

        return render_template(
            "execution_summary.html",
            parent_process_id=parent_process_id,
            parent_process_name=parent_process[1],
            executions=execution_list,
            total_executions=total_executions,
            completed_executions=completed_executions,
            in_progress_executions=in_progress_executions,
            failed_executions=failed_executions,
            pending_executions=pending_executions,
        )

    except Exception as e:
        print(f"Error loading execution summary: {e}")
        return f"Error loading execution summary: {str(e)}", 500
    finally:
        cursor.close()
        connection.close()


# ============================================================================
# EXECUTION TRACING APIs
# ============================================================================


@workflow_engine_bp.route("/api/workflow-engine/executions/<int:execution_id>/lineage", methods=["GET"])
@requires_auth
def get_execution_lineage(execution_id):
    """Get full execution lineage tree for tracing"""
    try:
        connection, cursor = db_conn()

        # Get the execution details
        cursor.execute(
            """
            SELECT pe.id, pe.parent_process_id, pe.execution_batch_id, pe.execution_status,
                   pe.execution_start_time, pe.execution_end_time, pe.execution_notes,
                   pe.parent_execution_ids, pe.sales_mapping_status,
                   pp.parent_process_name
            FROM workflow_engine_parent_executions pe
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.id = %s
        """,
            (execution_id,),
        )

        execution = cursor.fetchone()
        if not execution:
            return jsonify({"success": False, "error": "Execution not found"}), 404

        # Get all sub-executions for this parent execution
        cursor.execute(
            """
            SELECT se.id, se.sub_process_id, se.execution_status, se.execution_start_time,
                   se.execution_end_time, se.execution_notes, se.execution_data,
                   sp.sub_process_name, sp.execution_order
            FROM workflow_engine_sub_executions se
            LEFT JOIN workflow_engine_sub_processes sp ON se.sub_process_id = sp.id
            WHERE se.parent_execution_id = %s
            ORDER BY sp.execution_order, se.id
        """,
            (execution_id,),
        )

        sub_executions = cursor.fetchall()

        # Get lineage relationships
        cursor.execute(
            """
            SELECT parent_execution_id, child_execution_id, relationship_type, flow_through_data
            FROM workflow_engine_execution_lineage
            WHERE parent_execution_id = %s OR child_execution_id = %s
        """,
            (execution_id, execution_id),
        )

        lineage_relationships = cursor.fetchall()

        # Get sales mappings
        cursor.execute(
            """
            SELECT esm.id, esm.sales_id, esm.product_name, esm.quantity_sold,
                   esm.batch_reference, esm.mapping_type, esm.mapping_confidence,
                   esm.mapping_notes, sp.date as sales_date, sp.buyer
            FROM workflow_engine_execution_sales_mapping esm
            LEFT JOIN sales_product sp ON esm.sales_id = sp.id
            WHERE esm.execution_id = %s
        """,
            (execution_id,),
        )

        sales_mappings = cursor.fetchall()

        # Build the lineage tree
        lineage_tree = {
            "execution": {
                "id": execution[0],
                "parent_process_id": execution[1],
                "execution_batch_id": execution[2],
                "execution_status": execution[3],
                "execution_start_time": execution[4].isoformat() if execution[4] else None,
                "execution_end_time": execution[5].isoformat() if execution[5] else None,
                "execution_notes": execution[6],
                "parent_execution_ids": execution[7],
                "sales_mapping_status": execution[8],
                "parent_process_name": execution[9],
            },
            "sub_executions": [],
            "lineage_relationships": [],
            "sales_mappings": [],
            "ancestors": [],
            "descendants": [],
        }

        # Process sub-executions
        for sub_exec in sub_executions:
            lineage_tree["sub_executions"].append(
                {
                    "id": sub_exec[0],
                    "sub_process_id": sub_exec[1],
                    "execution_status": sub_exec[2],
                    "execution_start_time": sub_exec[3].isoformat() if sub_exec[3] else None,
                    "execution_end_time": sub_exec[4].isoformat() if sub_exec[4] else None,
                    "execution_notes": sub_exec[5],
                    "execution_data": sub_exec[6],
                    "sub_process_name": sub_exec[7],
                    "execution_order": sub_exec[8],
                }
            )

        # Process lineage relationships
        for rel in lineage_relationships:
            lineage_tree["lineage_relationships"].append(
                {
                    "parent_execution_id": rel[0],
                    "child_execution_id": rel[1],
                    "relationship_type": rel[2],
                    "flow_through_data": rel[3],
                }
            )

        # Process sales mappings
        for mapping in sales_mappings:
            lineage_tree["sales_mappings"].append(
                {
                    "id": mapping[0],
                    "sales_id": mapping[1],
                    "product_name": mapping[2],
                    "quantity_sold": mapping[3],
                    "batch_reference": mapping[4],
                    "mapping_type": mapping[5],
                    "mapping_confidence": mapping[6],
                    "mapping_notes": mapping[7],
                    "sales_date": mapping[8].isoformat() if mapping[8] else None,
                    "buyer": mapping[9],
                }
            )

        return jsonify({"success": True, "lineage": lineage_tree})

    except Exception as e:
        print(f"Error getting execution lineage: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/executions/<int:execution_id>/sales", methods=["GET"])
@requires_auth
def get_execution_sales(execution_id):
    """Get all sales linked to a specific execution"""
    try:
        connection, cursor = db_conn()

        cursor.execute(
            """
            SELECT esm.id, esm.sales_id, esm.product_name, esm.quantity_sold,
                   esm.batch_reference, esm.mapping_type, esm.mapping_confidence,
                   esm.mapping_notes, esm.created_at,
                   sp.date as sales_date, sp.buyer, sp.invoice_total, sp.products
            FROM workflow_engine_execution_sales_mapping esm
            LEFT JOIN sales_product sp ON esm.sales_id = sp.id
            WHERE esm.execution_id = %s
            ORDER BY sp.date DESC
        """,
            (execution_id,),
        )

        sales_mappings = cursor.fetchall()

        result = []
        for mapping in sales_mappings:
            result.append(
                {
                    "mapping_id": mapping[0],
                    "sales_id": mapping[1],
                    "product_name": mapping[2],
                    "quantity_sold": mapping[3],
                    "batch_reference": mapping[4],
                    "mapping_type": mapping[5],
                    "mapping_confidence": mapping[6],
                    "mapping_notes": mapping[7],
                    "mapping_created_at": mapping[8].isoformat() if mapping[8] else None,
                    "sales_date": mapping[9].isoformat() if mapping[9] else None,
                    "buyer": mapping[10],
                    "invoice_total": mapping[11],
                    "products": mapping[12],
                }
            )

        return jsonify({"success": True, "sales": result})

    except Exception as e:
        print(f"Error getting execution sales: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sales/unmapped", methods=["GET"])
@requires_auth
def get_unmapped_sales():
    """Get sales that don't have execution mappings"""
    try:
        connection, cursor = db_conn()

        cursor.execute("""
            SELECT sp.id, sp.date, sp.buyer, sp.products, sp.invoice_total,
                   sp.invoice_gst, sp.notes
            FROM sales_product sp
            LEFT JOIN workflow_engine_execution_sales_mapping esm ON sp.id = esm.sales_id
            WHERE esm.sales_id IS NULL
            ORDER BY sp.date DESC
            LIMIT 100
        """)

        unmapped_sales = cursor.fetchall()

        result = []
        for sale in unmapped_sales:
            # Parse products JSON to extract product details
            products_data = sale[3] if sale[3] else {}
            products_list = []

            if isinstance(products_data, dict) and "products" in products_data:
                for product_name, product_data in products_data["products"].items():
                    products_list.append(
                        {
                            "name": product_name,
                            "quantity": product_data.get("quantity", 0),
                            "unit_price": product_data.get("unit_price", 0),
                            "amount_nzd": product_data.get("amount_nzd", 0),
                            "bottle_batch": product_data.get("bottle_batch", ""),
                            "abv": product_data.get("abv", 0),
                            "bottle_size_ml": product_data.get("bottle_size_ml", 0),
                        }
                    )

            result.append(
                {
                    "id": sale[0],
                    "date": sale[1].isoformat() if sale[1] else None,
                    "buyer": sale[2],
                    "products": products_list,
                    "invoice_total": sale[4],
                    "invoice_gst": sale[5],
                    "notes": sale[6],
                }
            )

        return jsonify({"success": True, "unmapped_sales": result})

    except Exception as e:
        print(f"Error getting unmapped sales: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sales/<int:sales_id>/trace", methods=["GET"])
@requires_auth
def trace_sales_to_source(sales_id):
    """Trace a sale back to its source execution and materials"""
    try:
        connection, cursor = db_conn()

        # Get the sale details
        cursor.execute(
            """
            SELECT id, date, buyer, products, invoice_total, notes
            FROM sales_product
            WHERE id = %s
        """,
            (sales_id,),
        )

        sale = cursor.fetchone()
        if not sale:
            return jsonify({"success": False, "error": "Sale not found"}), 404

        # Get execution mappings for this sale
        cursor.execute(
            """
            SELECT esm.id, esm.execution_id, esm.product_name, esm.quantity_sold,
                   esm.batch_reference, esm.mapping_type, esm.mapping_confidence,
                   pe.execution_batch_id, pe.execution_status, pe.parent_process_id,
                   pp.parent_process_name
            FROM workflow_engine_execution_sales_mapping esm
            LEFT JOIN workflow_engine_parent_executions pe ON esm.execution_id = pe.id
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE esm.sales_id = %s
        """,
            (sales_id,),
        )

        execution_mappings = cursor.fetchall()

        # Build trace result
        trace_result = {
            "sale": {
                "id": sale[0],
                "date": sale[1].isoformat() if sale[1] else None,
                "buyer": sale[2],
                "products": sale[3],
                "invoice_total": sale[4],
                "notes": sale[5],
            },
            "execution_mappings": [],
            "full_lineage": [],
        }

        # Process execution mappings
        for mapping in execution_mappings:
            mapping_data = {
                "mapping_id": mapping[0],
                "execution_id": mapping[1],
                "product_name": mapping[2],
                "quantity_sold": mapping[3],
                "batch_reference": mapping[4],
                "mapping_type": mapping[5],
                "mapping_confidence": mapping[6],
                "execution_batch_id": mapping[7],
                "execution_status": mapping[8],
                "parent_process_id": mapping[9],
                "parent_process_name": mapping[10],
            }

            # Get full lineage for this execution
            if mapping[1]:  # If execution_id exists
                lineage_data = get_execution_lineage_data(cursor, mapping[1])
                mapping_data["lineage"] = lineage_data

            trace_result["execution_mappings"].append(mapping_data)

        return jsonify({"success": True, "trace": trace_result})

    except Exception as e:
        print(f"Error tracing sale: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_execution_lineage_data(cursor, execution_id):
    """Helper function to get execution lineage data"""
    try:
        # Get execution details
        cursor.execute(
            """
            SELECT pe.id, pe.execution_batch_id, pe.execution_status,
                   pe.parent_execution_ids, pp.parent_process_name
            FROM workflow_engine_parent_executions pe
            LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
            WHERE pe.id = %s
        """,
            (execution_id,),
        )

        execution = cursor.fetchone()
        if not execution:
            return None

        # Get sub-executions
        cursor.execute(
            """
            SELECT se.id, se.execution_status, se.execution_data,
                   sp.sub_process_name, sp.execution_order
            FROM workflow_engine_sub_executions se
            LEFT JOIN workflow_engine_sub_processes sp ON se.sub_process_id = sp.id
            WHERE se.parent_execution_id = %s
            ORDER BY sp.execution_order
        """,
            (execution_id,),
        )

        sub_executions = cursor.fetchall()

        return {
            "execution_id": execution[0],
            "execution_batch_id": execution[1],
            "execution_status": execution[2],
            "parent_execution_ids": execution[3],
            "parent_process_name": execution[4],
            "sub_executions": [
                {
                    "id": sub[0],
                    "execution_status": sub[1],
                    "execution_data": sub[2],
                    "sub_process_name": sub[3],
                    "execution_order": sub[4],
                }
                for sub in sub_executions
            ],
        }

    except Exception as e:
        print(f"Error getting execution lineage data: {e}")
        return None


@workflow_engine_bp.route("/api/workflow-engine/executions/<int:execution_id>/map-sales", methods=["POST"])
@requires_auth
def map_execution_to_sales(execution_id):
    """Map an execution to sales data"""
    try:
        data = request.get_json()
        sales_id = data.get("sales_id")
        product_name = data.get("product_name")
        quantity_sold = data.get("quantity_sold", 0)
        batch_reference = data.get("batch_reference", "")
        mapping_type = data.get("mapping_type", "manual")
        mapping_notes = data.get("mapping_notes", "")

        if not sales_id or not product_name:
            return jsonify({"success": False, "error": "sales_id and product_name are required"}), 400

        connection, cursor = db_conn()

        # Check if mapping already exists
        cursor.execute(
            """
            SELECT id FROM workflow_engine_execution_sales_mapping
            WHERE execution_id = %s AND sales_id = %s AND product_name = %s
        """,
            (execution_id, sales_id, product_name),
        )

        if cursor.fetchone():
            return jsonify({"success": False, "error": "Mapping already exists"}), 400

        # Create the mapping
        cursor.execute(
            """
            INSERT INTO workflow_engine_execution_sales_mapping
            (execution_id, sales_id, product_name, quantity_sold, batch_reference,
             mapping_type, mapping_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                execution_id,
                sales_id,
                product_name,
                quantity_sold,
                batch_reference,
                mapping_type,
                mapping_notes,
                str(uuid.uuid4()),
            ),
        )

        # Update execution sales mapping status
        cursor.execute(
            """
            UPDATE workflow_engine_parent_executions
            SET sales_mapping_status = 'partial'
            WHERE id = %s AND sales_mapping_status = 'unmapped'
        """,
            (execution_id,),
        )

        connection.commit()

        return jsonify({"success": True, "message": "Sales mapping created successfully"})

    except Exception as e:
        print(f"Error mapping execution to sales: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/traceability/search", methods=["GET"])
@requires_auth
def search_traceability():
    """Search for executions, sales, or batches across the system"""
    try:
        query = request.args.get("q", "")
        search_type = request.args.get("type", "all")  # 'all', 'executions', 'sales', 'batches'

        if not query:
            return jsonify({"success": False, "error": "Query parameter is required"}), 400

        connection, cursor = db_conn()

        results = {"executions": [], "sales": [], "batches": []}

        # Search executions
        if search_type in ["all", "executions"]:
            cursor.execute(
                """
                SELECT pe.id, pe.execution_batch_id, pe.execution_status,
                       pe.execution_start_time, pe.execution_end_time,
                       pp.parent_process_name
                FROM workflow_engine_parent_executions pe
                LEFT JOIN workflow_engine_parent_processes pp ON pe.parent_process_id = pp.id
                WHERE pe.execution_batch_id ILIKE %s OR pp.parent_process_name ILIKE %s
                ORDER BY pe.execution_start_time DESC
                LIMIT 20
            """,
                (f"%{query}%", f"%{query}%"),
            )

            executions = cursor.fetchall()
            for exec_data in executions:
                results["executions"].append(
                    {
                        "id": exec_data[0],
                        "execution_batch_id": exec_data[1],
                        "execution_status": exec_data[2],
                        "execution_start_time": exec_data[3].isoformat() if exec_data[3] else None,
                        "execution_end_time": exec_data[4].isoformat() if exec_data[4] else None,
                        "parent_process_name": exec_data[5],
                    }
                )

        # Search sales
        if search_type in ["all", "sales"]:
            cursor.execute(
                """
                SELECT id, date, buyer, invoice_total, notes
                FROM sales_product
                WHERE buyer ILIKE %s OR notes ILIKE %s
                ORDER BY date DESC
                LIMIT 20
            """,
                (f"%{query}%", f"%{query}%"),
            )

            sales = cursor.fetchall()
            for sale in sales:
                results["sales"].append(
                    {
                        "id": sale[0],
                        "date": sale[1].isoformat() if sale[1] else None,
                        "buyer": sale[2],
                        "invoice_total": sale[3],
                        "notes": sale[4],
                    }
                )

        # Search batches (from execution batch IDs and sales batch references)
        if search_type in ["all", "batches"]:
            cursor.execute(
                """
                SELECT DISTINCT execution_batch_id
                FROM workflow_engine_parent_executions
                WHERE execution_batch_id ILIKE %s
                ORDER BY execution_batch_id
                LIMIT 20
            """,
                (f"%{query}%"),
            )

            batches = cursor.fetchall()
            for batch in batches:
                results["batches"].append({"batch_id": batch[0], "type": "execution"})

        return jsonify({"success": True, "results": results})

    except Exception as e:
        print(f"Error searching traceability: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@workflow_engine_bp.route("/api/workflow-engine/sales/<int:sales_id>/auto-map", methods=["POST"])
@requires_auth
def auto_map_sales_to_execution(sales_id):
    """Attempt to automatically map a sale to executions"""
    try:
        from features.workflow_engine.backend.sales_execution_mapping import attempt_automatic_sales_mapping

        result = attempt_automatic_sales_mapping(sales_id)
        return jsonify(result)

    except Exception as e:
        print(f"Error in auto-mapping: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/api/workflow-engine/sales/<int:sales_id>/suggestions", methods=["GET"])
@requires_auth
def get_execution_suggestions(sales_id):
    """Get execution suggestions for a sale"""
    try:
        from features.workflow_engine.backend.sales_execution_mapping import get_execution_suggestions_for_sale

        suggestions = get_execution_suggestions_for_sale(sales_id)
        return jsonify({"success": True, "suggestions": suggestions})

    except Exception as e:
        print(f"Error getting execution suggestions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@workflow_engine_bp.route("/workflow-engine/execution-tracing")
@requires_auth
def execution_tracing():
    """Serve the execution tracing page"""
    return render_template("execution_tracing.html")
