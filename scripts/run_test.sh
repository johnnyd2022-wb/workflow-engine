#!/bin/bash

# Test environment runner
export ENVIRONMENT=test
echo "🧪 Starting Workflow Engine app in TEST environment..."
echo "Environment: $ENVIRONMENT"
echo "Config file: config/$ENVIRONMENT.ini"

# Build and run Docker container for test
docker stop workflow-engine-test 2>/dev/null || true
docker rm workflow-engine-test 2>/dev/null || true

# Build Docker image for test environment
docker build --target test -f Dockerfile.multi -t workflow-engine:test .

# Run Docker container
docker run -d \
    --name workflow-engine-test \
    -p 8001:8001 \
    -e ENVIRONMENT=test \
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD_TEST \
    -e XERO_CLIENT_ID_TEST="$XERO_CLIENT_ID_TEST" \
    -e XERO_CLIENT_SECRET_TEST="$XERO_CLIENT_SECRET_TEST" \
    -e xero_client_id_test="$xero_client_id_test" \
    -e xero_client_secret_test="$xero_client_secret_test" \
    workflow-engine:test

echo "✅ Test environment started on port 8001"
echo "View logs with: docker logs -f workflow-engine-test"
echo "Browse to: https://test-workflow-engine.whistlebird.co.nz"
