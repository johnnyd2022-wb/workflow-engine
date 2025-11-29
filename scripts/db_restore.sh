#!/bin/bash

current_date=$(date +"%m-%d-%Y")

psql_run_test() {
        docker run --name workflow-engine-test-db -d -p 8401:5432 \
                -e POSTGRES_DB=workflow-engine \
                -e POSTGRES_USER=wb_admin \
                -e POSTGRES_PASSWORD=secret \
                -d postgres

        echo "Waiting for PostgreSQL to start..."
        sleep 5

        docker exec -i workflow-engine-test-db psql -U wb_admin -d workflow-engine -c \
                "CREATE ROLE readonly_user LOGIN PASSWORD 'wb_readonly'; \
                GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user; \
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM readonly_user; \
                ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_user;"

        echo "PostgreSQL and readonly_user created successfully!"
}

# Database restore script - restores prod DB to test environment
echo "🔄 Restoring production database to test environment..."

# Stop and remove existing test DB container
docker stop workflow-engine-test-db && docker rm workflow-engine-test-db
docker stop workflow-engine-test-db && docker rm workflow-engine-test-db

# Take prod backup
docker exec -t workflow-engine-prod-db pg_dump -U wb_admin -d workflow-engine > /home/johnny/workflow-engine_db_backups/workflow-engine-prod-db-${current_date}.sql
sleep 5

# Create restore container
docker run --name workflow-engine-test-db -p 8401:5432 -e POSTGRES_USER=wb_admin -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=workflow-engine-test-db -d postgres

# Run test container
psql_run_test
sleep 5

docker cp /home/johnny/workflow-engine_db_backups/workflow-engine-prod-db-${current_date}.sql workflow-engine-test-db:/
docker cp /home/johnny/workflow-engine_db_backups/workflow-engine-prod-db-${current_date}.sql workflow-engine-test-db:/
docker exec -t workflow-engine-test-db psql -U wb_admin -d workflow-engine-test-db -f workflow-engine-prod-db-${current_date}.sql
docker exec -t workflow-engine-test-db psql -U wb_admin -d workflow-engine -f workflow-engine-prod-db-${current_date}.sql
sleep 5

# Run sanitization to replace customer emails
echo "🧹 Sanitizing customer data..."
python3 /home/johnny/workflow-engine/sanitize_db.py

echo "✅ Database restore completed!"
echo "Test environment is ready with sanitized production data"