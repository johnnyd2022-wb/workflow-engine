import os
import datetime
import pandas as pd
import psycopg2
import re
from sqlalchemy import create_engine
from io import StringIO  # Add this import statement for StringIO
import docker
from config_loader import config

def load_docker_container(image_name, container_name, port, environment):
    try:
        docker_host = "unix:///var/run/docker.sock"
        client = docker.from_env()

        try:
            # Check if the image already exists locally; if not, pull it from Docker Hub
            client.images.get(image_name)
        except docker.errors.ImageNotFound:
            print(f"Pulling the {image_name} image from Docker Hub...")
            client.images.pull(image_name)

        # Check if a container with the same name exists and its status
        existing_containers = client.containers.list(all=True, filters={"name": container_name})
        if existing_containers:
            container = existing_containers[0]
            container_status = container.status
            if container_status == "running":
                print(f"The {container_name} container is already running!")
                return
            else:
                # The container exists but is not running, so start it
                print(f"Starting the {container_name} container...")
                container.start()
                print(f"The {container_name} container has been started!")
        else:
            # The container does not exist, so create and start it
            print(f"Creating and starting the {container_name} container...")
            container = client.containers.run(
                image=image_name,
                name=container_name,
                detach=True,
                command="postgres",
                ports=port,
                environment=environment,
            )
            print(f"The {container_name} container has been started!")

            # Additional operations on the container if needed
            # e.g., container.exec_run("command") or container.stop()

    except Exception as e:
        print(f"⚠️ Docker container management failed (this is expected in containerized environments): {e}")
        print("Continuing with database initialization...")

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

def create_purchases_empty_bottles_table():
    table_name = "purchases_empty_bottles"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "supplier": "TEXT",
        "bottle_size_ml": "DOUBLE PRECISION",
        "empty_bottles_stored": "DOUBLE PRECISION",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_purchases_gns_table():
    table_name = "purchases_gns"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "supplier": "TEXT",
        "gns_purchased_l": "DOUBLE PRECISION",
        "abv": "DOUBLE PRECISION",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_purchases_ingredients_table():
    table_name = "purchases_ingredients"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "supplier": "TEXT",
        "ingredients": "TEXT",
        "ingredients_amount": "INTEGER",
        "ingredients_code": "TEXT",
        "ingredients_expiry": "DATE",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_sales_product_table():
    table_name = "sales_product"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "buyer": "TEXT",
        "products": "JSONB",
        #"product_name": "TEXT",
        #"bottles_sold": "DOUBLE PRECISION",
        #"abv": "DOUBLE PRECISION",
        #"bottle_size_ml": "DOUBLE PRECISION",
        #"lal": "DOUBLE PRECISION",
        "duty_amount": "DOUBLE PRECISION",
        #"bottle_batch": "TEXT",
        "notes": "TEXT",
        #"unit_price": "DOUBLE PRECISION",
        #"amount_nzd": "DOUBLE PRECISION",
        #"total_nzd": "DOUBLE PRECISION",
        "invoice_total": "DOUBLE PRECISION",
        #"gst": "DOUBLE PRECISION",
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

def create_supply_chain_processes_table():
    table_name = "supply_chain_processes"

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

def create_supply_chain_inputs_table():
    table_name = "supply_chain_inputs"

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

def create_supply_chain_outputs_table():
    table_name = "supply_chain_outputs"

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

def create_supply_chain_connections_table():
    table_name = "supply_chain_connections"

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

def create_supply_chain_traceability_table():
    table_name = "supply_chain_traceability"

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

def create_supply_chain_process_executions_table():
    """Table to track actual executions of processes with batch data"""
    table_name = "supply_chain_process_executions"
    
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

def create_supply_chain_execution_inputs_table():
    """Table to track actual inputs used in process executions"""
    table_name = "supply_chain_execution_inputs"
    
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

def create_supply_chain_execution_outputs_table():
    """Table to track actual outputs produced in process executions"""
    table_name = "supply_chain_execution_outputs"
    
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

def create_supply_chain_execution_flow_through_table():
    """Table to track flow-through data from executions"""
    table_name = "supply_chain_execution_flow_through"
    
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

def create_supply_chain_process_templates_table():
    """Table to store process templates with default inputs/outputs"""
    table_name = "supply_chain_process_templates"
    
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

def create_supply_chain_dag_layout_table():
    """Table to store DAG layout data for visual editor"""
    table_name = "supply_chain_dag_layout"
    
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "layout_data": "JSONB", # JSON data containing node positions and layout info
        "layout_timestamp": "TIMESTAMP", # when this layout was saved
        "uid": "TEXT"
    }
    
    create_table(table_name, columns)

def create_supply_chain_parent_processes_table():
    """Table to store parent processes"""
    table_name = "supply_chain_parent_processes"
    
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

def create_supply_chain_sub_processes_table():
    """Table to store sub-processes"""
    table_name = "supply_chain_sub_processes"
    
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

def create_supply_chain_field_options_table():
    """Table to store field options for dynamic dropdowns"""
    table_name = "supply_chain_field_options"
    
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

def create_sales_product_samples_table():
    table_name = "sales_product_samples"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "buyer": "TEXT",
        "samples_provided": "DOUBLE PRECISION",
        "product": "TEXT",
        "abv": "DOUBLE PRECISION",
        "bottle_size_ml": "DOUBLE PRECISION",
        "lal": "DOUBLE PRECISION",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_samples_created_table():
    table_name = "product_actions_samples_created"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "number_of_bottles": "INTEGER",
        "abv": "DOUBLE PRECISION",
        "bottle_size_ml": "DOUBLE PRECISION",
        "flavor_code": "TEXT",
        "notes": "TEXT",
        "lal": "DOUBLE PRECISION",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_bottling_table():
    table_name = "product_actions_bottling"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "bottles_stored": "DOUBLE PRECISION",
        "abv": "DOUBLE PRECISION",
        "bottle_size_ml": "DOUBLE PRECISION",
        "vat_batch": "TEXT",
        "bottle_batch": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_flavor_experiments_table():
    table_name = "product_actions_flavor_experiments"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "flavor_stored_ml": "DOUBLE PRECISION",
        "clearing_amount": "DOUBLE PRECISION",
        "clearing_abv": "DOUBLE PRECISION",
        "flavor_code": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_samples_consumed_table():
    table_name = "product_actions_samples_consumed"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "flavor_code": "TEXT",
        "number_of_bottles": "INTEGER",
        "abv": "DOUBLE PRECISION",
        "bottle_size_ml": "DOUBLE PRECISION",
        "notes": "TEXT",
        "lal": "DOUBLE PRECISION",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_create_premix_table():
    table_name = "product_actions_create_premix"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "notes": "TEXT",
        "alcohol_volume": "DOUBLE PRECISION",
        "alcohol_abv": "DOUBLE PRECISION",
        "container_id": "TEXT",
        "lal": "DOUBLE PRECISION",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_distillation_experiments_table():
    table_name = "product_actions_distillation_experiments"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "experiment_id": "TEXT",
        "alcohol_used_l": "DOUBLE PRECISION",
        "bottles_used": "DOUBLE PRECISION",
        "bottle_abv": "DOUBLE PRECISION",
        "abv": "DOUBLE PRECISION",
        "alcohol_yield_l": "DOUBLE PRECISION",
        "alcohol_yield_abv": "DOUBLE PRECISION",
        "flavor_codes": "TEXT[]",
        "lal": "DOUBLE PRECISION",
        "notes": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_flavor_vat_table():
    table_name = "product_actions_flavor_vat"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "abv": "DOUBLE PRECISION",
        "vat_batch": "TEXT",
        "volume_amount": "integer",
        "flavor_batch": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_ex_stock_storage_table():
    table_name = "product_actions_ex_stock_storage"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "notes": "TEXT",
        "product_name": "TEXT",
        "storage_id": "TEXT",
        "bottle_size_ml": "DOUBLE PRECISION",
        "abv": "DOUBLE PRECISION",
        "bottles_stored": "DOUBLE PRECISION",
        "lal": "DOUBLE PRECISION",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_flavors_table():
    table_name = "product_actions_flavors"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "flavor_stored_ml": "DOUBLE PRECISION",
        "clearing_amount": "DOUBLE PRECISION",
        "clearing_abv": "DOUBLE PRECISION",
        "flavor_code": "TEXT",
        "flavor_batch": "TEXT",
        "ingredient_codes": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_product_actions_ethanol_table():
    table_name = "product_actions_ethanol"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "date": "DATE",
        "action": "TEXT",
        "alcohol_stored_l": "DOUBLE PRECISION",
        "abv": "DOUBLE PRECISION",
        "notes": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_monthly_totals_table():
    table_name = "monthly_totals"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "month": "TEXT UNIQUE",
        "bottles_sold": "FLOAT",
        "lal": "FLOAT",
        "duty_amount": "FLOAT",
        "gns_purchased_l": "INT",
        "bottles_stored": "FLOAT",
        "flavor_stored_ml": "FLOAT",
        "flavor_code": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_inventory_table():
    table_name = "inventory"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "bottles_stored": "FLOAT",
        "neutral_spirit_stored": "NUMERIC(10, 2)",
        "empty_bottles_stored": "FLOAT",
        "flavor_stored_ml": "FLOAT",
        "date": "DATE",
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

def create_buyers_table():
    table_name = "buyers"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "action": "TEXT",
        "date": "DATE",
        "buyer": "TEXT",
        "primary_contact": "TEXT",
        "buyer_address": "TEXT",
        "buyer_phone": "TEXT",
        "buyer_email": "TEXT",
        "restock_contact_date": "DATE",
        "store_type": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_emails_table():
    table_name = "emails"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "action": "TEXT",
        "date": "DATE",
        "sender_email": "TEXT",
        "buyer_email": "TEXT",
        "email_subject": "TEXT",
        "email_content": "TEXT",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_ingredients_table():
    table_name = "ingredients"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "supplier": "TEXT",
        "ingredients": "TEXT",
        "ingredients_amount": "INT",
        "ingredients_code": "TEXT",
        "ingredients_expiry": "DATE",
        "date": "DATE",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_customs_lodgements_table():
    table_name = "customs_lodgements"

    columns = {
        "id": "SERIAL PRIMARY KEY",
        "action": "TEXT",
        "date_period": "TEXT",
        "lodged_volume": "DOUBLE PRECISION",
        "lodged_abv": "DOUBLE PRECISION",
        "lal": "DOUBLE PRECISION",
        "bottles": "DOUBLE PRECISION",
        "date": "DATE",
        "uid": "TEXT"
    }

    create_table(table_name, columns)

def create_products_table():
    table_name = "products"
    columns = {
        "id": "SERIAL PRIMARY KEY",
        "action": "TEXT",
        "date": "DATE",
        "product_name": "TEXT",
        "product_size": "TEXT",
        "product_abv": "DOUBLE PRECISION",
        "uid": "TEXT"
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
    db_name = "whistlebird_inventory"
    db_user = "readonly_user"
    db_password = "wb_readonly"
    host = "localhost"
    port = 5401

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

def create_email(sender, recipients, subject, email_content, content_type, image_data=None, image_cid=None):
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage

    # Create a multipart message
    message = MIMEMultipart()

    # Set sender, recipients, and subject
    message['From'] = sender
    message['To'] = ", ".join(recipients)
    message['Subject'] = subject

    # Check content type
    if content_type == 'plain':
        # Create plain text part
        text_part = MIMEText(email_content, 'plain')
        message.attach(text_part)
    elif content_type == 'html':
        # Create HTML part
        html_part = MIMEText(email_content, 'html')
        message.attach(html_part)
        
        # Check if image data is provided for embedding
        if image_data and image_cid:
            # Create an image part and attach the image
            image_part = MIMEImage(image_data)
            image_part.add_header('Content-ID', f'<{image_cid}>')
            message.attach(image_part)

            # Define the relationship between the HTML and image parts
            html_part.add_header('Content-ID', f'<{image_cid}>')

    return message

def send_emails_concurrently(email_data):
    import threading

    threads = []
    for email in email_data:
        thread = threading.Thread(target=send_email, args=(email,))
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()

def send_email(email):
    print("Accessed send_email() function")
    import smtplib

    app_password = 'bglgsnrkbxdynrsm'

    # Connect to the SMTP server and send the email
    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()  # Use TLS
        server.login('johnny@whistlebird.co.nz', app_password)
        server.send_message(email)

def email_settings():
    #sender_email = "inventory@whistlebird-app.iam.gserviceaccount.com"
    sender_email = 'johnny@whistlebird.co.nz'
    receiver_emails = ['johnny@whistlebird.co.nz', 'niko@whistlebird.co.nz']
    email_subject = "Weekly Check - expiring ingredients for next 3 weeks"
    return sender_email, receiver_emails, email_subject

def email_content(html_table, sender_email, receiver_emails, email_subject):
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    message = MIMEMultipart()
    message.attach(MIMEText(html_table, 'html'))
    message['From'] = sender_email
    message['To'] = receiver_emails
    message['Subject'] = email_subject
    return message

def main():
    df = {}
    connection, cursor = db_conn()
    
    # Create the 'actions' table in the database
    create_audit_table()
    create_purchases_empty_bottles_table()
    create_purchases_gns_table()
    create_purchases_ingredients_table()
    create_sales_product_table()
    create_product_actions_bottling_table()
    create_product_actions_flavor_experiments_table()
    create_product_actions_create_premix_table()
    create_product_actions_distillation_experiments_table()
    create_product_actions_flavor_vat_table()
    create_product_actions_flavors_table()
    create_product_actions_ethanol_table()
    create_monthly_totals_table()
    create_inventory_table()
    create_suppliers_table()
    create_db_function()
    create_buyers_table()
    create_emails_table()
    create_customs_lodgements_table()
    create_product_actions_ex_stock_storage_table()
    create_sales_product_samples_table()
    create_product_actions_samples_consumed_table()
    create_product_actions_samples_created_table()
    create_products_table()
    create_crm_customer_table()
    create_crm_follow_ups_table()
    create_crm_log_table()
    create_crm_tasks_table()
    create_supply_chain_processes_table()
    create_supply_chain_inputs_table()
    create_supply_chain_outputs_table()
    create_supply_chain_connections_table()
    create_supply_chain_traceability_table()
    create_supply_chain_process_executions_table()
    create_supply_chain_execution_inputs_table()
    create_supply_chain_execution_outputs_table()
    create_supply_chain_execution_flow_through_table()
    create_supply_chain_process_templates_table()
    create_supply_chain_dag_layout_table()
    create_supply_chain_parent_processes_table()
    create_supply_chain_sub_processes_table()
    create_supply_chain_field_options_table()
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
