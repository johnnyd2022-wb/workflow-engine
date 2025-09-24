#!/bin/bash

# Test environment runner
export WB_ENVIRONMENT=test
echo "🧪 Starting WhistleBird app in TEST environment..."
echo "Environment: $WB_ENVIRONMENT"
echo "Config file: config/$WB_ENVIRONMENT.ini"

# Build and run Docker container for test
docker stop $(docker ps -aqf "name=wb_inv_test") 2>/dev/null || true
docker rm $(docker ps -aqf "name=wb_inv_test") 2>/dev/null || true

# Build Docker image for test environment
docker build --target test -f Dockerfile.multi -t wb_inv:test .

# Run Docker container
docker run -d \
    --name wb_inv_test \
    -p 5001:5001 \
    -e WB_ENVIRONMENT=test \
    wb_inv:test

echo "✅ Test environment started on port 5001"
echo "View logs with: docker logs -f wb_inv_test"
echo "Browse to: https://test-inventory.whistlebird.co.nz"