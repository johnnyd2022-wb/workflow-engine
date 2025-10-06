from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from initialize import db_conn
from database_insert import insert_data
from config_loader import config
import json
import datetime
from datetime import date

# Create Supply Chain blueprint
supply_chain_bp = Blueprint('supply_chain', __name__, template_folder='../frontend')

@supply_chain_bp.route('/supply-chain', methods=['GET', 'POST'])
def supply_chain():
    print("Accessed /supply-chain route")
    connection, cursor = db_conn()

    try:
        # Get all processes
        cursor.execute("""
            SELECT id, process_name, process_description, process_type, 
                   process_status, process_category, process_notes, date
            FROM supply_chain_processes
            ORDER BY process_name
        """)
        processes = cursor.fetchall()

        # Get process statistics
        cursor.execute("SELECT COUNT(*) FROM supply_chain_processes")
        total_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_processes WHERE process_status = 'active'")
        active_processes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_inputs")
        total_inputs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_outputs")
        total_outputs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supply_chain_connections")
        total_connections = cursor.fetchone()[0]

        return render_template('supply_chain.html',
                               processes=processes,
                               total_processes=total_processes,
                               active_processes=active_processes,
                               total_inputs=total_inputs,
                               total_outputs=total_outputs,
                               total_connections=total_connections)

    except Exception as e:
        print(f"Error in supply_chain route: {e}")
        return render_template('supply_chain.html', 
                               processes=[],
                               total_processes=0,
                               active_processes=0,
                               total_inputs=0,
                               total_outputs=0,
                               total_connections=0,
                               error=str(e))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

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

@supply_chain_bp.route('/api/processes', methods=['POST'])
def create_process():
    """Create a new process"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_processes 
            (date, action, process_name, process_description, process_type, 
             process_status, process_category, process_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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

@supply_chain_bp.route('/api/processes/<int:process_id>', methods=['GET'])
def get_process(process_id):
    """Get a specific process"""
    try:
        connection, cursor = db_conn()
        
        cursor.execute("""
            SELECT id, process_name, process_description, process_type, 
                   process_status, process_category, process_notes, date
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
            'date': process[7].isoformat() if process[7] else None
        })
        
    except Exception as e:
        print(f"Error getting process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/processes/<int:process_id>', methods=['PUT'])
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

@supply_chain_bp.route('/api/processes/<int:process_id>', methods=['DELETE'])
def delete_process(process_id):
    """Delete a process"""
    try:
        connection, cursor = db_conn()
        
        # Check if process exists
        cursor.execute("SELECT id FROM supply_chain_processes WHERE id = %s", (process_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Process not found'}), 404
        
        # Delete related records first
        cursor.execute("DELETE FROM supply_chain_inputs WHERE process_id = %s", (process_id,))
        cursor.execute("DELETE FROM supply_chain_outputs WHERE process_id = %s", (process_id,))
        cursor.execute("DELETE FROM supply_chain_connections WHERE from_process_id = %s OR to_process_id = %s", (process_id, process_id))
        
        # Delete the process
        cursor.execute("DELETE FROM supply_chain_processes WHERE id = %s", (process_id,))
        
        connection.commit()
        return jsonify({'message': 'Process deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting process: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/inputs', methods=['POST'])
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

@supply_chain_bp.route('/api/outputs', methods=['POST'])
def create_output():
    """Create a new output"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_outputs 
            (date, action, process_id, output_name, output_type, output_quantity, 
             output_unit, output_specifications, output_batch_number, 
             output_quality_status, output_destination, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            data.get('uid', '')
        ))
        
        output_id = cursor.fetchone()[0]
        connection.commit()
        
        return jsonify({'id': output_id, 'message': 'Output created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating output: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/connections', methods=['POST'])
def create_connection():
    """Create a new connection between processes"""
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        cursor.execute("""
            INSERT INTO supply_chain_connections 
            (date, action, from_process_id, to_process_id, from_output_id, 
             to_input_id, connection_type, connection_status, connection_notes, uid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            date.today(),
            'create',
            data.get('from_process_id'),
            data.get('to_process_id'),
            data.get('from_output_id'),
            data.get('to_input_id'),
            data.get('connection_type', 'direct'),
            data.get('connection_status', 'active'),
            data.get('connection_notes', ''),
            data.get('uid', '')
        ))
        
        connection_id = cursor.fetchone()[0]
        connection.commit()
        
        return jsonify({'id': connection_id, 'message': 'Connection created successfully'}), 201
        
    except Exception as e:
        print(f"Error creating connection: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@supply_chain_bp.route('/api/traceability', methods=['POST'])
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

@supply_chain_bp.route('/api/traceability/<trace_id>', methods=['GET'])
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
