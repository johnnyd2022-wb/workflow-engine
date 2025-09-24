#!/bin/bash

# Production environment runner
export WB_ENVIRONMENT=production
echo "🏭 Starting WhistleBird app in PRODUCTION environment..."
echo "Environment: $WB_ENVIRONMENT"
echo "Config file: config/$WB_ENVIRONMENT.ini"

# Backup current production
/home/johnny/app_backups.sh
/home/johnny/db_backups.sh

# Build and run Docker container for production
docker stop $(docker ps -aqf "name=wb_inv_prod") 2>/dev/null || true
docker rm $(docker ps -aqf "name=wb_inv_prod") 2>/dev/null || true

# Build Docker image for production environment
docker build --target production -f Dockerfile.multi -t wb_inv:prod .

# Run Docker container
docker run -d \
    --name wb_inv_prod \
    -p 5000:5000 \
    -e WB_ENVIRONMENT=production \
    wb_inv:prod

echo "✅ Production environment started on port 5000"
echo "View logs with: docker logs -f wb_inv_prod"
