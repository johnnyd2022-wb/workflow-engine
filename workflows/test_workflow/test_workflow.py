from flask import Blueprint, render_template, request, jsonify
from initialize import db_conn
import json

test_workflow = Blueprint('test_workflow', __name__)

@test_workflow.route('/test_workflow')
def test_workflow_form():
    return render_template('test_workflow/test_workflow.html',
                         workflow_type='retrieval',
                         storage_type='',
                         columns=[] if '' == 'new_table' else None,
                         existing_columns=[] if '' == 'existing_table' else None)

@test_workflow.route('/process-test_workflow', methods=['POST'])
def process_test_workflow():
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        if 'retrieval' == 'storage':
            # Handle data storage
            if '' == 'new_table':
                # Insert into new table
                columns = []
                values = [data.get(col['name']) for col in columns]
                placeholders = ', '.join(['%s'] * len(values))
                column_names = ', '.join([col['name'] for col in columns])
                
                query = f"INSERT INTO {data.get('table_name')} ({column_names}) VALUES ({placeholders})"
                cursor.execute(query, values)
            else:
                # Insert into existing table
                table_name = data.get('table_name')
                values = data.get('values', {})
                columns = ', '.join(values.keys())
                placeholders = ', '.join(['%s'] * len(values))
                
                query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
                cursor.execute(query, list(values.values()))
        else:
            # Handle data retrieval
            sql_query = data.get('sql_query')
            cursor.execute(sql_query)
            results = cursor.fetchall()
            return jsonify({'success': True, 'data': results})
            
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})