# Create uid to be used to correlate audit logs with other tables
def unique_id():
    from initialize import db_conn
    connection, cursor = db_conn()

    # Fetch the next value from the sequence
    cursor.execute("SELECT nextval('audit_id_seq'::regclass);")
    sequid = cursor.fetchone()[0]  # Fetch the first row and first column

    # Close the cursor and connection
    cursor.close()
    connection.close()

    print(sequid)
    return sequid
