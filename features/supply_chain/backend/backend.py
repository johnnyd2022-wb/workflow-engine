from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from initialize import db_conn
import json
from datetime import datetime, date
from database_insert import insert_data
from config_loader import config

# Create Supply Chain blueprint
supply_chain_bp = Blueprint('supply_chain', __name__, template_folder='../frontend')

def format_process_type_for_display(process_type):
    """Convert database process type to user-friendly display name"""
    if not process_type:
        return 'Not specified'
    
    type_mapping = {
        'production_workflow': 'Production Workflow',
        'quality_workflow': 'Quality Workflow', 
        'logistics_workflow': 'Logistics Workflow',
        'procurement_workflow': 'Procurement Workflow',
        'manufacturing': 'Manufacturing',
        'packaging': 'Packaging',
        'quality_control': 'Quality Control',
        'logistics': 'Logistics',
        'procurement': 'Procurement'
    }
    
    return type_mapping.get(process_type, process_type.replace('_', ' ').title())

@supply_chain_bp.route('/supply-chain', methods=['GET', 'POST'])
def supply_chain():
    print("Accessed /supply-chain route")
    connection, cursor = db_conn()

    try:
        # Get all parent processes
        cursor.execute("""
            SELECT id, parent_process_name, parent_process_description, parent_process_type, 
                   parent_process_status, parent_process_category, parent_process_notes, date
            FROM supply_chain_parent_processes
            ORDER BY parent_process_name
        """)
        parent_processes = cursor.fetchall()

        # Get parent process statistics
        cursor.execute("SELECT COUNT(*) FROM supply_chain_parent_processes")
        total_parent_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_parent_processes WHERE parent_process_status = 'active'")
        active_parent_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_sub_processes")
        total_sub_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_inputs")
        total_inputs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_outputs")
        total_outputs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_connections")
        total_connections = cursor.fetchone()[0]

        return render_template('supply_chain.html',
                               parent_processes=parent_processes,
                               total_parent_processes=total_parent_processes,
                               active_parent_processes=active_parent_processes,
                               total_sub_processes=total_sub_processes,
                               total_inputs=total_inputs,
                               total_outputs=total_outputs,
                               total_connections=total_connections,
                               format_type=format_process_type_for_display)

    except Exception as e:
        print(f"Error in supply_chain route: {e}")
        return render_template('supply_chain.html', 
                               parent_processes=[],
                               total_parent_processes=0,
                               active_parent_processes=0,
                               total_sub_processes=0,
                               total_inputs=0,
                               total_outputs=0,
                               total_connections=0,
                               error=str(e))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/supply-chain/parent-process/<int:parent_process_id>')
def parent_process_detail(parent_process_id):
    print(f"Accessed parent process detail for ID: {parent_process_id}")
    connection, cursor = db_conn()

    try:
        # Get parent process details
        cursor.execute("""
            SELECT id, parent_process_name, parent_process_description, parent_process_type, 
                   parent_process_status, parent_process_category, parent_process_notes, date
            FROM supply_chain_parent_processes
            WHERE id = %s
        """, (parent_process_id,))
        parent_process = cursor.fetchone()

        if not parent_process:
            return render_template('parent_process_detail.html', 
                                   parent_process=None, 
                                   sub_processes=[],
                                   connections=[],
                                   error="Parent process not found")

        # Get sub processes for this parent
        cursor.execute("""
            SELECT id, sub_process_name, sub_process_description, sub_process_type,
                   sub_process_status, sub_process_category, sub_process_notes, 
                   execution_order, date
            FROM supply_chain_sub_processes
            WHERE parent_process_id = %s
            ORDER BY execution_order, sub_process_name
        """, (parent_process_id,))
        sub_processes = cursor.fetchall()

        # Get connections between sub-processes in this parent process
        cursor.execute("""
            SELECT c.id, c.parent_process_id, c.from_sub_process_id, c.to_sub_process_id, c.connection_type,
                   c.connection_status, c.connection_notes, c.date, c.action, c.uid,
                   sp1.sub_process_name as from_sub_process_name,
                   sp2.sub_process_name as to_sub_process_name
            FROM supply_chain_connections c
            LEFT JOIN supply_chain_sub_processes sp1 ON c.from_sub_process_id = sp1.id
            LEFT JOIN supply_chain_sub_processes sp2 ON c.to_sub_process_id = sp2.id
            WHERE c.parent_process_id = %s
            ORDER BY c.date DESC
        """, (parent_process_id,))
        connections = cursor.fetchall()

        return render_template('parent_process_detail.html',
                               parent_process=parent_process,
                               sub_processes=sub_processes,
                               connections=connections,
                               format_type=format_process_type_for_display)

    except Exception as e:
        print(f"Error in parent_process_detail route: {e}")
        return render_template('parent_process_detail.html', 
                               parent_process=None,
                               sub_processes=[],
                               connections=[],
                               error=str(e))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/supply-chain/parent-process/<int:parent_process_id>/visual', methods=['GET'])
def parent_process_visual_view(parent_process_id):
    """Visual DAG view for a specific parent process showing only its sub processes"""
    print(f"Accessed /supply-chain/parent-process/{parent_process_id}/visual route")
    connection, cursor = db_conn()
    
    try:
        # Get parent process details
        cursor.execute("""
            SELECT id, parent_process_name, parent_process_description, parent_process_type, 
                   parent_process_status, parent_process_category, parent_process_notes
            FROM supply_chain_parent_processes 
            WHERE id = %s
        """, (parent_process_id,))
        parent_process = cursor.fetchone()
        
        if not parent_process:
            return "Parent process not found", 404
        
        return render_template('parent_process_visual.html',
                               parent_process=parent_process,
                               format_type=format_process_type_for_display)
        
    except Exception as e:
        print(f"Error in parent_process_visual_view route: {e}")
        return f"Error loading visual view: {e}", 500
    finally:
        cursor.close()
        connection.close()

@supply_chain_bp.route('/supply-chain/sub-process/<int:sub_process_id>')
def sub_process_detail(sub_process_id):
    """Detail view for a specific sub process"""
    print(f"Accessed sub-process detail for ID: {sub_process_id}")
    connection, cursor = db_conn()
    
    try:
        # Get sub process details
        cursor.execute("""
            SELECT s.id, s.parent_process_id, s.sub_process_name, s.sub_process_description, 
                   s.sub_process_type, s.sub_process_status, s.sub_process_category, 
                   s.sub_process_notes, s.execution_order, s.date,
                   p.parent_process_name
            FROM supply_chain_sub_processes s
            LEFT JOIN supply_chain_parent_processes p ON s.parent_process_id = p.id
            WHERE s.id = %s
        """, (sub_process_id,))
        sub_process = cursor.fetchone()
        
        if not sub_process:
            return render_template('process_detail.html', 
                                   process=None, 
                                   inputs=[], 
                                   outputs=[], 
                                   connections=[],
                                   error="Sub-process not found")
        
        # Get inputs for this sub process
        cursor.execute("""
            SELECT i.id, i.process_id, i.input_name, i.input_type, i.input_quantity,
                   i.input_unit, i.input_specifications, i.input_source, i.input_batch_number,
                   i.input_status, i.date, i.action
            FROM supply_chain_inputs i
            WHERE i.process_id = %s
            ORDER BY i.input_name
        """, (sub_process_id,))
        inputs = cursor.fetchall()
        
        # Get outputs for this sub process
        cursor.execute("""
            SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity,
                   o.output_unit, o.output_specifications, o.output_batch_number,
                   o.output_quality_status, o.output_destination, o.date, o.action
            FROM supply_chain_outputs o
            WHERE o.process_id = %s
            ORDER BY o.output_name
        """, (sub_process_id,))
        outputs = cursor.fetchall()
        
        # Get connections for this sub process
        cursor.execute("""
            SELECT c.id, c.from_process_id, c.to_process_id, c.connection_type,
                   c.connection_status, c.connection_notes, c.date, c.action,
                   from_proc.sub_process_name as from_process_name,
                   to_proc.sub_process_name as to_process_name
            FROM supply_chain_connections c
            LEFT JOIN supply_chain_sub_processes from_proc ON c.from_process_id = from_proc.id
            LEFT JOIN supply_chain_sub_processes to_proc ON c.to_process_id = to_proc.id
            WHERE c.from_process_id = %s OR c.to_process_id = %s
            ORDER BY c.from_process_id, c.to_process_id
        """, (sub_process_id, sub_process_id))
        connections = cursor.fetchall()
        
        return render_template('process_detail.html',
                               process=sub_process,
                               inputs=inputs,
                               outputs=outputs,
                               connections=connections,
                               parent_process_name=sub_process[10] if sub_process else None)
        
    except Exception as e:
        print(f"Error in sub_process_detail route: {e}")
        return f"Error loading sub-process details: {e}", 500
    finally:
        cursor.close()
        connection.close()

@supply_chain_bp.route('/api/supply-chain/save-layout', methods=['POST'])
def save_layout():
    """Save DAG layout positions"""
    try:
        data = request.get_json()
        layout_data = data.get('layout_data')
        parent_process_id = data.get('parent_processId')
        
        if not layout_data or not parent_process_id:
            return jsonify({'success': False, 'error': 'Missing layout data or parent process ID'}), 400
        
        connection, cursor = db_conn()
        
        # Check if layout already exists for this parent process
        cursor.execute("""
            SELECT id FROM supply_chain_dag_layout 
            WHERE layout_data::text LIKE %s
        """, (f'%"parentProcessId":{parent_process_id}%',))
        
        existing_layout = cursor.fetchone()
        
        if existing_layout:
            # Update existing layout
            cursor.execute("""
                UPDATE supply_chain_dag_layout 
                SET layout_data = %s, layout_timestamp = %s, action = 'update'
                WHERE id = %s
            """, (json.dumps(layout_data), datetime.now(), existing_layout[0]))
        else:
            # Create new layout
            cursor.execute("""
                INSERT INTO supply_chain_dag_layout 
                (date, action, layout_data, layout_timestamp, uid)
                VALUES (%s, %s, %s, %s, %s)
            """, (datetime.now().date(), 'save', json.dumps(layout_data), datetime.now(), f'parent_{parent_process_id}'))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error saving layout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/load-layout/<int:parent_process_id>', methods=['GET'])
def load_layout(parent_process_id):
    """Load DAG layout positions for a parent process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT layout_data, layout_timestamp 
            FROM supply_chain_dag_layout 
            WHERE layout_data::text LIKE %s
            ORDER BY layout_timestamp DESC
            LIMIT 1
        """, (f'%"parentProcessId":{parent_process_id}%',))
        
        layout = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if layout:
            return jsonify({'success': True, 'layout': {'layout_data': layout[0], 'layout_timestamp': layout[1]}})
        else:
            return jsonify({'success': True, 'layout': None})
            
    except Exception as e:
        print(f"Error loading layout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/update-execution-order', methods=['POST'])
def update_execution_order():
    """Update execution order based on DAG connections"""
    try:
        data = request.get_json()
        parent_process_id = data.get('parent_process_id')
        execution_order = data.get('execution_order')  # List of sub_process_ids in order
        
        if not parent_process_id or not execution_order:
            return jsonify({'success': False, 'error': 'Missing parent_process_id or execution_order'}), 400
        
        connection, cursor = db_conn()
        
        # Update execution order for each sub process
        for order, sub_process_id in enumerate(execution_order, 1):
            cursor.execute("""
                UPDATE supply_chain_sub_processes 
                SET execution_order = %s, action = 'update_order'
                WHERE id = %s AND parent_process_id = %s
            """, (order, sub_process_id, parent_process_id))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error updating execution order: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/parent-processes/<int:parent_process_id>/inputs', methods=['GET'])
def get_inputs_by_parent(parent_process_id):
    """Get all inputs for sub processes of a specific parent process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT i.id, i.sub_process_id, i.input_name, i.input_type, 
                   i.input_specifications, i.input_quantity, i.input_unit, i.input_status,
                   sp.sub_process_name
            FROM supply_chain_inputs i
            JOIN supply_chain_sub_processes sp ON i.sub_process_id = sp.id
            WHERE sp.parent_process_id = %s
            ORDER BY sp.execution_order, i.input_name
        """, (parent_process_id,))
        
        inputs = cursor.fetchall()
        cursor.close()
        connection.close()
        
        # Convert to list of dictionaries for JSON response
        result = []
        for inp in inputs:
            result.append({
                'id': inp[0],
                'sub_process_id': inp[1],
                'input_name': inp[2],
                'input_type': inp[3],
                'input_specifications': inp[4],
                'input_quantity': inp[5],
                'input_unit': inp[6],
                'input_status': inp[7],
                'sub_process_name': inp[8]
            })
        
        return jsonify({'success': True, 'inputs': result})
        
    except Exception as e:
        print(f"Error getting inputs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/parent-processes/<int:parent_process_id>/outputs', methods=['GET'])
def get_outputs_by_parent(parent_process_id):
    """Get all outputs for sub processes of a specific parent process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT o.id, o.sub_process_id, o.output_name, o.output_type, 
                   o.output_specifications, o.output_quantity, o.output_unit, o.output_quality_status,
                   sp.sub_process_name
            FROM supply_chain_outputs o
            JOIN supply_chain_sub_processes sp ON o.sub_process_id = sp.id
            WHERE sp.parent_process_id = %s
            ORDER BY sp.execution_order, o.output_name
        """, (parent_process_id,))
        
        outputs = cursor.fetchall()
        cursor.close()
        connection.close()
        
        # Convert to list of dictionaries for JSON response
        result = []
        for out in outputs:
            result.append({
                'id': out[0],
                'sub_process_id': out[1],
                'output_name': out[2],
                'output_type': out[3],
                'output_specifications': out[4],
                'output_quantity': out[5],
                'output_unit': out[6],
                'output_quality_status': out[7],
                'sub_process_name': out[8]
            })
        
        return jsonify({'success': True, 'outputs': result})
        
    except Exception as e:
        print(f"Error getting outputs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/parent-processes/<int:parent_process_id>/connections', methods=['GET'])
def get_connections_by_parent(parent_process_id):
    """Get all connections between sub processes of a specific parent process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT c.id, c.from_sub_process_id, c.to_sub_process_id, c.connection_type, 
                   c.connection_notes, c.connection_status,
                   sp_from.sub_process_name as from_process_name,
                   sp_to.sub_process_name as to_process_name
            FROM supply_chain_connections c
            JOIN supply_chain_sub_processes sp_from ON c.from_sub_process_id = sp_from.id
            JOIN supply_chain_sub_processes sp_to ON c.to_sub_process_id = sp_to.id
            WHERE sp_from.parent_process_id = %s AND sp_to.parent_process_id = %s
            ORDER BY c.id
        """, (parent_process_id, parent_process_id))
        
        connections = cursor.fetchall()
        cursor.close()
        connection.close()
        
        # Convert to list of dictionaries for JSON response
        result = []
        for conn in connections:
            result.append({
                'id': conn[0],
                'from_sub_process_id': conn[1],
                'to_sub_process_id': conn[2],
                'connection_type': conn[3],
                'connection_notes': conn[4],
                'connection_status': conn[5],
                'from_process_name': conn[6],
                'to_process_name': conn[7]
            })
        
        return jsonify({'success': True, 'connections': result})
        
    except Exception as e:
        print(f"Error getting connections: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@supply_chain_bp.route('/supply-chain/process/<int:process_id>')
def process_detail(process_id):
    print(f"Accessed process detail for ID: {process_id}")
    connection, cursor = db_conn()

    try:
        # Get process details
        cursor.execute("""
            SELECT id, process_name, process_description, process_type, 
                   process_status, process_category, process_notes, date
            FROM supply_chain_processes
            WHERE id = %s
        """, (process_id,))
        process = cursor.fetchone()

        if not process:
            return render_template('process_detail.html', 
                                   process=None, 
                                   inputs=[], 
                                   outputs=[], 
                                   connections=[],
                                   error="Process not found")

        # Get inputs for this process
        cursor.execute("""
            SELECT id, input_name, input_type, input_quantity, input_unit,
                   input_specifications, input_source, input_batch_number,
                   input_expiry_date, input_status, date
            FROM supply_chain_inputs
            WHERE process_id = %s
            ORDER BY input_name
        """, (process_id,))
        inputs = cursor.fetchall()

        # Get outputs for this process
        cursor.execute("""
            SELECT id, output_name, output_type, output_quantity, output_unit,
                   output_specifications, output_batch_number, output_quality_status,
                   output_destination, date
            FROM supply_chain_outputs
            WHERE process_id = %s
            ORDER BY output_name
        """, (process_id,))
        outputs = cursor.fetchall()

        # Get connections for this process
        cursor.execute("""
            SELECT c.id, c.from_process_id, c.to_process_id, c.from_output_id, c.to_input_id,
                   c.connection_type, c.connection_status, c.connection_notes,
                   fp.process_name as from_process_name,
                   tp.process_name as to_process_name
            FROM supply_chain_connections c
            LEFT JOIN supply_chain_processes fp ON c.from_process_id = fp.id
            LEFT JOIN supply_chain_processes tp ON c.to_process_id = tp.id
            WHERE c.from_process_id = %s OR c.to_process_id = %s
            ORDER BY c.id
        """, (process_id, process_id))
        connections = cursor.fetchall()

        return render_template('process_detail.html',
                               process=process,
                               inputs=inputs,
                               outputs=outputs,
                               connections=connections)

    except Exception as e:
        print(f"Error in process_detail route: {e}")
        return render_template('process_detail.html', 
                               process=None,
                               inputs=[],
                               outputs=[],
                               connections=[],
                               error=str(e))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# API Routes for CRUD operations

@supply_chain_bp.route('/api/supply-chain/processes', methods=['POST'])
def create_process():
    """Create a new process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_processes 
            (date, action, process_name, process_description, process_type, 
             process_status, process_category, process_notes, is_managed, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            date.today(),
            'create',
            data.get('process_name'),
            data.get('process_description', ''),
            data.get('process_type', 'manufacturing'),
            data.get('process_status', 'active'),
            data.get('process_category', ''),
            data.get('process_notes', ''),
            data.get('is_managed', False),  # New processes start as unmanaged
            data.get('uid', '')
        ))
        
        process_id = cursor.fetchone()[0]
        connection.commit()
        
        return jsonify({'id': process_id, 'message': 'Process created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>', methods=['GET'])
def get_process(process_id):
    """Get a specific process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT id, process_name, process_description, process_type, 
                   process_status, process_category, process_notes, date, flow_through_enabled, is_managed
            FROM supply_chain_processes
            WHERE id = %s
        """, (process_id,))
        
        process = cursor.fetchone()
        if not process:
            return jsonify({'error': 'Process not found'}), 404
            
        return jsonify({
            'id': process[0],
            'process_name': process[1],
            'process_description': process[2],
            'process_type': process[3],
            'process_status': process[4],
            'process_category': process[5],
            'process_notes': process[6],
            'date': process[7].isoformat() if process[7] else None,
            'flow_through_enabled': process[8] or False,
            'is_managed': process[9] or False
        })
        
    except Exception as e:
        print(f"Error getting process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>', methods=['PUT'])
def update_process(process_id):
    """Update a process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            UPDATE supply_chain_processes 
            SET process_name = %s, process_description = %s, process_type = %s,
                process_status = %s, process_category = %s, process_notes = %s,
                action = 'update', date = %s
            WHERE id = %s
        """, (
            data.get('process_name'),
            data.get('process_description'),
            data.get('process_type'),
            data.get('process_status'),
            data.get('process_category'),
            data.get('process_notes'),
            date.today(),
            process_id
        ))
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Process not found'}), 404
            
        connection.commit()
        return jsonify({'message': 'Process updated successfully'})
        
    except Exception as e:
        print(f"Error updating process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>', methods=['DELETE'])
def delete_process(process_id):
    """Delete a process"""
    try:
        print(f"Delete process API called for process_id: {process_id}")
        connection, cursor = db_conn()
        
        # Check if process exists
        cursor.execute("SELECT id, process_name FROM supply_chain_processes WHERE id = %s", (process_id,))
        process = cursor.fetchone()
        if not process:
            print(f"Process {process_id} not found")
            return jsonify({'error': 'Process not found'}), 404
        
        print(f"Found process: {process[1]} (ID: {process[0]})")
        
        # Delete related records first
        print("Deleting related inputs...")
        cursor.execute("DELETE FROM supply_chain_inputs WHERE process_id = %s", (process_id,))
        inputs_deleted = cursor.rowcount
        print(f"Deleted {inputs_deleted} inputs")
        
        print("Deleting related outputs...")
        cursor.execute("DELETE FROM supply_chain_outputs WHERE process_id = %s", (process_id,))
        outputs_deleted = cursor.rowcount
        print(f"Deleted {outputs_deleted} outputs")
        
        print("Deleting related connections...")
        cursor.execute("DELETE FROM supply_chain_connections WHERE from_process_id = %s OR to_process_id = %s", (process_id, process_id))
        connections_deleted = cursor.rowcount
        print(f"Deleted {connections_deleted} connections")
        
        # Delete the process
        print("Deleting process...")
        cursor.execute("DELETE FROM supply_chain_processes WHERE id = %s", (process_id,))
        process_deleted = cursor.rowcount
        print(f"Deleted {process_deleted} processes")
        
        connection.commit()
        print("Transaction committed successfully")
        return jsonify({'message': 'Process deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def create_automatic_inputs_for_flow_through(process_id, connection, cursor):
    """Create automatic inputs in connected processes when flow-through is enabled"""
    try:
        # Get all outputs from this process that have individual field flow-through enabled
        cursor.execute("""
            SELECT id, output_name, output_type, output_quantity, output_unit, 
                   output_specifications, output_batch_number, output_destination,
                   flow_through_fields
            FROM supply_chain_outputs 
            WHERE process_id = %s AND flow_through_fields IS NOT NULL 
            AND flow_through_fields != '{}' AND flow_through_fields != 'null'
        """, (process_id,))
        
        flow_through_outputs = cursor.fetchall()
        
        if not flow_through_outputs:
            print(f"No flow-through outputs found for process {process_id}")
            return
        
        # Get all connections from this process
        cursor.execute("""
            SELECT to_process_id, connection_type
            FROM supply_chain_connections 
            WHERE from_process_id = %s AND connection_status = 'active'
        """, (process_id,))
        
        connections = cursor.fetchall()
        
        if not connections:
            print(f"No active connections found from process {process_id}")
            return
        
        # For each connection, create inputs in the receiving process
        for to_process_id, connection_type in connections:
            print(f"Processing connection to process {to_process_id} (type: {connection_type})")
            
            # Create inputs for each flow-through output (no need to check receiving process flow-through setting)
            for output in flow_through_outputs:
                output_id, output_name, output_type, output_quantity, output_unit, output_specifications, output_batch_number, output_destination, flow_through_fields = output
                
                # Parse flow-through fields
                flow_fields = flow_through_fields if isinstance(flow_through_fields, dict) else (json.loads(flow_through_fields) if flow_through_fields else {})
                
                # Skip if no fields are actually enabled for flow-through
                if not any(flow_fields.values()):
                    print(f"No fields enabled for flow-through in output '{output_name}'")
                    continue
                
                # Check if this input already exists (for update) or create new
                cursor.execute("""
                    SELECT id, input_name, input_type, input_quantity, input_unit, 
                           input_specifications, input_batch_number
                    FROM supply_chain_inputs 
                    WHERE process_id = %s AND input_source = %s
                """, (to_process_id, f"Flow-through from process {process_id}"))
                
                existing_input = cursor.fetchone()
                
                # Create the input with only the fields that are marked for flow-through
                input_name = output_name if flow_fields.get('output_name', False) else f"Flow-through from {output_name}"
                input_type = output_type if flow_fields.get('output_type', False) else 'flow_through'
                input_quantity = output_quantity if flow_fields.get('output_quantity', False) else None
                input_unit = output_unit if flow_fields.get('output_unit', False) else ''
                input_batch_number = output_batch_number if flow_fields.get('output_batch_number', False) else ''
                
                # Create enhanced specifications with flow-through info
                enhanced_specs = output_specifications if isinstance(output_specifications, dict) else (json.loads(output_specifications) if output_specifications else {})
                enhanced_specs['flow_through_source'] = f"Process {process_id}"
                enhanced_specs['flow_through_fields'] = flow_fields
                
                if flow_fields.get('output_notes', False) and 'notes' in enhanced_specs:
                    enhanced_specs['flow_through_notes'] = enhanced_specs['notes']
                
                if flow_fields.get('output_destination', False):
                    enhanced_specs['original_destination'] = output_destination
                
                if existing_input:
                    # Update existing input
                    cursor.execute("""
                        UPDATE supply_chain_inputs 
                        SET input_name = %s, input_type = %s, input_quantity = %s, 
                            input_unit = %s, input_specifications = %s, input_batch_number = %s,
                            date = CURRENT_DATE, action = 'update'
                        WHERE id = %s
                    """, (
                        input_name,
                        input_type,
                        input_quantity,
                        input_unit,
                        json.dumps(enhanced_specs),
                        input_batch_number,
                        existing_input[0]
                    ))
                    print(f"Updated input '{input_name}' in process {to_process_id} with flow-through fields: {flow_fields}")
                else:
                    # Create new input
                    cursor.execute("""
                        INSERT INTO supply_chain_inputs 
                        (date, action, process_id, input_name, input_type, input_quantity, 
                         input_unit, input_specifications, input_source, input_batch_number, 
                         input_status, uid)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        date.today(),
                        'create',
                        to_process_id,
                        input_name,
                        input_type,
                        input_quantity,
                        input_unit,
                        json.dumps(enhanced_specs),
                        f"Flow-through from process {process_id}",
                        input_batch_number,
                        'available',
                        ''
                    ))
                    print(f"Created input '{input_name}' in process {to_process_id} with flow-through fields: {flow_fields}")
        
        connection.commit()
        print(f"Automatic inputs created successfully for process {process_id}")
        
    except Exception as e:
        print(f"Error creating automatic inputs: {e}")
        connection.rollback()
        raise e

def cleanup_orphaned_flow_through_inputs(process_id, connection, cursor):
    """Clean up flow-through inputs that are no longer connected"""
    try:
        print(f"Cleaning up orphaned flow-through inputs for process {process_id}")
        
        # Get all current connections FROM this process
        cursor.execute("""
            SELECT to_process_id FROM supply_chain_connections 
            WHERE from_process_id = %s AND connection_status = 'active'
        """, (process_id,))
        
        connected_processes = [row[0] for row in cursor.fetchall()]
        print(f"Process {process_id} is connected to: {connected_processes}")
        
        # Find all flow-through inputs that claim to be from this process
        cursor.execute("""
            SELECT id, process_id, input_name FROM supply_chain_inputs 
            WHERE input_source = %s
        """, (f"Flow-through from process {process_id}",))
        
        flow_through_inputs = cursor.fetchall()
        print(f"Found {len(flow_through_inputs)} flow-through inputs from process {process_id}")
        
        # Remove inputs that are in processes no longer connected
        for input_id, target_process_id, input_name in flow_through_inputs:
            if target_process_id not in connected_processes:
                cursor.execute("DELETE FROM supply_chain_inputs WHERE id = %s", (input_id,))
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

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>/flow-through', methods=['PUT'])
def update_process_flow_through(process_id):
    """Update flow-through setting for a process"""
    try:
        data = request.get_json()
        flow_through_enabled = data.get('flow_through_enabled', False)
        
        connection, cursor = db_conn()
        
        cursor.execute("""
            UPDATE supply_chain_processes 
            SET flow_through_enabled = %s, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """, (flow_through_enabled, process_id))
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Process not found'}), 404
        
        connection.commit()
        
        # Check if we need to create automatic inputs for this process
        # Trigger if process flow-through is enabled
        if flow_through_enabled:
            create_automatic_inputs_for_flow_through(process_id, connection, cursor)
        
        return jsonify({
            'message': 'Flow-through setting updated successfully',
            'process_id': process_id,
            'flow_through_enabled': flow_through_enabled
        })
        
    except Exception as e:
        print(f"Error updating process flow-through: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>/has-connections', methods=['GET'])
def check_process_has_connections(process_id):
    """Check if a process has any connections, inputs, or outputs"""
    try:
        connection, cursor = db_conn()
        
        # Check for connections (as from_process or to_process)
        cursor.execute("""
            SELECT COUNT(*) FROM supply_chain_connections 
            WHERE from_process_id = %s OR to_process_id = %s
        """, (process_id, process_id))
        connection_count = cursor.fetchone()[0]
        
        # Check for inputs
        cursor.execute("""
            SELECT COUNT(*) FROM supply_chain_inputs 
            WHERE process_id = %s
        """, (process_id,))
        input_count = cursor.fetchone()[0]
        
        # Check for outputs
        cursor.execute("""
            SELECT COUNT(*) FROM supply_chain_outputs 
            WHERE process_id = %s
        """, (process_id,))
        output_count = cursor.fetchone()[0]
        
        has_connections = connection_count > 0
        has_inputs = input_count > 0
        has_outputs = output_count > 0
        has_any = has_connections or has_inputs or has_outputs
        
        return jsonify({
            'process_id': process_id,
            'has_connections': has_connections,
            'has_inputs': has_inputs,
            'has_outputs': has_outputs,
            'has_any': has_any,
            'connection_count': connection_count,
            'input_count': input_count,
            'output_count': output_count
        })
        
    except Exception as e:
        print(f"Error checking process connections: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>/move-to-unmanaged', methods=['PUT'])
def move_process_to_unmanaged(process_id):
    """Move a process to unmanaged status and delete all associated inputs, outputs, and connections using CRUD APIs"""
    try:
        print(f"Move to unmanaged API called for process_id: {process_id}")
        connection, cursor = db_conn()
        
        # Check if process exists
        cursor.execute("SELECT id, process_name FROM supply_chain_processes WHERE id = %s", (process_id,))
        process = cursor.fetchone()
        if not process:
            print(f"Process {process_id} not found")
            return jsonify({'error': 'Process not found'}), 404
        
        print(f"Found process: {process[1]} (ID: {process[0]})")
        
        # Get all inputs for this process
        cursor.execute("SELECT id FROM supply_chain_inputs WHERE process_id = %s", (process_id,))
        input_ids = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(input_ids)} inputs to delete")
        
        # Get all outputs for this process
        cursor.execute("SELECT id FROM supply_chain_outputs WHERE process_id = %s", (process_id,))
        output_ids = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(output_ids)} outputs to delete")
        
        # Get all connections for this process
        cursor.execute("SELECT id FROM supply_chain_connections WHERE from_process_id = %s OR to_process_id = %s", (process_id, process_id))
        connection_ids = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(connection_ids)} connections to delete")
        
        # Delete inputs using individual API calls
        inputs_deleted = 0
        for input_id in input_ids:
            try:
                cursor.execute("DELETE FROM supply_chain_inputs WHERE id = %s", (input_id,))
                if cursor.rowcount > 0:
                    inputs_deleted += 1
                    print(f"Deleted input {input_id}")
            except Exception as e:
                print(f"Error deleting input {input_id}: {e}")
        
        # Delete outputs using individual API calls
        outputs_deleted = 0
        for output_id in output_ids:
            try:
                cursor.execute("DELETE FROM supply_chain_outputs WHERE id = %s", (output_id,))
                if cursor.rowcount > 0:
                    outputs_deleted += 1
                    print(f"Deleted output {output_id}")
            except Exception as e:
                print(f"Error deleting output {output_id}: {e}")
        
        # Delete connections using individual API calls
        connections_deleted = 0
        for connection_id in connection_ids:
            try:
                cursor.execute("DELETE FROM supply_chain_connections WHERE id = %s", (connection_id,))
                if cursor.rowcount > 0:
                    connections_deleted += 1
                    print(f"Deleted connection {connection_id}")
            except Exception as e:
                print(f"Error deleting connection {connection_id}: {e}")
        
        # Update process to unmanaged
        print("Moving process to unmanaged...")
        cursor.execute("""
            UPDATE supply_chain_processes 
            SET is_managed = FALSE, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """, (process_id,))
        
        connection.commit()
        print("Transaction committed successfully")
        
        return jsonify({
            'message': 'Process moved to unmanaged successfully',
            'process_id': process_id,
            'process_name': process[1],
            'inputs_deleted': inputs_deleted,
            'outputs_deleted': outputs_deleted,
            'connections_deleted': connections_deleted
        })
        
    except Exception as e:
        print(f"Error moving process to unmanaged: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>/managed', methods=['PUT'])
def update_process_managed_status(process_id):
    """Update managed status for a process"""
    try:
        data = request.get_json()
        is_managed = data.get('is_managed', False)
        
        connection, cursor = db_conn()
        
        cursor.execute("""
            UPDATE supply_chain_processes 
            SET is_managed = %s, action = 'update', date = CURRENT_DATE
            WHERE id = %s
        """, (is_managed, process_id))
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Process not found'}), 404
        
        connection.commit()
        
        return jsonify({
            'message': 'Managed status updated successfully',
            'process_id': process_id,
            'is_managed': is_managed
        })
        
    except Exception as e:
        print(f"Error updating process managed status: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

@supply_chain_bp.route('/api/supply-chain/inputs', methods=['GET'])
def get_inputs():
    """Get all inputs or filter by process_id"""
    try:
        connection, cursor = db_conn()
        
        process_id = request.args.get('process_id')
        
        if process_id:
            cursor.execute("""
                SELECT i.id, i.process_id, i.input_name, i.input_type, i.input_quantity, 
                       i.input_unit, i.input_specifications, i.input_source, i.input_batch_number,
                       i.input_expiry_date, i.input_status, p.process_name
                FROM supply_chain_inputs i
                LEFT JOIN supply_chain_processes p ON i.process_id = p.id
                WHERE i.process_id = %s
                ORDER BY i.id DESC
            """, (process_id,))
        else:
            cursor.execute("""
                SELECT i.id, i.process_id, i.input_name, i.input_type, i.input_quantity, 
                       i.input_unit, i.input_specifications, i.input_source, i.input_batch_number,
                       i.input_expiry_date, i.input_status, p.process_name
                FROM supply_chain_inputs i
                LEFT JOIN supply_chain_processes p ON i.process_id = p.id
                ORDER BY i.id DESC
            """)
        
        inputs = cursor.fetchall()
        
        return jsonify([{
            'id': inp[0],
            'process_id': inp[1],
            'input_name': inp[2],
            'input_type': inp[3],
            'input_quantity': inp[4],
            'input_unit': inp[5],
            'input_specifications': inp[6],
            'input_source': inp[7],
            'input_batch_number': inp[8],
            'input_expiry_date': inp[9].isoformat() if inp[9] else None,
            'input_status': inp[10],
            'process_name': inp[11]
        } for inp in inputs])
        
    except Exception as e:
        print(f"Error getting inputs: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/inputs/<int:input_id>', methods=['GET'])
def get_input(input_id):
    """Get a specific input by ID"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT i.id, i.process_id, i.input_name, i.input_type, i.input_quantity, 
                   i.input_unit, i.input_specifications, i.input_source, i.input_batch_number,
                   i.input_expiry_date, i.input_status, p.process_name
            FROM supply_chain_inputs i
            LEFT JOIN supply_chain_processes p ON i.process_id = p.id
            WHERE i.id = %s
        """, (input_id,))
        
        inp = cursor.fetchone()
        if not inp:
            return jsonify({'error': 'Input not found'}), 404
        
        return jsonify({
            'id': inp[0],
            'process_id': inp[1],
            'input_name': inp[2],
            'input_type': inp[3],
            'input_quantity': inp[4],
            'input_unit': inp[5],
            'input_specifications': inp[6],
            'input_source': inp[7],
            'input_batch_number': inp[8],
            'input_expiry_date': inp[9].isoformat() if inp[9] else None,
            'input_status': inp[10],
            'process_name': inp[11]
        })
        
    except Exception as e:
        print(f"Error getting input: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/inputs/<int:input_id>', methods=['PUT'])
def update_input(input_id):
    """Update an input"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()
        
        # Check if input exists
        cursor.execute("SELECT id FROM supply_chain_inputs WHERE id = %s", (input_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Input not found'}), 404
        
        # Update input
        cursor.execute("""
            UPDATE supply_chain_inputs 
            SET input_name = %s, input_type = %s, input_quantity = %s, input_unit = %s,
                input_specifications = %s, input_source = %s, input_batch_number = %s,
                input_expiry_date = %s, input_status = %s, date = NOW(), action = 'update'
            WHERE id = %s
        """, (
            data.get('input_name'),
            data.get('input_type'),
            data.get('input_quantity'),
            data.get('input_unit'),
            json.dumps(data.get('input_specifications', {})),
            data.get('input_source'),
            data.get('input_batch_number'),
            data.get('input_expiry_date'),
            data.get('input_status'),
            input_id
        ))
        
        connection.commit()
        return jsonify({'message': 'Input updated successfully'})
        
    except Exception as e:
        print(f"Error updating input: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/inputs/<int:input_id>', methods=['DELETE'])
def delete_input(input_id):
    """Delete an input"""
    try:
        connection, cursor = db_conn()
        
        # Check if input exists
        cursor.execute("SELECT id FROM supply_chain_inputs WHERE id = %s", (input_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Input not found'}), 404
        
        # Delete the input
        cursor.execute("DELETE FROM supply_chain_inputs WHERE id = %s", (input_id,))
        
        connection.commit()
        return jsonify({'message': 'Input deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting input: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/inputs', methods=['POST'])
def create_input():
    """Create a new input"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_inputs 
            (date, action, process_id, input_name, input_type, input_quantity, 
             input_unit, input_specifications, input_source, input_batch_number,
             input_expiry_date, input_status, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            date.today(),
            'create',
            data.get('process_id'),
            data.get('input_name'),
            data.get('input_type', 'raw_material'),
            data.get('input_quantity'),
            data.get('input_unit'),
            json.dumps(data.get('input_specifications', {})),
            data.get('input_source', ''),
            data.get('input_batch_number', ''),
            data.get('input_expiry_date'),
            data.get('input_status', 'available'),
            data.get('uid', '')
        ))
        
        input_id = cursor.fetchone()[0]
        connection.commit()
        
        return jsonify({'id': input_id, 'message': 'Input created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating input: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/outputs', methods=['GET'])
def get_outputs():
    """Get all outputs or filter by process_id"""
    try:
        connection, cursor = db_conn()
        
        process_id = request.args.get('process_id')
        
        if process_id:
            cursor.execute("""
                SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity, 
                       o.output_unit, o.output_specifications, o.output_batch_number,
                       o.output_quality_status, o.output_destination, o.flow_through_enabled,
                       o.flow_through_fields, p.process_name
                FROM supply_chain_outputs o
                LEFT JOIN supply_chain_processes p ON o.process_id = p.id
                WHERE o.process_id = %s
                ORDER BY o.id DESC
            """, (process_id,))
        else:
            cursor.execute("""
                SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity, 
                       o.output_unit, o.output_specifications, o.output_batch_number,
                       o.output_quality_status, o.output_destination, o.flow_through_enabled,
                       o.flow_through_fields, p.process_name
                FROM supply_chain_outputs o
                LEFT JOIN supply_chain_processes p ON o.process_id = p.id
                ORDER BY o.id DESC
            """)
        
        outputs = cursor.fetchall()
        
        return jsonify([{
            'id': out[0],
            'process_id': out[1],
            'output_name': out[2],
            'output_type': out[3],
            'output_quantity': out[4],
            'output_unit': out[5],
            'output_specifications': out[6],
            'output_batch_number': out[7],
            'output_quality_status': out[8],
            'output_destination': out[9],
            'flow_through_enabled': out[10] or False,
            'flow_through_fields': out[11] or {},
            'process_name': out[12]
        } for out in outputs])
        
    except Exception as e:
        print(f"Error getting outputs: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/outputs/<int:output_id>', methods=['GET'])
def get_output(output_id):
    """Get a specific output by ID"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT o.id, o.process_id, o.output_name, o.output_type, o.output_quantity, 
                   o.output_unit, o.output_specifications, o.output_batch_number,
                   o.output_quality_status, o.output_destination, o.flow_through_enabled,
                   o.flow_through_fields, p.process_name
            FROM supply_chain_outputs o
            LEFT JOIN supply_chain_processes p ON o.process_id = p.id
            WHERE o.id = %s
        """, (output_id,))
        
        out = cursor.fetchone()
        if not out:
            return jsonify({'error': 'Output not found'}), 404
        
        return jsonify({
            'id': out[0],
            'process_id': out[1],
            'output_name': out[2],
            'output_type': out[3],
            'output_quantity': out[4],
            'output_unit': out[5],
            'output_specifications': out[6],
            'output_batch_number': out[7],
            'output_quality_status': out[8],
            'output_destination': out[9],
            'flow_through_enabled': out[10] or False,
            'flow_through_fields': out[11] or {},
            'process_name': out[12]
        })
        
    except Exception as e:
        print(f"Error getting output: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/outputs/<int:output_id>', methods=['PUT'])
def update_output(output_id):
    """Update an output"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()
        
        # Check if output exists and get process_id
        cursor.execute("SELECT id, process_id FROM supply_chain_outputs WHERE id = %s", (output_id,))
        output_record = cursor.fetchone()
        if not output_record:
            return jsonify({'error': 'Output not found'}), 404
        
        process_id = output_record[1]
        
        # Update output
        cursor.execute("""
            UPDATE supply_chain_outputs 
            SET output_name = %s, output_type = %s, output_quantity = %s, output_unit = %s,
                output_specifications = %s, output_batch_number = %s,
                output_quality_status = %s, output_destination = %s, flow_through_enabled = %s,
                flow_through_fields = %s, date = NOW(), action = 'update'
            WHERE id = %s
        """, (
            data.get('output_name'),
            data.get('output_type'),
            data.get('output_quantity'),
            data.get('output_unit'),
            json.dumps(data.get('output_specifications', {})),
            data.get('output_batch_number'),
            data.get('output_quality_status'),
            data.get('output_destination'),
            data.get('flow_through_enabled', False),
            json.dumps(data.get('flow_through_fields', {})),
            output_id
        ))
        
        connection.commit()
        
        # Check if we need to create automatic inputs for this output
        # Trigger if any individual fields are marked for flow-through
        flow_through_fields = data.get('flow_through_fields', {})
        has_flow_through_fields = any(flow_through_fields.values()) if isinstance(flow_through_fields, dict) else False
        
        if has_flow_through_fields:
            create_automatic_inputs_for_flow_through(process_id, connection, cursor)
        
        return jsonify({'message': 'Output updated successfully'})
        
    except Exception as e:
        print(f"Error updating output: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/outputs/<int:output_id>', methods=['DELETE'])
def delete_output(output_id):
    """Delete an output"""
    try:
        connection, cursor = db_conn()
        
        # Check if output exists
        cursor.execute("SELECT id FROM supply_chain_outputs WHERE id = %s", (output_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Output not found'}), 404
        
        # Delete the output
        cursor.execute("DELETE FROM supply_chain_outputs WHERE id = %s", (output_id,))
        
        connection.commit()
        return jsonify({'message': 'Output deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting output: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/outputs', methods=['POST'])
def create_output():
    """Create a new output"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_outputs 
            (date, action, process_id, output_name, output_type, output_quantity, 
             output_unit, output_specifications, output_batch_number, 
             output_quality_status, output_destination, flow_through_enabled, flow_through_fields, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            date.today(),
            'create',
            data.get('process_id'),
            data.get('output_name'),
            data.get('output_type', 'finished_product'),
            data.get('output_quantity'),
            data.get('output_unit'),
            json.dumps(data.get('output_specifications', {})),
            data.get('output_batch_number', ''),
            data.get('output_quality_status', 'pending'),
            data.get('output_destination', ''),
            data.get('flow_through_enabled', False),
            json.dumps(data.get('flow_through_fields', {})),
            data.get('uid', '')
        ))
        
        output_id = cursor.fetchone()[0]
        connection.commit()
        
        # Check if we need to create automatic inputs for this output
        # Trigger if any individual fields are marked for flow-through
        flow_through_fields = data.get('flow_through_fields', {})
        has_flow_through_fields = any(flow_through_fields.values()) if isinstance(flow_through_fields, dict) else False
        
        if has_flow_through_fields:
            create_automatic_inputs_for_flow_through(data.get('process_id'), connection, cursor)
        
        return jsonify({'id': output_id, 'message': 'Output created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating output: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/connections', methods=['GET'])
def get_connections():
    """Get all connections for visual display"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT c.id, c.from_process_id, c.to_process_id, c.connection_type, 
                   c.connection_status, c.connection_notes,
                   fp.process_name as from_process_name,
                   tp.process_name as to_process_name
            FROM supply_chain_connections c
            LEFT JOIN supply_chain_processes fp ON c.from_process_id = fp.id
            LEFT JOIN supply_chain_processes tp ON c.to_process_id = tp.id
            ORDER BY c.id
        """)
        
        connections = cursor.fetchall()
        
        return jsonify([{
            'id': conn[0],
            'from_process_id': conn[1],
            'to_process_id': conn[2],
            'connection_type': conn[3],
            'connection_status': conn[4],
            'connection_notes': conn[5],
            'from_process_name': conn[6],
            'to_process_name': conn[7]
        } for conn in connections])
        
    except Exception as e:
        print(f"Error getting connections: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/connections', methods=['POST'])
def create_connection():
    """Create a new connection between processes"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        # Check if connection already exists
        cursor.execute("""
            SELECT id FROM supply_chain_connections 
            WHERE from_sub_process_id = %s AND to_sub_process_id = %s AND connection_type = %s
        """, (data.get('from_sub_process_id'), data.get('to_sub_process_id'), data.get('connection_type', 'direct')))
        
        if cursor.fetchone():
            return jsonify({'error': 'Connection already exists with the same From process, To process, and connection type'}), 409
        
        cursor.execute("""
            INSERT INTO supply_chain_connections 
            (date, action, parent_process_id, from_sub_process_id, to_sub_process_id, from_output_id, 
             to_input_id, connection_type, connection_status, connection_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            date.today(),
            'create',
            data.get('parent_process_id'),
            data.get('from_sub_process_id'),
            data.get('to_sub_process_id'),
            data.get('from_output_id'),
            data.get('to_input_id'),
            data.get('connection_type', 'direct'),
            data.get('connection_status', 'active'),
            data.get('connection_notes', ''),
            data.get('uid', '')
        ))
        
        connection_id = cursor.fetchone()[0]
        connection.commit()
        
        # Update flow-through inputs for the source process
        from_process_id = data.get('from_process_id')
        if from_process_id:
            update_flow_through_for_connection_changes(from_process_id, connection, cursor)
        
        return jsonify({'id': connection_id, 'message': 'Connection created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating connection: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/traceability', methods=['GET'])
def get_all_traces():
    """Get all traceability records"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT t.id, t.trace_id, t.item_name, t.item_type, t.current_location, 
                   t.current_process_id, t.trace_path, t.trace_status, t.trace_notes,
                   p.process_name
            FROM supply_chain_traceability t
            LEFT JOIN supply_chain_processes p ON t.current_process_id = p.id
            ORDER BY t.id DESC
        """)
        
        traces = cursor.fetchall()
        
        return jsonify([{
            'id': trace[0],
            'trace_id': trace[1],
            'item_name': trace[2],
            'item_type': trace[3],
            'current_location': trace[4],
            'current_process_id': trace[5],
            'trace_path': trace[6],
            'trace_status': trace[7],
            'trace_notes': trace[8],
            'process_name': trace[9]
        } for trace in traces])
        
    except Exception as e:
        print(f"Error getting traceability records: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/traceability/<trace_id>', methods=['PUT'])
def update_trace(trace_id):
    """Update a traceability record"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()
        
        # Check if trace exists
        cursor.execute("SELECT id FROM supply_chain_traceability WHERE trace_id = %s", (trace_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Traceability record not found'}), 404
        
        # Update trace
        cursor.execute("""
            UPDATE supply_chain_traceability 
            SET item_name = %s, item_type = %s, current_location = %s,
                current_process_id = %s, trace_path = %s, trace_status = %s,
                trace_notes = %s, date = NOW(), action = 'update'
            WHERE trace_id = %s
        """, (
            data.get('item_name'),
            data.get('item_type'),
            data.get('current_location'),
            data.get('current_process_id'),
            data.get('trace_path'),
            data.get('trace_status'),
            data.get('trace_notes'),
            trace_id
        ))
        
        connection.commit()
        return jsonify({'message': 'Traceability record updated successfully'})
        
    except Exception as e:
        print(f"Error updating traceability record: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/traceability/<trace_id>', methods=['DELETE'])
def delete_trace(trace_id):
    """Delete a traceability record"""
    try:
        connection, cursor = db_conn()
        
        # Check if trace exists
        cursor.execute("SELECT id FROM supply_chain_traceability WHERE trace_id = %s", (trace_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Traceability record not found'}), 404
        
        # Delete the trace
        cursor.execute("DELETE FROM supply_chain_traceability WHERE trace_id = %s", (trace_id,))
        
        connection.commit()
        return jsonify({'message': 'Traceability record deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting traceability record: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/traceability', methods=['POST'])
def create_trace():
    """Create a new traceability record"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_traceability 
            (date, action, trace_id, item_name, item_type, current_location, 
             current_process_id, trace_path, trace_status, trace_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            date.today(),
            'create',
            data.get('trace_id'),
            data.get('item_name'),
            data.get('item_type'),
            data.get('current_location'),
            data.get('current_process_id'),
            json.dumps(data.get('trace_path', [])),
            data.get('trace_status', 'active'),
            data.get('trace_notes', ''),
            data.get('uid', '')
        ))
        
        trace_id = cursor.fetchone()[0]
        connection.commit()
        
        return jsonify({'id': trace_id, 'message': 'Traceability record created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating traceability record: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/traceability/<trace_id>', methods=['GET'])
def get_trace(trace_id):
    """Get traceability information for a specific item"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT id, trace_id, item_name, item_type, current_location, 
                   current_process_id, trace_path, trace_status, trace_notes, date
            FROM supply_chain_traceability
            WHERE trace_id = %s
        """, (trace_id,))
        
        trace = cursor.fetchone()
        if not trace:
            return jsonify({'error': 'Trace not found'}), 404
            
        return jsonify({
            'id': trace[0],
            'trace_id': trace[1],
            'item_name': trace[2],
            'item_type': trace[3],
            'current_location': trace[4],
            'current_process_id': trace[5],
            'trace_path': json.loads(trace[6]) if trace[6] else [],
            'trace_status': trace[7],
            'trace_notes': trace[8],
            'date': trace[9].isoformat() if trace[9] else None
        })
        
    except Exception as e:
        print(f"Error getting trace: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes', methods=['GET'])
def get_all_processes():
    """Get all processes for connection dropdowns"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT id, process_name, process_type, process_status, is_managed
            FROM supply_chain_processes
            ORDER BY process_name
        """)
        
        processes = cursor.fetchall()
        
        return jsonify([{
            'id': process[0],
            'process_name': process[1],
            'process_type': process[2],
            'process_status': process[3],
            'is_managed': process[4] or False
        } for process in processes])
        
    except Exception as e:
        print(f"Error getting processes: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/connections/<int:connection_id>', methods=['GET'])
def get_connection(connection_id):
    """Get a specific connection by ID"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT c.id, c.from_process_id, c.to_process_id, c.connection_type, 
                   c.connection_status, c.connection_notes, c.from_output_id, c.to_input_id,
                   fp.process_name as from_process_name,
                   tp.process_name as to_process_name
            FROM supply_chain_connections c
            LEFT JOIN supply_chain_processes fp ON c.from_process_id = fp.id
            LEFT JOIN supply_chain_processes tp ON c.to_process_id = tp.id
            WHERE c.id = %s
        """, (connection_id,))
        
        conn = cursor.fetchone()
        if not conn:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({
            'id': conn[0],
            'from_process_id': conn[1],
            'to_process_id': conn[2],
            'connection_type': conn[3],
            'connection_status': conn[4],
            'connection_notes': conn[5],
            'from_output_id': conn[6],
            'to_input_id': conn[7],
            'from_process_name': conn[8],
            'to_process_name': conn[9]
        })
        
    except Exception as e:
        print(f"Error getting connection: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/connections/<int:connection_id>', methods=['PUT'])
def update_connection(connection_id):
    """Update a connection"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()
        
        # Check if connection exists
        cursor.execute("SELECT id FROM supply_chain_connections WHERE id = %s", (connection_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Connection not found'}), 404
        
        # Update connection
        cursor.execute("""
            UPDATE supply_chain_connections 
            SET connection_type = %s, connection_status = %s, connection_notes = %s,
                from_output_id = %s, to_input_id = %s, date = NOW(), action = 'update'
            WHERE id = %s
        """, (
            data.get('connection_type'),
            data.get('connection_status'),
            data.get('connection_notes'),
            data.get('from_output_id'),
            data.get('to_input_id'),
            connection_id
        ))
        
        connection.commit()
        return jsonify({'message': 'Connection updated successfully'})
        
    except Exception as e:
        print(f"Error updating connection: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>/activate', methods=['POST'])
def activate_process(process_id):
    """Activate a process for batch execution"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()
        
        # Check if process exists
        cursor.execute("SELECT id, process_name FROM supply_chain_processes WHERE id = %s", (process_id,))
        process = cursor.fetchone()
        if not process:
            return jsonify({'error': 'Process not found'}), 404
        
        # Create process template if it doesn't exist
        cursor.execute("""
            INSERT INTO supply_chain_process_templates 
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
        """, (
            process_id,
            f"{process[1]} Template",
            json.dumps(data.get('default_inputs', [])),
            json.dumps(data.get('default_outputs', [])),
            json.dumps(data.get('default_variables', {})),
            data.get('template_notes', ''),
            data.get('uid', 'system')
        ))
        
        # Update process status to active
        cursor.execute("""
            UPDATE supply_chain_processes 
            SET process_status = 'active', date = NOW(), action = 'activate'
            WHERE id = %s
        """, (process_id,))
        
        connection.commit()
        return jsonify({'message': 'Process activated successfully'})
        
    except Exception as e:
        print(f"Error activating process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/processes/<int:process_id>/execute', methods=['POST'])
def execute_process(process_id):
    """Execute a process with batch data"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()
        
        # Check if process exists and is active
        cursor.execute("""
            SELECT id, process_name, process_status 
            FROM supply_chain_processes 
            WHERE id = %s
        """, (process_id,))
        process = cursor.fetchone()
        if not process:
            return jsonify({'error': 'Process not found'}), 404
        if process[2] != 'active':
            return jsonify({'error': 'Process must be active to execute'}), 400
        
        # Generate batch number if not provided
        batch_number = data.get('execution_batch_number')
        if not batch_number:
            batch_number = f"{process[1].replace(' ', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create execution record
        cursor.execute("""
            INSERT INTO supply_chain_process_executions 
            (date, action, process_id, execution_batch_number, execution_status, 
             execution_start_time, execution_notes, execution_variables, uid)
            VALUES (NOW(), 'create', %s, %s, 'in_progress', NOW(), %s, %s, %s)
            RETURNING id
        """, (
            process_id,
            batch_number,
            data.get('execution_notes', ''),
            json.dumps(data.get('execution_variables', {})),
            data.get('uid', 'system')
        ))
        
        execution_id = cursor.fetchone()[0]
        
        # Create execution inputs
        for input_data in data.get('execution_inputs', []):
            cursor.execute("""
                INSERT INTO supply_chain_execution_inputs 
                (date, action, execution_id, input_template_id, actual_input_name,
                 actual_input_quantity, actual_input_unit, actual_input_batch_number,
                 actual_input_source, input_consumption_time, input_quality_status, 
                 input_notes, uid)
                VALUES (NOW(), 'create', %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
            """, (
                execution_id,
                input_data.get('input_template_id'),
                input_data.get('actual_input_name'),
                input_data.get('actual_input_quantity'),
                input_data.get('actual_input_unit'),
                input_data.get('actual_input_batch_number'),
                input_data.get('actual_input_source'),
                input_data.get('input_quality_status', 'passed'),
                input_data.get('input_notes', ''),
                data.get('uid', 'system')
            ))
        
        connection.commit()
        return jsonify({
            'message': 'Process execution started successfully',
            'execution_id': execution_id,
            'batch_number': batch_number
        })
        
    except Exception as e:
        print(f"Error executing process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/executions/<int:execution_id>/complete', methods=['POST'])
def complete_execution(execution_id):
    """Complete a process execution and record outputs"""
    try:
        connection, cursor = db_conn()
        data = request.get_json()
        
        # Check if execution exists
        cursor.execute("SELECT id, process_id FROM supply_chain_process_executions WHERE id = %s", (execution_id,))
        execution = cursor.fetchone()
        if not execution:
            return jsonify({'error': 'Execution not found'}), 404
        
        # Create execution outputs
        for output_data in data.get('execution_outputs', []):
            cursor.execute("""
                INSERT INTO supply_chain_execution_outputs 
                (date, action, execution_id, output_template_id, actual_output_name,
                 actual_output_quantity, actual_output_unit, actual_output_batch_number,
                 actual_output_quality_status, actual_output_destination, 
                 output_production_time, output_notes, uid)
                VALUES (NOW(), 'create', %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
            """, (
                execution_id,
                output_data.get('output_template_id'),
                output_data.get('actual_output_name'),
                output_data.get('actual_output_quantity'),
                output_data.get('actual_output_unit'),
                output_data.get('actual_output_batch_number'),
                output_data.get('actual_output_quality_status', 'passed'),
                output_data.get('actual_output_destination'),
                output_data.get('output_notes', ''),
                data.get('uid', 'system')
            ))
        
        # Update execution status
        cursor.execute("""
            UPDATE supply_chain_process_executions 
            SET execution_status = 'completed', execution_end_time = NOW(),
                execution_quality_checks = %s, date = NOW(), action = 'complete'
            WHERE id = %s
        """, (
            json.dumps(data.get('execution_quality_checks', {})),
            execution_id
        ))
        
        connection.commit()
        return jsonify({'message': 'Process execution completed successfully'})
        
    except Exception as e:
        print(f"Error completing execution: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/connections/<int:connection_id>/details', methods=['GET'])
def get_connection_details(connection_id):
    """Get detailed connection information including linked inputs/outputs"""
    try:
        connection, cursor = db_conn()
        
        # Get connection details
        cursor.execute("""
            SELECT c.id, c.from_process_id, c.to_process_id, c.from_output_id, c.to_input_id,
                   c.connection_type, c.connection_status, c.connection_notes,
                   fp.process_name as from_process_name,
                   tp.process_name as to_process_name
            FROM supply_chain_connections c
            LEFT JOIN supply_chain_processes fp ON c.from_process_id = fp.id
            LEFT JOIN supply_chain_processes tp ON c.to_process_id = tp.id
            WHERE c.id = %s
        """, (connection_id,))
        
        conn = cursor.fetchone()
        if not conn:
            return jsonify({'error': 'Connection not found'}), 404
        
        # Get linked output details
        linked_output = None
        if conn[4]:  # from_output_id
            cursor.execute("""
                SELECT id, output_name, output_type, output_quantity, output_unit, output_specifications
                FROM supply_chain_outputs
                WHERE id = %s
            """, (conn[4],))
            linked_output = cursor.fetchone()
        
        # Get linked input details
        linked_input = None
        if conn[5]:  # to_input_id
            cursor.execute("""
                SELECT id, input_name, input_type, input_quantity, input_unit, input_specifications
                FROM supply_chain_inputs
                WHERE id = %s
            """, (conn[5],))
            linked_input = cursor.fetchone()
        
        # Get all outputs from source process
        cursor.execute("""
            SELECT id, output_name, output_type, output_quantity, output_unit
            FROM supply_chain_outputs
            WHERE process_id = %s
            ORDER BY output_name
        """, (conn[1],))
        available_outputs = cursor.fetchall()
        
        # Get all inputs from destination process
        cursor.execute("""
            SELECT id, input_name, input_type, input_quantity, input_unit
            FROM supply_chain_inputs
            WHERE process_id = %s
            ORDER BY input_name
        """, (conn[2],))
        available_inputs = cursor.fetchall()
        
        return jsonify({
            'connection': {
                'id': conn[0],
                'from_process_id': conn[1],
                'to_process_id': conn[2],
                'from_output_id': conn[4],
                'to_input_id': conn[5],
                'connection_type': conn[6],
                'connection_status': conn[7],
                'connection_notes': conn[8],
                'from_process_name': conn[9],
                'to_process_name': conn[10]
            },
            'linked_output': {
                'id': linked_output[0],
                'output_name': linked_output[1],
                'output_type': linked_output[2],
                'output_quantity': linked_output[3],
                'output_unit': linked_output[4],
                'output_specifications': linked_output[5]
            } if linked_output else None,
            'linked_input': {
                'id': linked_input[0],
                'input_name': linked_input[1],
                'input_type': linked_input[2],
                'input_quantity': linked_input[3],
                'input_unit': linked_input[4],
                'input_specifications': linked_input[5]
            } if linked_input else None,
            'available_outputs': [{
                'id': out[0],
                'output_name': out[1],
                'output_type': out[2],
                'output_quantity': out[3],
                'output_unit': out[4]
            } for out in available_outputs],
            'available_inputs': [{
                'id': inp[0],
                'input_name': inp[1],
                'input_type': inp[2],
                'input_quantity': inp[3],
                'input_unit': inp[4]
            } for inp in available_inputs]
        })
        
    except Exception as e:
        print(f"Error getting connection details: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
@supply_chain_bp.route('/api/supply-chain/connections/<int:connection_id>/auto-link', methods=['POST'])
def auto_link_connection(connection_id):
    """Automatically link outputs from source process to inputs of destination process"""
    try:
        connection, cursor = db_conn()
        
        # Get connection details
        cursor.execute("""
            SELECT c.from_process_id, c.to_process_id, c.from_output_id, c.to_input_id
            FROM supply_chain_connections c
            WHERE c.id = %s
        """, (connection_id,))
        conn = cursor.fetchone()
        if not conn:
            return jsonify({'error': 'Connection not found'}), 404
        
        from_process_id, to_process_id, from_output_id, to_input_id = conn
        
        # Get outputs from source process
        cursor.execute("""
            SELECT id, output_name, output_type, output_quantity, output_unit
            FROM supply_chain_outputs
            WHERE process_id = %s
        """, (from_process_id,))
        outputs = cursor.fetchall()
        
        # Get inputs for destination process
        cursor.execute("""
            SELECT id, input_name, input_type, input_quantity, input_unit
            FROM supply_chain_inputs
            WHERE process_id = %s
        """, (to_process_id,))
        inputs = cursor.fetchall()
        
        # Auto-link matching outputs to inputs
        linked_count = 0
        for output in outputs:
            output_id, output_name, output_type, output_qty, output_unit = output
            
            # Find matching input by name or type
            for input_record in inputs:
                input_id, input_name, input_type, input_qty, input_unit = input_record
                
                # Match by name or type
                if (output_name.lower() == input_name.lower() or 
                    output_type.lower() == input_type.lower()):
                    
                    # Update connection to link specific output to input
                    cursor.execute("""
                        UPDATE supply_chain_connections 
                        SET from_output_id = %s, to_input_id = %s, date = NOW(), action = 'auto_link'
                        WHERE id = %s
                    """, (output_id, input_id, connection_id))
                    linked_count += 1
                    break
        
        connection.commit()
        return jsonify({
            'message': f'Auto-linked {linked_count} output-input pairs',
            'linked_count': linked_count
        })
        
    except Exception as e:
        print(f"Error auto-linking connection: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/connections/<int:connection_id>', methods=['DELETE'])
def delete_connection(connection_id):
    """Delete a connection"""
    try:
        connection, cursor = db_conn()
        
        # Check if connection exists and get from_process_id
        cursor.execute("SELECT id, from_process_id FROM supply_chain_connections WHERE id = %s", (connection_id,))
        connection_data = cursor.fetchone()
        if not connection_data:
            return jsonify({'error': 'Connection not found'}), 404
        
        from_process_id = connection_data[1]
        
        # Delete the connection
        cursor.execute("DELETE FROM supply_chain_connections WHERE id = %s", (connection_id,))
        
        connection.commit()
        
        # Update flow-through inputs for the source process
        if from_process_id:
            update_flow_through_for_connection_changes(from_process_id, connection, cursor)
        
        return jsonify({'message': 'Connection deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting connection: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/dag-layout', methods=['POST'])
def save_dag_layout():
    """Save DAG layout positions to database for a specific parent process"""
    connection = None
    cursor = None
    try:
        data = request.get_json()
        parent_process_id = data.get('parent_process_id')
        layout_data = data.get('layout_data')
        
        if not parent_process_id or not layout_data:
            return jsonify({'success': False, 'error': 'Missing parent_process_id or layout_data'}), 400
        
        connection, cursor = db_conn()
        
        # Check if layout already exists for this parent process
        cursor.execute("""
            SELECT id FROM supply_chain_dag_layout 
            WHERE layout_data::text LIKE %s
        """, (f'%"parentProcessId":{parent_process_id}%',))
        
        existing_layout = cursor.fetchone()
        
        if existing_layout:
            # Update existing layout
            cursor.execute("""
                UPDATE supply_chain_dag_layout 
                SET layout_data = %s, layout_timestamp = %s, action = 'update'
                WHERE id = %s
            """, (json.dumps(layout_data), datetime.now(), existing_layout[0]))
        else:
            # Create new layout
            cursor.execute("""
                INSERT INTO supply_chain_dag_layout 
                (date, action, layout_data, layout_timestamp, uid)
                VALUES (%s, %s, %s, %s, %s)
            """, (datetime.now().date(), 'save', json.dumps(layout_data), datetime.now(), f'parent_{parent_process_id}'))
        
        connection.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error saving DAG layout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/dag-layout/<int:parent_process_id>', methods=['GET'])
def get_dag_layout(parent_process_id):
    """Get saved DAG layout positions for a specific parent process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT layout_data, layout_timestamp 
            FROM supply_chain_dag_layout 
            WHERE layout_data::text LIKE %s
            ORDER BY layout_timestamp DESC
            LIMIT 1
        """, (f'%"parentProcessId":{parent_process_id}%',))
        
        layout = cursor.fetchone()
        cursor.close()
        connection.close()
        
        if layout:
            return jsonify({'success': True, 'layout': {'layout_data': layout[0], 'layout_timestamp': layout[1]}})
        else:
            return jsonify({'success': True, 'layout': None})
            
    except Exception as e:
        print(f"Error loading DAG layout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/dag-layout', methods=['DELETE'])
def delete_dag_layout():
    """Delete saved DAG layout positions"""
    try:
        connection, cursor = db_conn()
        
        # Clear all layout data
        cursor.execute("DELETE FROM supply_chain_dag_layout")
        
        connection.commit()
        return jsonify({'message': 'DAG layout deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting DAG layout: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# Parent Process API Routes

@supply_chain_bp.route('/api/supply-chain/parent-processes', methods=['POST'])
def create_parent_process():
    """Create a new parent process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_parent_processes 
            (date, action, parent_process_name, parent_process_description, parent_process_type, 
             parent_process_status, parent_process_category, parent_process_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            date.today(),
            'create',
            data.get('parent_process_name'),
            data.get('parent_process_description', ''),
            data.get('parent_process_type', 'production_workflow'),
            data.get('parent_process_status', 'active'),
            data.get('parent_process_category', ''),
            data.get('parent_process_notes', ''),
            data.get('uid', '')
        ))
        
        parent_process_id = cursor.fetchone()[0]
        connection.commit()
        
        return jsonify({'id': parent_process_id, 'message': 'Parent process created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating parent process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/parent-processes/<int:parent_process_id>', methods=['GET'])
def get_parent_process(parent_process_id):
    """Get a specific parent process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT id, parent_process_name, parent_process_description, parent_process_type, 
                   parent_process_status, parent_process_category, parent_process_notes, date
            FROM supply_chain_parent_processes
            WHERE id = %s
        """, (parent_process_id,))
        
        parent_process = cursor.fetchone()
        if not parent_process:
            return jsonify({'error': 'Parent process not found'}), 404
            
        return jsonify({
            'id': parent_process[0],
            'parent_process_name': parent_process[1],
            'parent_process_description': parent_process[2],
            'parent_process_type': parent_process[3],
            'parent_process_status': parent_process[4],
            'parent_process_category': parent_process[5],
            'parent_process_notes': parent_process[6],
            'date': parent_process[7].isoformat() if parent_process[7] else None
        })
        
    except Exception as e:
        print(f"Error getting parent process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/parent-processes/<int:parent_process_id>', methods=['PUT'])
def update_parent_process(parent_process_id):
    """Update a parent process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            UPDATE supply_chain_parent_processes 
            SET parent_process_name = %s, parent_process_description = %s, parent_process_type = %s,
                parent_process_status = %s, parent_process_category = %s, parent_process_notes = %s,
                action = 'update', date = %s
            WHERE id = %s
        """, (
            data.get('parent_process_name'),
            data.get('parent_process_description'),
            data.get('parent_process_type'),
            data.get('parent_process_status'),
            data.get('parent_process_category'),
            data.get('parent_process_notes'),
            date.today(),
            parent_process_id
        ))
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Parent process not found'}), 404
            
        connection.commit()
        return jsonify({'message': 'Parent process updated successfully'})
        
    except Exception as e:
        print(f"Error updating parent process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/parent-processes/<int:parent_process_id>', methods=['DELETE'])
def delete_parent_process(parent_process_id):
    """Delete a parent process and all its sub processes"""
    try:
        print(f"Delete parent process API called for parent_process_id: {parent_process_id}")
        connection, cursor = db_conn()
        
        # Check if parent process exists
        cursor.execute("SELECT id, parent_process_name FROM supply_chain_parent_processes WHERE id = %s", (parent_process_id,))
        parent_process = cursor.fetchone()
        if not parent_process:
            print(f"Parent process {parent_process_id} not found")
            return jsonify({'error': 'Parent process not found'}), 404
        
        print(f"Found parent process: {parent_process[1]} (ID: {parent_process[0]})")
        
        # Get all sub processes for this parent
        cursor.execute("SELECT id FROM supply_chain_sub_processes WHERE parent_process_id = %s", (parent_process_id,))
        sub_process_ids = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(sub_process_ids)} sub processes to delete")
        
        # Delete inputs, outputs, and connections for each sub process
        for sub_process_id in sub_process_ids:
            # Delete inputs
            cursor.execute("DELETE FROM supply_chain_inputs WHERE sub_process_id = %s", (sub_process_id,))
            inputs_deleted = cursor.rowcount
            print(f"Deleted {inputs_deleted} inputs for sub process {sub_process_id}")
            
            # Delete outputs
            cursor.execute("DELETE FROM supply_chain_outputs WHERE sub_process_id = %s", (sub_process_id,))
            outputs_deleted = cursor.rowcount
            print(f"Deleted {outputs_deleted} outputs for sub process {sub_process_id}")
            
            # Delete connections
            cursor.execute("DELETE FROM supply_chain_connections WHERE from_sub_process_id = %s OR to_sub_process_id = %s", (sub_process_id, sub_process_id))
            connections_deleted = cursor.rowcount
            print(f"Deleted {connections_deleted} connections for sub process {sub_process_id}")
        
        # Delete all sub processes
        cursor.execute("DELETE FROM supply_chain_sub_processes WHERE parent_process_id = %s", (parent_process_id,))
        sub_processes_deleted = cursor.rowcount
        print(f"Deleted {sub_processes_deleted} sub processes")
        
        # Delete the parent process
        cursor.execute("DELETE FROM supply_chain_parent_processes WHERE id = %s", (parent_process_id,))
        parent_deleted = cursor.rowcount
        print(f"Deleted {parent_deleted} parent processes")
        
        connection.commit()
        print("Transaction committed successfully")
        return jsonify({'message': 'Parent process and all sub processes deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting parent process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/parent-processes', methods=['GET'])
def get_all_parent_processes():
    """Get all parent processes"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT id, parent_process_name, parent_process_type, parent_process_status, parent_process_category
            FROM supply_chain_parent_processes
            ORDER BY parent_process_name
        """)
        
        parent_processes = cursor.fetchall()
        
        return jsonify([{
            'id': process[0],
            'parent_process_name': process[1],
            'parent_process_type': process[2],
            'parent_process_status': process[3],
            'parent_process_category': process[4]
        } for process in parent_processes])
        
    except Exception as e:
        print(f"Error getting parent processes: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# Sub Process API Routes

@supply_chain_bp.route('/api/supply-chain/sub-processes', methods=['POST'])
def create_sub_process():
    """Create a new sub process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_sub_processes 
            (date, action, parent_process_id, sub_process_name, sub_process_description, sub_process_type, 
             sub_process_status, sub_process_category, sub_process_notes, execution_order, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            date.today(),
            'create',
            data.get('parent_process_id'),
            data.get('sub_process_name'),
            data.get('sub_process_description', ''),
            data.get('sub_process_type', 'manufacturing'),
            data.get('sub_process_status', 'active'),
            data.get('sub_process_category', ''),
            data.get('sub_process_notes', ''),
            data.get('execution_order', 1),
            data.get('uid', '')
        ))
        
        sub_process_id = cursor.fetchone()[0]
        connection.commit()
        
        return jsonify({'id': sub_process_id, 'message': 'Sub process created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating sub process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/sub-processes/<int:sub_process_id>', methods=['GET'])
def get_sub_process(sub_process_id):
    """Get a specific sub process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT s.id, s.parent_process_id, s.sub_process_name, s.sub_process_description, 
                   s.sub_process_type, s.sub_process_status, s.sub_process_category, 
                   s.sub_process_notes, s.execution_order, s.date,
                   p.parent_process_name
            FROM supply_chain_sub_processes s
            LEFT JOIN supply_chain_parent_processes p ON s.parent_process_id = p.id
            WHERE s.id = %s
        """, (sub_process_id,))
        
        sub_process = cursor.fetchone()
        if not sub_process:
            return jsonify({'error': 'Sub process not found'}), 404
            
        return jsonify({
            'id': sub_process[0],
            'parent_process_id': sub_process[1],
            'sub_process_name': sub_process[2],
            'sub_process_description': sub_process[3],
            'sub_process_type': sub_process[4],
            'sub_process_status': sub_process[5],
            'sub_process_category': sub_process[6],
            'sub_process_notes': sub_process[7],
            'execution_order': sub_process[8],
            'date': sub_process[9].isoformat() if sub_process[9] else None,
            'parent_process_name': sub_process[10]
        })
        
    except Exception as e:
        print(f"Error getting sub process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/sub-processes/<int:sub_process_id>', methods=['PUT'])
def update_sub_process(sub_process_id):
    """Update a sub process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            UPDATE supply_chain_sub_processes 
            SET sub_process_name = %s, sub_process_description = %s, sub_process_type = %s,
                sub_process_status = %s, sub_process_category = %s, sub_process_notes = %s,
                execution_order = %s, action = 'update', date = %s
            WHERE id = %s
        """, (
            data.get('sub_process_name'),
            data.get('sub_process_description'),
            data.get('sub_process_type'),
            data.get('sub_process_status'),
            data.get('sub_process_category'),
            data.get('sub_process_notes'),
            data.get('execution_order'),
            date.today(),
            sub_process_id
        ))
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Sub process not found'}), 404
            
        connection.commit()
        return jsonify({'message': 'Sub process updated successfully'})
        
    except Exception as e:
        print(f"Error updating sub process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/sub-processes/<int:sub_process_id>', methods=['DELETE'])
def delete_sub_process(sub_process_id):
    """Delete a sub process and all its inputs, outputs, and connections"""
    try:
        print(f"Delete sub process API called for sub_process_id: {sub_process_id}")
        connection, cursor = db_conn()
        
        # Check if sub process exists
        cursor.execute("SELECT id, sub_process_name FROM supply_chain_sub_processes WHERE id = %s", (sub_process_id,))
        sub_process = cursor.fetchone()
        if not sub_process:
            print(f"Sub process {sub_process_id} not found")
            return jsonify({'error': 'Sub process not found'}), 404
        
        print(f"Found sub process: {sub_process[1]} (ID: {sub_process[0]})")
        
        # Delete related records first
        print("Deleting related inputs...")
        cursor.execute("DELETE FROM supply_chain_inputs WHERE sub_process_id = %s", (sub_process_id,))
        inputs_deleted = cursor.rowcount
        print(f"Deleted {inputs_deleted} inputs")
        
        print("Deleting related outputs...")
        cursor.execute("DELETE FROM supply_chain_outputs WHERE sub_process_id = %s", (sub_process_id,))
        outputs_deleted = cursor.rowcount
        print(f"Deleted {outputs_deleted} outputs")
        
        print("Deleting related connections...")
        cursor.execute("DELETE FROM supply_chain_connections WHERE from_sub_process_id = %s OR to_sub_process_id = %s", (sub_process_id, sub_process_id))
        connections_deleted = cursor.rowcount
        print(f"Deleted {connections_deleted} connections")
        
        # Delete the sub process
        print("Deleting sub process...")
        cursor.execute("DELETE FROM supply_chain_sub_processes WHERE id = %s", (sub_process_id,))
        sub_process_deleted = cursor.rowcount
        print(f"Deleted {sub_process_deleted} sub processes")
        
        connection.commit()
        print("Transaction committed successfully")
        return jsonify({'message': 'Sub process deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting sub process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/supply-chain/sub-processes/<int:sub_process_id>/inputs', methods=['GET'])
def get_sub_process_inputs(sub_process_id):
    """Get all inputs for a specific sub-process"""
    try:
        connection, cursor = db_conn()
        cursor.execute("""
            SELECT id, process_id, input_name, input_type, input_quantity, 
                   input_unit, input_specifications, input_source, input_batch_number, 
                   input_expiry_date, input_status, uid
            FROM supply_chain_inputs
            WHERE process_id = %s
            ORDER BY input_name
        """, (sub_process_id,))
        inputs = cursor.fetchall()
        cursor.close()
        connection.close()
        
        result = []
        for input_item in inputs:
            result.append({
                'id': input_item[0],
                'process_id': input_item[1],
                'input_name': input_item[2],
                'input_type': input_item[3],
                'input_quantity': input_item[4],
                'input_unit': input_item[5],
                'input_specifications': input_item[6],
                'input_source': input_item[7],
                'input_batch_number': input_item[8],
                'input_expiry_date': input_item[9].isoformat() if input_item[9] else None,
                'input_status': input_item[10],
                'uid': input_item[11]
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error getting sub-process inputs: {e}")
        return jsonify({'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/sub-processes/<int:sub_process_id>/outputs', methods=['GET'])
def get_sub_process_outputs(sub_process_id):
    """Get all outputs for a specific sub-process"""
    try:
        connection, cursor = db_conn()
        cursor.execute("""
            SELECT id, process_id, output_name, output_type, output_quantity, 
                   output_unit, output_specifications, output_batch_number, 
                   output_quality_status, output_destination, uid
            FROM supply_chain_outputs
            WHERE process_id = %s
            ORDER BY output_name
        """, (sub_process_id,))
        outputs = cursor.fetchall()
        cursor.close()
        connection.close()
        
        result = []
        for output in outputs:
            result.append({
                'id': output[0],
                'process_id': output[1],
                'output_name': output[2],
                'output_type': output[3],
                'output_quantity': output[4],
                'output_unit': output[5],
                'output_specifications': output[6],
                'output_batch_number': output[7],
                'output_quality_status': output[8],
                'output_destination': output[9],
                'uid': output[10]
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error getting sub-process outputs: {e}")
        return jsonify({'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/sub-processes/<int:sub_process_id>/connections', methods=['GET'])
def get_sub_process_connections(sub_process_id):
    """Get all connections for a specific sub-process"""
    try:
        connection, cursor = db_conn()
        cursor.execute("""
            SELECT c.id, c.parent_process_id, c.from_sub_process_id, c.to_sub_process_id, 
                   c.connection_type, c.connection_status, c.connection_notes,
                   sp_from.sub_process_name as from_process_name,
                   sp_to.sub_process_name as to_process_name
            FROM supply_chain_connections c
            JOIN supply_chain_sub_processes sp_from ON c.from_sub_process_id = sp_from.id
            JOIN supply_chain_sub_processes sp_to ON c.to_sub_process_id = sp_to.id
            WHERE c.from_sub_process_id = %s OR c.to_sub_process_id = %s
            ORDER BY c.id
        """, (sub_process_id, sub_process_id))
        connections = cursor.fetchall()
        cursor.close()
        connection.close()
        
        result = []
        for conn in connections:
            result.append({
                'id': conn[0],
                'parent_process_id': conn[1],
                'from_sub_process_id': conn[2],
                'to_sub_process_id': conn[3],
                'connection_type': conn[4],
                'connection_status': conn[5],
                'connection_notes': conn[6],
                'from_process_name': conn[7],
                'to_process_name': conn[8]
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error getting sub-process connections: {e}")
        return jsonify({'error': str(e)}), 500

@supply_chain_bp.route('/api/supply-chain/parent-processes/<int:parent_process_id>/sub-processes', methods=['GET'])
def get_sub_processes_by_parent(parent_process_id):
    """Get all sub processes for a specific parent process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT s.id, s.parent_process_id, s.sub_process_name, s.sub_process_type, 
                   s.sub_process_status, s.sub_process_category, s.execution_order,
                   p.parent_process_name
            FROM supply_chain_sub_processes s
            LEFT JOIN supply_chain_parent_processes p ON s.parent_process_id = p.id
            WHERE s.parent_process_id = %s
            ORDER BY s.execution_order, s.sub_process_name
        """, (parent_process_id,))
        
        sub_processes = cursor.fetchall()
        
        # Convert to list of dictionaries for JSON response
        result = []
        for sub_process in sub_processes:
            result.append({
                'id': sub_process[0],
                'parent_process_id': sub_process[1],
                'sub_process_name': sub_process[2],
                'sub_process_type': sub_process[3],
                'sub_process_status': sub_process[4],
                'sub_process_category': sub_process[5],
                'execution_order': sub_process[6],
                'parent_process_name': sub_process[7]
            })
        
        return jsonify({'success': True, 'sub_processes': result})
        
    except Exception as e:
        print(f"Error getting sub processes: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

