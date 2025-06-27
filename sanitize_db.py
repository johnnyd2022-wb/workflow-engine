def sanitize_db():
    print("Accessed sanitize_db() function")
    import importlib.util
    import sys
    
    module_path = "/home/johnny/wb_local/initialize.py"

    spec = importlib.util.spec_from_file_location("remote_initialize", module_path)
    remote_initialize = importlib.util.module_from_spec(spec)
    sys.modules["remote_initialize"] = remote_initialize
    spec.loader.exec_module(remote_initialize)

    db_conn = remote_initialize.db_conn
    connection, cursor = db_conn()

    # Fetch buyer (store name) + email address to be sanitized
    cursor.execute("""
    SELECT buyer, buyer_email
    FROM buyers
    """)
    buyers = cursor.fetchall()

    try:
        for buyer, buyer_email in buyers:
            new_email = f"johnny+{buyer}@whistlebird.co.nz"
            sanitized_email = new_email.replace(' ', '')  # Remove any white space
            cursor.execute("UPDATE buyers SET buyer_email = %s WHERE buyer = %s", (sanitized_email, buyer))
            print(f"Successfully sanitized email address for {buyer}, set new email to {sanitized_email}")

        # Commit all updates at once
        connection.commit()
    except Exception as e:
        # Rollback the transaction if there's an error to maintain data consistency
        print(f"Error occurred, rolled back all changes: {e}")
        connection.rollback()
    finally:
        # Close the cursor and connection
        cursor.close()
        connection.close()

if __name__ == "__main__":
    sanitize_db()

