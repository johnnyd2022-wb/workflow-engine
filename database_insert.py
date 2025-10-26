import datetime
import uuid
import psycopg2
from initialize import db_conn

def insert_data(table_name=None, audit_action=None, **kwargs):
    """
    Insert data into the specified table and an audit table.

    Parameters:
    - table_name: Name of the table to insert data into. Default is None.
    - audit_action: Action to be recorded in the audit table. Default is None.
    - kwargs: Dictionary containing column names and their corresponding values.

    Example usage:
    insert_data(table_name='actions', audit_action='Add flavor to inventory', flavor_stored=100, clearing_amount=50, clearing_abv=5, flavor_code='ABC', flavor_batch_code='123', ingredient_codes=[1, 2, 3])
    """
    # Check if table_name, audit_action, and kwargs contain data
    if not (table_name and audit_action and kwargs):
        print("No data provided for insertion.")
        return

    # Establish a database connection and get a cursor
    connection, cursor = db_conn()

    try:
        # Generate a unique identifier (UID)
        uid = str(uuid.uuid4())

        # Insert data into the audit table
        audit_query = "INSERT INTO audit (id, date, action, uid) VALUES (DEFAULT, %s, %s, %s);"
        audit_values = (datetime.date.today(), audit_action, uid)
        cursor.execute(audit_query, audit_values)

        # Append to the kwargs
        kwargs['uid'] = uid
        kwargs['date'] = datetime.date.today()
        kwargs['action'] = audit_action

        # Construct the INSERT query for the specified table
        columns = ', '.join(kwargs.keys())
        placeholders = ', '.join(['%s'] * len(kwargs))
        values = tuple(kwargs.values())

        # Construct the INSERT query dynamically
        insert_query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders});"

        # Execute the INSERT query for the specified table
        cursor.execute(insert_query, values)

        # Commit the transaction if both insertions are successful
        connection.commit()
        print(f"Data inserted successfully for action: {audit_action}!")
        
        # Attempt automatic sales-execution mapping for sales_product records
        if table_name == 'sales_product':
            try:
                # Get the inserted sales record ID
                cursor.execute("SELECT id FROM sales_product WHERE uid = %s ORDER BY id DESC LIMIT 1", (uid,))
                sales_record = cursor.fetchone()
                
                if sales_record:
                    sales_id = sales_record[0]
                    
                    # Import and attempt automatic mapping
                    try:
                        from features.supply_chain.backend.sales_execution_mapping import attempt_automatic_sales_mapping
                        mapping_result = attempt_automatic_sales_mapping(sales_id)
                        
                        if mapping_result['success'] and mapping_result['mappings_created'] > 0:
                            print(f"Auto-mapped {mapping_result['mappings_created']} products to executions for sales ID {sales_id}")
                        else:
                            print(f"No automatic mappings created for sales ID {sales_id}")
                    except ImportError:
                        print("Sales execution mapping module not available")
                    except Exception as mapping_error:
                        print(f"Error in automatic sales mapping: {mapping_error}")
                        
            except Exception as e:
                print(f"Error attempting automatic sales mapping: {e}")
                
    except Exception as e:
        # Rollback the transaction if there's an error to maintain data consistency
        print(f"Error inserting data for action - {audit_action}: {e}")
        connection.rollback()
    finally:
        # Close cursor and connection
        cursor.close()
        connection.close()

def update_data(table_name=None, condition=None, **kwargs):
    """
    Update data in specified tables in the database.

    Parameters:
    - table_name: Name of the table to update data in. Default is None.
    - condition: Dictionary containing column names and their corresponding values for the WHERE clause.
    - kwargs: Dictionary containing column names and their corresponding values to update.
    """

    # Check if table_name and kwargs contain data
    if not (table_name and kwargs):
        print("No data provided for update.")
        return

    # Establish a database connection and get a cursor
    connection, cursor = db_conn()

    try:
        # Update data

        # Construct the SET clause for the update query
        set_clause = ', '.join([f"{key} = %s" for key in kwargs.keys()])

        # Construct the WHERE clause for the update query
        where_clause = ' AND '.join([f"{key} = %s" for key in condition.keys()])
        condition_values = tuple(condition.values())

        # Construct the UPDATE query dynamically
        update_query = f"UPDATE {table_name} SET {set_clause} WHERE {where_clause}"

        # Combine values for SET and WHERE clauses
        values = tuple(kwargs.values()) + condition_values

        # Execute the UPDATE query
        cursor.execute(update_query, values)

        # Commit the transaction if the update is successful
        connection.commit()
        print(f"Data updated successfully in {table_name}!")
    except Exception as e:
        # Rollback the transaction if there's an error to maintain data consistency
        print(f"Error updating data in table - {table_name}: {e}")
        connection.rollback()
    finally:
        # Close cursor and connection
        cursor.close()
        connection.close()
