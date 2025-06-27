from flask import Blueprint, render_template, request, jsonify
from initialize import db_conn
import json
import os

workflow_creator = Blueprint('workflow_creator', __name__)

@workflow_creator.route('/workflow-creator')
def workflow_creator_form():
    # Get list of existing tables
    connection, cursor = db_conn()
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name != 'audit'
        ORDER BY table_name
    """)
    existing_tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    connection.close()
    
    return render_template('workflow_creator/workflow_creator.html', 
                         existing_tables=existing_tables,
                         workflow_type='storage',  # Default to storage type
                         storage_type='new_table')  # Default to new table

@workflow_creator.route('/create-workflow', methods=['POST'])
def create_workflow():
    try:
        data = request.get_json()
        workflow_name = data.get('name')
        workflow_description = data.get('description')
        workflow_type = data.get('type')  # 'storage' or 'retrieval'
        storage_type = data.get('storage_type')  # 'new_table' or 'existing_table'
        
        # Create workflow directory
        workflow_dir = f"workflows/{workflow_name.lower().replace(' ', '_')}"
        os.makedirs(workflow_dir, exist_ok=True)
        
        # Create blueprint file
        blueprint_content = f'''from flask import Blueprint, render_template, request, jsonify
from initialize import db_conn
import json

{workflow_name.lower().replace(' ', '_')} = Blueprint('{workflow_name.lower().replace(' ', '_')}', __name__)

@{workflow_name.lower().replace(' ', '_')}.route('/{workflow_name.lower().replace(' ', '_')}')
def {workflow_name.lower().replace(' ', '_')}_form():
    return render_template('{workflow_name.lower().replace(' ', '_')}/{workflow_name.lower().replace(' ', '_')}.html',
                         workflow_type='{workflow_type}',
                         storage_type='{storage_type}',
                         columns=[] if '{storage_type}' == 'new_table' else None,
                         existing_columns=[] if '{storage_type}' == 'existing_table' else None)

@{workflow_name.lower().replace(' ', '_')}.route('/process-{workflow_name.lower().replace(' ', '_')}', methods=['POST'])
def process_{workflow_name.lower().replace(' ', '_')}():
    try:
        data = request.get_json()
        connection, cursor = db_conn()
        
        if '{workflow_type}' == 'storage':
            # Handle data storage
            if '{storage_type}' == 'new_table':
                # Insert into new table
                columns = {json.dumps(data.get('columns', []))}
                values = [data.get(col['name']) for col in columns]
                placeholders = ', '.join(['%s'] * len(values))
                column_names = ', '.join([col['name'] for col in columns])
                
                query = f"INSERT INTO {{data.get('table_name')}} ({{column_names}}) VALUES ({{placeholders}})"
                cursor.execute(query, values)
            else:
                # Insert into existing table
                table_name = data.get('table_name')
                values = data.get('values', {{}})
                columns = ', '.join(values.keys())
                placeholders = ', '.join(['%s'] * len(values))
                
                query = f"INSERT INTO {{table_name}} ({{columns}}) VALUES ({{placeholders}})"
                cursor.execute(query, list(values.values()))
        else:
            # Handle data retrieval
            sql_query = data.get('sql_query')
            cursor.execute(sql_query)
            results = cursor.fetchall()
            return jsonify({{'success': True, 'data': results}})
            
        connection.commit()
        cursor.close()
        connection.close()
        
        return jsonify({{'success': True}})
    except Exception as e:
        return jsonify({{'success': False, 'error': str(e)}})'''
        
        with open(f"{workflow_dir}/{workflow_name.lower().replace(' ', '_')}.py", 'w') as f:
            f.write(blueprint_content)
            
        # Create table creation file if needed
        if workflow_type == 'storage' and storage_type == 'new_table':
            table_content = f'''from initialize import db_conn

def create_{workflow_name.lower().replace(' ', '_')}_tables():
    connection, cursor = db_conn()
    try:
        columns = {json.dumps(data.get('columns', []))}
        column_defs = ', '.join([f"{{col['name']}} {{col['type']}}" for col in columns])
        query = f"""
            CREATE TABLE IF NOT EXISTS {{data.get('table_name')}} (
                id SERIAL PRIMARY KEY,
                {{column_defs}},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        cursor.execute(query)
        connection.commit()
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()'''
            
            with open(f"{workflow_dir}/create_tables.py", 'w') as f:
                f.write(table_content)
                
        # Create template file
        template_content = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{workflow_name}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/styles.css') }}">
</head>
<body>
    <div class="container">
        <h1>{workflow_name}</h1>
        <p>{workflow_description}</p>
        
        <form id="workflowForm">
            {% if workflow_type == 'storage' %}
                {% if storage_type == 'new_table' %}
                    {% for column in columns %}
                    <div class="form-group">
                        <label for="{{ column.name }}">{{ column.label }}</label>
                        <input type="{{ column.input_type }}" id="{{ column.name }}" name="{{ column.name }}" required>
                    </div>
                    {% endfor %}
                {% else %}
                    {% for column in existing_columns %}
                    <div class="form-group">
                        <label for="{{ column.name }}">{{ column.label }}</label>
                        <input type="{{ column.input_type }}" id="{{ column.name }}" name="{{ column.name }}" required>
                    </div>
                    {% endfor %}
                {% endif %}
            {% else %}
                <div class="form-group">
                    <label for="sqlQuery">SQL Query</label>
                    <textarea id="sqlQuery" name="sqlQuery" rows="4" required></textarea>
                </div>
            {% endif %}
            
            <button type="submit">Submit</button>
        </form>
        
        <div id="results"></div>
    </div>
    
    <script>
        document.getElementById('workflowForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());
            
            try {
                const response = await fetch('/process-{workflow_name_lower}', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                if (result.success) {
                    document.getElementById('results').innerHTML = '<p>Success!</p>';
                    if (result.data) {
                        // Display data in a table
                        const table = document.createElement('table');
                        // ... table creation logic ...
                        document.getElementById('results').appendChild(table);
                    }
                } else {
                    document.getElementById('results').innerHTML = `<p>Error: ${result.error}</p>`;
                }
            } catch (error) {
                document.getElementById('results').innerHTML = `<p>Error: ${error.message}</p>`;
            }
        });
    </script>
</body>
</html>'''
        
        os.makedirs(f"templates/{workflow_name.lower().replace(' ', '_')}", exist_ok=True)
        with open(f"templates/{workflow_name.lower().replace(' ', '_')}/{workflow_name.lower().replace(' ', '_')}.html", 'w') as f:
            f.write(template_content.format(
                workflow_name=workflow_name,
                workflow_description=workflow_description,
                workflow_name_lower=workflow_name.lower().replace(' ', '_')
            ))
            
        # Update app.py to import the new blueprint
        with open('app.py', 'r') as f:
            app_content = f.read()
            
        # Add import statement
        import_statement = f"from workflows.{workflow_name.lower().replace(' ', '_')}.{workflow_name.lower().replace(' ', '_')} import {workflow_name.lower().replace(' ', '_')}\n"
        app_content = app_content.replace("from flask import Flask", f"from flask import Flask\n{import_statement}")
        
        # Add blueprint registration
        blueprint_registration = f"app.register_blueprint({workflow_name.lower().replace(' ', '_')})\n"
        app_content = app_content.replace("app = Flask(__name__)", f"app = Flask(__name__)\n{blueprint_registration}")
        
        with open('app.py', 'w') as f:
            f.write(app_content)
            
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@workflow_creator.route('/get-table-columns/<table_name>')
def get_table_columns(table_name):
    try:
        connection, cursor = db_conn()
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = %s
        """, (table_name,))
        columns = [{'name': row[0], 'type': row[1]} for row in cursor.fetchall()]
        cursor.close()
        connection.close()
        return jsonify({'success': True, 'columns': columns})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}) 