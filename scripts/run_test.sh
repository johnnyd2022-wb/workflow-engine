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

# Browser telemetry uses the public PostHog project token stored in KeePassXC.
# Resolve it on the host; the container cannot access the host KeePassXC database.
if [ -z "${POSTHOG_PROJECT_API_KEY:-}" ]; then
    POSTHOG_PROJECT_API_KEY="$(uv run python -c 'from app.utils.config_loader import config; print(config.rum_posthog_api_key)')"
fi
if [ -z "$POSTHOG_PROJECT_API_KEY" ]; then
    echo "❌ PostHog project API key is unavailable. Configure workflow-engine/observability/posthog_project_api_key in KeePassXC."
    exit 1
fi

# Run Docker container
docker run -d \
    --name workflow-engine-test \
    -p 8001:8001 \
    --network workflow-observability \
    -e ENVIRONMENT=test \
    -e POSTHOG_PROJECT_API_KEY="$POSTHOG_PROJECT_API_KEY" \
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD_TEST \
    -e XERO_CLIENT_ID_TEST="$XERO_CLIENT_ID_TEST" \
    -e XERO_CLIENT_SECRET_TEST="$XERO_CLIENT_SECRET_TEST" \
    -e xero_client_id_test="$xero_client_id_test" \
    -e xero_client_secret_test="$xero_client_secret_test" \
    workflow-engine:test

echo "✅ Test environment started on port 8001"
echo "View logs with: docker logs -f workflow-engine-test"
echo "Browse to: https://test-workflow-engine.whistlebird.co.nz"
