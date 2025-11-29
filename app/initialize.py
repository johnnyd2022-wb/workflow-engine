import os
import datetime
import psycopg2
import re
from sqlalchemy import create_engine
from io import StringIO  # Add this import statement for StringIO
import docker
from app.utils.config_loader import config

def calculate_numeric_precision_scale(series):
    max_digits = series.apply(lambda x: len(str(x).replace('.', '')) if not pd.isna(x) else 0).max()
    max_decimal_places = series.apply(lambda x: len(str(x).split('.')[1]) if not pd.isna(x) and '.' in str(x) else 0).max()
    return max_digits + max_decimal_places, max_decimal_places

def create_table(table_name, columns):
    # Check if the table exists
    connection, cursor = db_conn()

    try:
        with connection.cursor() as outer_cursor:
            # Use parameterized query to prevent SQL injection
            outer_cursor.execute("SELECT * FROM information_schema.tables WHERE table_name=%s", (table_name,))
            table_exists = bool(outer_cursor.rowcount)

            # If the table exists, get the column names and data types from the existing table
            if table_exists:
                with connection.cursor() as inner_cursor:
                    inner_cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name=%s", (table_name,))
                    existing_columns = {row[0]: row[1] for row in inner_cursor.fetchall()}
            else:
                existing_columns = {}

            # Merge existing columns with new columns
            all_columns = {**existing_columns, **columns}

            # If the table exists, add missing columns
            if table_exists:
                missing_columns = {column: data_type for column, data_type in columns.items() if column not in existing_columns}

                if missing_columns:
                    print(f"Adding missing columns to table '{table_name}': {list(missing_columns.keys())}")
                    
                    # Add columns one by one to get better error reporting
                    for column, data_type in missing_columns.items():
                        try:
                            alter_table_query = f"ALTER TABLE {table_name} ADD COLUMN {column} {data_type}"
                            print(f"Executing: {alter_table_query}")
                            outer_cursor.execute(alter_table_query)
                            print(f"✅ Successfully added column '{column}' to table '{table_name}'")
                        except Exception as e:
                            print(f"❌ Error adding column '{column}' to table '{table_name}': {e}")
                            connection.rollback()
                            raise e
                    
                    connection.commit()
                    print(f"✅ All missing columns added to table '{table_name}'.")
                else:
                    print(f"Table '{table_name}' already exists with all specified columns.")
            else:
                # Create the table with the provided columns and data types
                create_table_query = f"CREATE TABLE IF NOT EXISTS {table_name} ("
                for column, data_type in all_columns.items():
                    create_table_query += f'"{column}" {data_type}, '
                create_table_query = create_table_query[:-2]  # Remove the last comma and space
                create_table_query += ");"

                print(f"Creating table '{table_name}' with query: {create_table_query}")
                outer_cursor.execute(create_table_query)
                connection.commit()
                print(f"✅ Table '{table_name}' created successfully.")
                
    except Exception as e:
        print(f"❌ Error in create_table for '{table_name}': {e}")
        if connection:
            connection.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def create_audit_table():
    table_name = "audit"

    columns = {
    "id": "SERIAL PRIMARY KEY",
    "date": "DATE",
    "action": "TEXT",
    "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_sales_table():
    table_name = "sales"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "buyer": "TEXT",
        "products": "JSONB",
        "duty_amount": "DOUBLE PRECISION",
        "notes": "TEXT",
        "invoice_total": "DOUBLE PRECISION",
        "invoice_gst": "DOUBLE PRECISION",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_crm_customer_table():
    table_name = "crm_customers"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "customer": "TEXT", # customer name
        "primary_contact": "TEXT", # primary contact for the customer
        "customer_address": "TEXT", # customer address
        "customer_phone": "TEXT", # customer phone number
        "customer_email": "TEXT", # customer email address
        "customer_notes": "TEXT", # notes about the customer
        "customer_status": "TEXT", # 'active', 'inactive', 'new'
        "customer_last_contact": "DATE", # last date the customer was contacted
        "invoices": "JSONB",  # Stores invoice data as nested JSON with invoice number as key
        "aliases": "TEXT[]", # list of aliases for the customer
        "contacts": "JSONB", # list of contacts & contact details for the customer
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_crm_follow_ups_table():
    table_name = "crm_follow_ups"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "customer": "TEXT", # customer name
        "follow_up_date": "DATE", # date of the follow-up
        "follow_up_type": "TEXT", # 'email', 'phone', 'in-person', 'other'
        "follow_up_notes": "TEXT", # notes about the follow-up
        "follow_up_priority": "TEXT", # 'low', 'medium', 'high'
        "follow_up_status": "TEXT", # 'completed', 'pending', 'cancelled'
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_crm_log_table():
    table_name = "crm_logs"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "customer": "TEXT", # customer name
        "log_date": "DATE", # date of the log
        "log_type": "TEXT", # 'email', 'phone', 'in-person', 'other'
        "log_notes": "TEXT", # notes about the log,
        "log_status": "TEXT", # 'completed', 'pending', 'cancelled', 'sale', 'in-progress', 'other'
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_crm_tasks_table():
    table_name = "crm_tasks"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "customer": "TEXT", # customer name
        "task_date": "DATE", # date of the task
        "task_type": "TEXT", # 'email', 'phone', 'in-person', 'other'
        "task_notes": "TEXT", # notes about the task
        "task_status": "TEXT", # 'completed', 'pending', 'cancelled', 'sale', 'in-progress', 'other', 'follow-up'
        "task_priority": "TEXT", # 'low', 'medium', 'high'
        "task_assigned_to": "TEXT", # name of the person assigned to the task
        "task_notification_type": "TEXT", # 'email', 'popup', 'other'
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_workflow_processes_table():
    table_name = "workflow_processes"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "process_name": "TEXT", # name of the process (e.g., "Gin Distillation", "Botanical Mixing")
        "process_description": "TEXT", # detailed description of the process
        "process_type": "TEXT", # type of process (e.g., "manufacturing", "packaging", "quality_control")
        "process_status": "TEXT", # 'active', 'inactive', 'archived'
        "process_category": "TEXT", # category for grouping processes
        "process_notes": "TEXT", # additional notes about the process
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_workflow_inputs_table():
    table_name = "workflow_inputs"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "process_id": "INTEGER", # foreign key to supply_chain_processes
        "input_name": "TEXT", # name of the input (e.g., "Juniper Berries", "Neutral Spirit")
        "input_type": "TEXT", # type of input (e.g., "raw_material", "intermediate_product", "equipment")
        "input_quantity": "DOUBLE PRECISION", # quantity of input
        "input_unit": "TEXT", # unit of measurement (e.g., "kg", "liters", "pieces")
        "input_specifications": "JSONB", # additional specifications as JSON
        "input_source": "TEXT", # where the input comes from
        "input_batch_number": "TEXT", # batch or lot number for traceability
        "input_expiry_date": "DATE", # expiry date if applicable
        "input_status": "TEXT", # 'available', 'consumed', 'expired', 'quarantined'
        "execution_options": "JSONB", # JSON object with execution options for each field (e.g., {"name": "template", "quantity": "prompt", "unit": "template"})
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_workflow_outputs_table():
    table_name = "workflow_outputs"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "process_id": "INTEGER", # foreign key to supply_chain_processes
        "output_name": "TEXT", # name of the output (e.g., "Gin Batch A", "Bottled Product")
        "output_type": "TEXT", # type of output (e.g., "finished_product", "intermediate_product", "waste")
        "output_quantity": "DOUBLE PRECISION", # quantity of output
        "output_unit": "TEXT", # unit of measurement
        "output_specifications": "JSONB", # additional specifications as JSON
        "output_batch_number": "TEXT", # batch or lot number for traceability
        "output_quality_status": "TEXT", # 'passed', 'failed', 'pending', 'quarantined'
        "output_destination": "TEXT", # where the output goes next
        "output_flow_through": "BOOLEAN DEFAULT FALSE", # whether this output flows through to connected processes
        "output_flow_through_fields": "JSONB", # which specific fields flow through as JSON
        "execution_options": "JSONB", # JSON object with execution options for each field (e.g., {"type": "template", "volume": "prompt", "measure": "template"})
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_workflow_connections_table():
    table_name = "workflow_connections"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "parent_process_id": "INTEGER", # parent process this connection belongs to
        "from_sub_process_id": "INTEGER", # source sub-process
        "to_sub_process_id": "INTEGER", # destination sub-process
        "from_output_id": "INTEGER", # specific output from source sub-process
        "to_input_id": "INTEGER", # specific input to destination sub-process
        "connection_type": "TEXT", # type of connection (e.g., "direct", "storage", "transport")
        "connection_status": "TEXT", # 'active', 'inactive', 'blocked'
        "connection_notes": "TEXT", # additional notes about the connection
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_workflow_traceability_table():
    table_name = "workflow_traceability"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "trace_id": "TEXT", # unique trace identifier
        "item_name": "TEXT", # name of the item being traced
        "item_type": "TEXT", # type of item (e.g., "batch", "product", "ingredient")
        "current_location": "TEXT", # current location in the supply chain
        "current_process_id": "INTEGER", # current process
        "trace_path": "JSONB", # complete path through the supply chain
        "trace_status": "TEXT", # 'active', 'completed', 'lost'
        "trace_notes": "TEXT", # additional trace information
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_workflow_process_executions_table():
    """Table to track actual executions of processes with batch data"""
    table_name = "workflow_process_executions"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "process_id": "INTEGER", # foreign key to supply_chain_processes
        "execution_batch_number": "TEXT", # unique batch number for this execution
        "execution_status": "TEXT", # 'planned', 'in_progress', 'completed', 'failed', 'cancelled'
        "execution_start_time": "TIMESTAMP", # when execution started
        "execution_end_time": "TIMESTAMP", # when execution completed
        "execution_notes": "TEXT", # notes about this specific execution
        "execution_variables": "JSONB", # custom variables (VAT number, operator, etc.)
        "execution_quality_checks": "JSONB", # quality check results
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_execution_inputs_table():
    """Table to track actual inputs used in process executions"""
    table_name = "workflow_execution_inputs"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "execution_id": "INTEGER", # foreign key to supply_chain_process_executions
        "input_template_id": "INTEGER", # foreign key to supply_chain_inputs (template)
        "actual_input_name": "TEXT", # actual name used (may differ from template)
        "actual_input_quantity": "DOUBLE PRECISION", # actual quantity used
        "actual_input_unit": "TEXT", # actual unit used
        "actual_input_batch_number": "TEXT", # actual batch number of input
        "actual_input_source": "TEXT", # actual source of input
        "input_consumption_time": "TIMESTAMP", # when input was consumed
        "input_quality_status": "TEXT", # quality status of this input
        "input_notes": "TEXT", # notes about this specific input usage
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_execution_outputs_table():
    """Table to track actual outputs produced in process executions"""
    table_name = "workflow_execution_outputs"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "execution_id": "INTEGER", # foreign key to supply_chain_process_executions
        "output_template_id": "INTEGER", # foreign key to supply_chain_outputs (template)
        "actual_output_name": "TEXT", # actual name produced
        "actual_output_quantity": "DOUBLE PRECISION", # actual quantity produced
        "actual_output_unit": "TEXT", # actual unit
        "actual_output_batch_number": "TEXT", # actual batch number produced
        "actual_output_quality_status": "TEXT", # actual quality status
        "actual_output_destination": "TEXT", # where this output actually went
        "output_production_time": "TIMESTAMP", # when output was produced
        "output_notes": "TEXT", # notes about this specific output
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_execution_flow_through_table():
    """Table to track flow-through data from executions"""
    table_name = "workflow_execution_flow_through"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "source_execution_id": "INTEGER", # foreign key to supply_chain_sub_executions
        "source_output_id": "INTEGER", # foreign key to supply_chain_outputs
        "target_process_id": "INTEGER", # foreign key to supply_chain_sub_processes (where it flows to)
        "flow_through_data": "JSONB", # actual prompted values and flow-through configuration
        "flow_through_status": "TEXT", # 'pending', 'processed', 'failed'
        "flow_through_notes": "TEXT", # notes about this flow-through
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_process_templates_table():
    """Table to store process templates with default inputs/outputs"""
    table_name = "workflow_process_templates"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "process_id": "INTEGER", # foreign key to supply_chain_processes
        "template_name": "TEXT", # name of this template version
        "template_version": "TEXT", # version number
        "template_status": "TEXT", # 'draft', 'active', 'archived'
        "default_inputs": "JSONB", # default input specifications
        "default_outputs": "JSONB", # default output specifications
        "default_variables": "JSONB", # default variable definitions
        "template_notes": "TEXT", # notes about this template
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_dag_layout_table():
    """Table to store DAG layout data for visual editor"""
    table_name = "workflow_dag_layout"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "layout_data": "JSONB", # JSON data containing node positions and layout info
        "layout_timestamp": "TIMESTAMP", # when this layout was saved
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_parent_processes_table():
    """Table to store parent processes"""
    table_name = "workflow_parent_processes"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "parent_process_name": "TEXT",
        "parent_process_description": "TEXT",
        "parent_process_type": "TEXT",
        "parent_process_status": "TEXT",
        "parent_process_category": "TEXT",
        "parent_process_notes": "TEXT",
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_sub_processes_table():
    """Table to store sub-processes"""
    table_name = "workflow_sub_processes"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "parent_process_id": "INTEGER",
        "sub_process_name": "TEXT",
        "sub_process_description": "TEXT",
        "sub_process_type": "TEXT",
        "sub_process_status": "TEXT",
        "sub_process_category": "TEXT",
        "sub_process_notes": "TEXT",
        "execution_order": "INTEGER",
        "is_managed": "BOOLEAN",
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_field_options_table():
    """Table to store field options for dynamic dropdowns"""
    table_name = "workflow_field_options"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "field_type": "TEXT NOT NULL",
        "option_value": "TEXT NOT NULL",
        "option_label": "TEXT",
        "is_system_default": "BOOLEAN DEFAULT FALSE",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    }
    
    create_table(table_name, columns)

def create_workflow_parent_executions_table():
    """Table to store parent process executions"""
    table_name = "workflow_parent_executions"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "parent_process_id": "INTEGER",
        "execution_batch_id": "TEXT", # Human-friendly batch identifier (e.g., "Gin Batch #2024-001")
        "execution_status": "TEXT", # 'pending', 'in_progress', 'completed', 'failed', 'cancelled'
        "execution_start_time": "TIMESTAMP",
        "execution_end_time": "TIMESTAMP",
        "execution_notes": "TEXT",
        "parent_execution_ids": "JSONB", # Array of parent execution IDs for lineage tracking
        "sales_mapping_status": "TEXT DEFAULT 'unmapped'", # 'unmapped', 'partial', 'complete'
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_sub_executions_table():
    """Table to store sub-process executions"""
    table_name = "workflow_sub_executions"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "parent_execution_id": "INTEGER", # Foreign key to supply_chain_parent_executions
        "sub_process_id": "INTEGER", # Foreign key to supply_chain_sub_processes
        "execution_status": "TEXT", # 'pending', 'in_progress', 'completed', 'failed', 'cancelled'
        "execution_start_time": "TIMESTAMP",
        "execution_end_time": "TIMESTAMP",
        "execution_notes": "TEXT",
        "execution_data": "JSONB", # Store actual input/output data from execution
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_execution_sales_mapping_table():
    """Table to map executions to sales for full traceability"""
    table_name = "workflow_execution_sales_mapping"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "execution_id": "INTEGER NOT NULL", # Links to supply_chain_parent_executions.id
        "sales_id": "INTEGER NOT NULL", # Links to sales_product.id
        "product_name": "TEXT NOT NULL", # Specific product sold
        "quantity_sold": "DOUBLE PRECISION",
        "batch_reference": "TEXT", # Human-readable batch identifier
        "mapping_type": "TEXT DEFAULT 'auto'", # 'auto', 'manual', 'fifo'
        "mapping_confidence": "DOUBLE PRECISION DEFAULT 1.0", # Confidence score for automatic mappings
        "mapping_notes": "TEXT", # Notes about the mapping
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_workflow_execution_lineage_table():
    """Table to store execution lineage relationships for efficient tracing"""
    table_name = "workflow_execution_lineage"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "parent_execution_id": "INTEGER NOT NULL", # Parent execution
        "child_execution_id": "INTEGER NOT NULL", # Child execution
        "relationship_type": "TEXT DEFAULT 'direct'", # 'direct', 'inherited', 'split', 'merged'
        "flow_through_data": "JSONB", # Data that flowed from parent to child
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_suppliers_table():
    table_name = "suppliers"
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "action": "TEXT",
        "uid": "TEXT",
        "supplier": "TEXT",
        "supplier_contact": "TEXT",
        "supplier_location": "TEXT",
        "supplier_number": "TEXT",
        "supplier_type": "TEXT",
        "date": "DATE"
    }

    create_table(table_name, columns)

def db_conn():
    db_name = config.db_name
    db_user = config.db_user
    db_password = config.db_password
    host = config.db_host
    port = config.db_port

    # Create a connection to the PostgreSQL database
    connection = psycopg2.connect(
        host=host,
        database=db_name,
        user=db_user,
        password=db_password,
        port=port
    )
    
    cursor = connection.cursor()  # Create a new cursor

    return connection, cursor

def db_conn_readonly():
    db_name = config.db_name
    db_user = config.db_readonly_user
    db_password = config.db_readonly_password
    host = config.db_host
    port = config.db_port

    # Create a connection to the PostgreSQL database
    connection = psycopg2.connect(
        host=host,
        database=db_name,
        user=db_user,
        password=db_password,
        port=port
    )
    
    cursor = connection.cursor()  # Create a new cursor

    return connection, cursor

def create_db_function():
    connection, cursor = db_conn()

    # Check if the function already exists
    cursor.execute("""
    SELECT 1
    FROM pg_proc
    WHERE proname = 'query_all_tables_by_uid'
    """)
    exists = cursor.fetchone()

    if not exists:
        # Execute the SQL command to create the PostgreSQL function
        cursor.execute("""
        CREATE OR REPLACE FUNCTION query_all_tables_by_uid(uid_value TEXT)
        RETURNS TABLE (Entry JSONB) AS $$
        DECLARE
            sql_query TEXT;
            queries TEXT[] := '{}';  -- Initialize the array
            rec_tbl RECORD;
            q TEXT;  -- Variable to hold individual queries
            columns_list TEXT; -- Variable to hold the column list for each table
        BEGIN
            -- Loop through tables to construct queries
            FOR rec_tbl IN
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
                AND table_name NOT IN ('actions', 'audit') -- Exclude the "actions" and "audit" tables
            LOOP
                -- Check if the table has a 'uid' column
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = rec_tbl.table_name
                    AND column_name = 'uid'
                ) THEN
                    -- Get the list of columns for the current table
                    columns_list := (
                        SELECT string_agg(column_name, ', ')
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        AND table_name = rec_tbl.table_name
                    );

                    -- Construct SQL query to select all columns where uid matches
                    q := format('SELECT to_jsonb(t) AS Entry FROM %I t WHERE uid = $1', rec_tbl.table_name);

                    -- Add the query to the array
                    queries := array_append(queries, q);
                END IF;
            END LOOP;

            -- Join the queries into a single SQL query
            sql_query := 'SELECT jsonb_agg(Entry) AS Entry FROM (' || array_to_string(queries, ' UNION ALL ') || ') t';

            -- Execute the query and return results
            RETURN QUERY EXECUTE sql_query USING uid_value;
        END;
        $$ LANGUAGE plpgsql;
        """)

    # Commit the changes and close the connection
    connection.commit()
    cursor.close()
    connection.close()

def main():
    df = {}
    connection, cursor = db_conn()
    
    # Create the 'actions' table in the database
    create_audit_table()
    create_sales_table()
    create_suppliers_table()
    create_db_function()
    create_crm_customer_table()
    create_crm_follow_ups_table()
    create_crm_log_table()
    create_crm_tasks_table()
    create_workflow_processes_table()
    create_workflow_inputs_table()
    create_workflow_outputs_table()
    create_workflow_connections_table()
    create_workflow_traceability_table()
    create_workflow_process_executions_table()
    create_workflow_execution_inputs_table()
    create_workflow_execution_outputs_table()
    create_workflow_execution_flow_through_table()
    create_workflow_process_templates_table()
    create_workflow_dag_layout_table()
    create_workflow_parent_processes_table()
    create_workflow_sub_processes_table()
    create_workflow_field_options_table()
    create_workflow_parent_executions_table()
    create_workflow_sub_executions_table()
    create_workflow_execution_sales_mapping_table()
    create_workflow_execution_lineage_table()
    # Export the current date's data to the Excel file
    
    current_date = datetime.date.today()
    current_date_str = current_date.strftime("%d-%m-%Y")

    # Close the connection
    connection.close()

if __name__ == "__main__":
    # Use environment-specific Docker configuration
    if config.docker_enabled:
        print(f"Loading Docker container for {config.environment} environment...")
        
        # Get Docker configuration from environment config
        image_name = config.docker_image_name
        container_name = config.docker_container_name
        
        # Port mapping from config
        ports = {
            config.docker_host_port: config.docker_container_port
        }
        
        # Database environment variables
        environment = {
            "POSTGRES_DB": config.db_name,
            "POSTGRES_USER": config.db_user,
            "POSTGRES_PASSWORD": config.db_password
        }
        
        load_docker_container(image_name, container_name, ports, environment)
    else:
        print(f"Docker container disabled for {config.environment} environment")
    
    # Run database initialization for all environments
    print(f"Running database initialization for environment: {config.environment}")
    main()
