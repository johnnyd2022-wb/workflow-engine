#!/bin/bash

# Production environment runner
export ENVIRONMENT=prod
echo "🏭 Starting Workflow Engine app in PRODUCTION environment..."
echo "Environment: $ENVIRONMENT"
echo "Config file: config/$ENVIRONMENT.ini"

# Backup current production
/home/johnny/workflow-engine_backups.sh
/home/johnny/workflow-engine_db_backups.sh

# Build and run Docker container for production
docker stop $(docker ps -aqf "name=workflow-engine-prod") 2>/dev/null || true
docker rm $(docker ps -aqf "name=workflow-engine-prod") 2>/dev/null || true

# Build Docker image for production environment
docker build --target production -f Dockerfile.multi -t workflow-engine:prod .

# Run Docker container
docker run -d \
    --name workflow-engine-prod \
    -p 8000:8000 \
    -e ENVIRONMENT=prod \
    workflow-engine:prod

echo "✅ Production environment started on port 8000"
echo "View logs with: docker logs -f workflow-engine-prod"
echo "Browse to: https://workflow-engine.whistlebird.co.nz"