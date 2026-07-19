#!/bin/bash

# Test deployment script.
#
# Local dev (unchanged): ./scripts/deploy_test_simple.sh
#   Builds the `test` target from Dockerfile.multi locally, same as before.
#
# CD (new): ./scripts/deploy_test_simple.sh <image-ref>
#   Pulls the given image (e.g. $CI_REGISTRY_IMAGE/app:test-<sha> or :test-stable)
#   from the registry instead of building -- this is what makes CD deploy exactly
#   the artifact CI already tested, not a fresh rebuild of whatever's on disk.
set -euo pipefail

export ENVIRONMENT=test
echo "🧪 Starting Workflow Engine app in TEST environment..."
echo "Environment: $ENVIRONMENT"
echo "Config file: config/$ENVIRONMENT.ini"

IMAGE_REF="${1:-}"

# Build and run Docker container for test
docker stop $(docker ps -aqf "name=workflow-engine-test") 2>/dev/null || true
docker rm $(docker ps -aqf "name=workflow-engine-test") 2>/dev/null || true

if [ -n "$IMAGE_REF" ]; then
    echo "Pulling $IMAGE_REF from registry..."
    docker pull "$IMAGE_REF"
    RUN_IMAGE="$IMAGE_REF"
else
    echo "No image ref given -- building locally (local dev path)."
    docker build --target test -f Dockerfile.multi -t workflow-engine:test .
    RUN_IMAGE="workflow-engine:test"
fi

# Browser telemetry uses the public PostHog project token stored in KeePassXC.
# Resolve it on the host; the container cannot access the host KeePassXC database.
# In CD, POSTHOG_PROJECT_API_KEY is instead expected to already be set as a masked
# GitLab CI/CD variable -- the check below is a no-op in that case since the
# variable is already non-empty.
if [ -z "${POSTHOG_PROJECT_API_KEY:-}" ]; then
    POSTHOG_PROJECT_API_KEY="$(uv run python -c 'from app.utils.config_loader import config; print(config.rum_posthog_api_key)')"
fi
if [ -z "$POSTHOG_PROJECT_API_KEY" ]; then
    echo "❌ PostHog project API key is unavailable. Configure workflow-engine/observability/posthog_project_api_key in KeePassXC (local) or the POSTHOG_PROJECT_API_KEY CI/CD variable (CD)."
    exit 1
fi

# Run Docker container
docker run -d \
    --name workflow-engine-test \
    -p 8001:8001 \
    --network workflow-observability \
    -e ENVIRONMENT=test \
    -e POSTHOG_PROJECT_API_KEY="$POSTHOG_PROJECT_API_KEY" \
    -e XERO_CLIENT_ID_TEST="$XERO_CLIENT_ID_TEST" \
    -e XERO_CLIENT_SECRET_TEST="$XERO_CLIENT_SECRET_TEST" \
    -e xero_client_id_test="$xero_client_id_test" \
    -e xero_client_secret_test="$xero_client_secret_test" \
    "$RUN_IMAGE"

echo "✅ Test environment started on port 8001"
echo "View logs with: docker logs -f workflow-engine-test"
echo "Browse to: https://test-workflow-engine.whistlebird.co.nz"
