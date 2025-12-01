#!/bin/bash

current_date=$(date +"%m-%d-%Y")

psql_run_test() {
        docker run --name workflow-engine-test-db -d -p 8401:5432 \
                -e POSTGRES_DB=workflow-engine \
                -e POSTGRES_USER=workflow_rw \
                -e POSTGRES_PASSWORD=secret \
                -d postgres

        echo "Waiting for PostgreSQL to start..."
        sleep 5

        docker exec -i workflow-engine-test-db psql -U workflow_rw -d workflow-engine -c \
                "CREATE ROLE workflow_rw LOGIN PASSWORD 'workflow_rw'; \
                GRANT SELECT ON ALL TABLES IN SCHEMA public TO workflow_rw; \
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM workflow_rw; \
                ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO workflow_rw;"

        echo "PostgreSQL and workflow_rw created successfully!"
}

# Database restore script - restores prod DB to test environment
echo "🔄 Restoring production database to test environment..."

# Stop and remove existing test DB container
docker stop workflow-engine-test-db && docker rm workflow-engine-test-db
docker stop workflow-engine-test-db && docker rm workflow-engine-test-db

# Take prod backup
docker exec -t workflow-engine-prod-db pg_dump -U workflow_rw -d workflow-engine > /home/johnny/workflow-engine_db_backups/workflow-engine-prod-db-${current_date}.sql
sleep 5

# Create restore container
docker run --name workflow-engine-test-db -p 8401:5432 -e POSTGRES_USER=workflow_rw -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=workflow-engine-test-db -d postgres

# Run test container
psql_run_test
sleep 5

docker cp /home/johnny/workflow-engine_db_backups/workflow-engine-prod-db-${current_date}.sql workflow-engine-test-db:/
docker cp /home/johnny/workflow-engine_db_backups/workflow-engine-prod-db-${current_date}.sql workflow-engine-test-db:/
docker exec -t workflow-engine-test-db psql -U workflow_rw -d workflow-engine-test-db -f workflow-engine-prod-db-${current_date}.sql
docker exec -t workflow-engine-test-db psql -U workflow_rw -d workflow-engine -f workflow-engine-prod-db-${current_date}.sql
sleep 5

# Run sanitization to replace customer emails

echo "✅ Database restore completed!"
echo "Test environment is ready"