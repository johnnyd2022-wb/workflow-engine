from initialize import db_conn

def create_workflow_tables():
    """Create the necessary tables for workflow definitions"""
    connection, cursor = db_conn()
    
    try:
        # Create workflow_definitions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_definitions (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                storage_type VARCHAR(50) NOT NULL,
                table_name VARCHAR(255) NOT NULL,
                table_columns JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create workflow_instances table to track workflow runs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_instances (
                id SERIAL PRIMARY KEY,
                workflow_id INTEGER REFERENCES workflow_definitions(id),
                status VARCHAR(50) NOT NULL,
                input_data JSONB,
                output_data JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );
        """)
        
        connection.commit()
        print("✓ Workflow tables created successfully")
        
    except Exception as e:
        print(f"❌ Error creating workflow tables: {str(e)}")
        connection.rollback()
        raise
        
    finally:
        cursor.close()
        connection.close()

if __name__ == "__main__":
    create_workflow_tables() 