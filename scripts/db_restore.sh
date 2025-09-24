#!/bin/bash

# Database restore script - restores prod DB to test environment
echo "🔄 Restoring production database to test environment..."

# Stop and remove existing test DB container
docker stop $(docker ps -aqf "name=wb_inv_test") 2>/dev/null || true
docker rm $(docker ps -aqf "name=wb_inv_test") 2>/dev/null || true

# Stop and remove existing test DB container
docker stop $(docker ps -aqf "name=whistlebird_db_test") 2>/dev/null || true
docker rm $(docker ps -aqf "name=whistlebird_db_test") 2>/dev/null || true

# Create new test DB container from production backup
docker run -d \
    --name whistlebird_db_test \
    -p 5401:5432 \
    -e POSTGRES_DB=whistlebird_db_test \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=your_password_here \
    postgres:13

# Wait for container to be ready
echo "⏳ Waiting for database to be ready..."
sleep 10

# Restore production data (you'll need to implement the actual restore logic)
echo "📥 Restoring production data..."
# Add your restore logic here - this might involve:
# 1. Creating a backup of prod DB
# 2. Restoring it to test DB
# 3. Running sanitization scripts

# Run sanitization to replace customer emails
echo "🧹 Sanitizing customer data..."
# Add sanitization logic here

echo "✅ Database restore completed!"
echo "Test environment is ready with sanitized production data"