#!/bin/bash
# Setup database for CI tests
# This script waits for PostgreSQL, updates config, and runs migrations

set -e

echo "🔧 Setting up database..."

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
until PGPASSWORD=$POSTGRES_PASSWORD psql -h postgres -p 5432 -U $POSTGRES_USER -d $POSTGRES_DB -c '\q' 2>/dev/null; do
  echo "PostgreSQL is unavailable - sleeping"
  sleep 2
done
echo "✅ PostgreSQL is ready!"

# Update test.ini to use service container hostname and correct port
# Service containers are accessible via their alias as hostname
# Tests expect port 8005, so update test.ini to match
echo "Updating test.ini configuration..."
sed -i 's|host = host.docker.internal|host = postgres|' app/config/test.ini
sed -i 's|port = 8401|port = 5432|' app/config/test.ini
sed -i 's|port = 8001|port = 8005|' app/config/test.ini

# Run Alembic migrations to set up schema
echo "Running database migrations..."
# Upgrade to head (merge_draft_tracking_001) so both is_draft and execution_step_tracking are applied
echo "Upgrading to head (merge_draft_tracking_001)..."
ENVIRONMENT=test uv run alembic upgrade head

echo "✅ Database setup complete!"

