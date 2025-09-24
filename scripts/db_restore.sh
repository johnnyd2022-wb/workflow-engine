#!/bin/bash

current_date=$(date +"%m-%d-%Y")

psql_run_test() {
        docker run --name whistlebird_db_test -d -p 5401:5432 \
                -e POSTGRES_DB=whistlebird_inventory \
                -e POSTGRES_USER=wb_admin \
                -e POSTGRES_PASSWORD=whistlebird \
                -d postgres

        echo "Waiting for PostgreSQL to start..."
        sleep 5

        docker exec -i whistlebird_db_test psql -U wb_admin -d whistlebird_inventory -c \
                "CREATE ROLE readonly_user LOGIN PASSWORD 'wb_readonly'; \
                GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user; \
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM readonly_user; \
                ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_user;"

        echo "PostgreSQL and readonly_user created successfully!"
}

# Database restore script - restores prod DB to test environment
echo "🔄 Restoring production database to test environment..."

# Stop and remove existing test DB container
docker stop whistlebird_restore && docker rm whistlebird_restore
docker stop whistlebird_db_test && docker rm whistlebird_db_test

# Take prod backup
docker exec -t whistlebird_db_prod pg_dump -U wb_admin -d whistlebird_inventory > /home/johnny/wb_db_backups/whistlebird_db_prod-${current_date}.sql
sleep 5

# Create restore container
docker run --name whistlebird_restore -p 5410:5432 -e POSTGRES_USER=wb_admin -e POSTGRES_PASSWORD=whistlebird -e POSTGRES_DB=whistlebird_restore -d postgres

# Run test container
psql_run_test
sleep 5

docker cp /home/johnny/wb_db_backups/whistlebird_db_prod-${current_date}.sql whistlebird_restore:/
docker cp /home/johnny/wb_db_backups/whistlebird_db_prod-${current_date}.sql whistlebird_db_test:/
docker exec -t whistlebird_restore psql -U wb_admin -d whistlebird_restore -f whistlebird_db_prod-${current_date}.sql
docker exec -t whistlebird_db_test psql -U wb_admin -d whistlebird_inventory -f whistlebird_db_prod-${current_date}.sql
sleep 5

# Run sanitization to replace customer emails
echo "🧹 Sanitizing customer data..."
python3 /home/johnny/wb_local/sanitize_db.py

echo "✅ Database restore completed!"
echo "Test environment is ready with sanitized production data"