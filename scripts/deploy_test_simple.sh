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

# Build and run Docker container for test.
# The filter must match the app container's name exactly -- "name=workflow-engine-test"
# is a substring filter and also matches "workflow-engine-test-db", which stops and
# removes the database container along with the app container (data survives on its
# named volume, but the container has to be manually recreated afterwards).
if [ -n "$IMAGE_REF" ]; then
    echo "Pulling $IMAGE_REF from registry..."
    docker pull "$IMAGE_REF"
    RUN_IMAGE="$IMAGE_REF"
else
    echo "No image ref given -- building locally (local dev path)."
    docker build --target test -f Dockerfile.multi -t workflow-engine:test .
    RUN_IMAGE="workflow-engine:test"
fi

# Only now replace the running app: a failed pull or build above (for example a rollback to a
# :test-stable tag that has not been promoted yet) must leave the existing container serving.
docker stop $(docker ps -aqf "name=^workflow-engine-test$") 2>/dev/null || true
docker rm $(docker ps -aqf "name=^workflow-engine-test$") 2>/dev/null || true

# Browser telemetry uses the public PostHog project token stored in KeePassXC.
# Optional, not required: an empty key just means client-side RUM doesn't
# initialize (config_loader.rum_posthog_api_key falls back to "", app_factory
# passes it straight into the page template either way) -- no crash, no missing
# functionality that matters for a deploy. CD does not resolve or require this
# at all; only try KeePassXC when running locally with no image ref, and only
# best-effort (never fail the deploy over it).
POSTHOG_PROJECT_API_KEY="${POSTHOG_PROJECT_API_KEY:-}"
if [ -z "$POSTHOG_PROJECT_API_KEY" ] && [ -z "$IMAGE_REF" ]; then
    POSTHOG_PROJECT_API_KEY="$(uv run python -c 'from app.utils.config_loader import config; print(config.rum_posthog_api_key)' 2>/dev/null || true)"
fi

# Run Docker container
DOCKER_RUN_ARGS=(
    -d
    --name workflow-engine-test
    -p 8001:8001
    --network workflow-observability
    -e ENVIRONMENT=test
    -e XERO_CLIENT_ID_TEST="${XERO_CLIENT_ID_TEST:-}"
    -e XERO_CLIENT_SECRET_TEST="${XERO_CLIENT_SECRET_TEST:-}"
    -e xero_client_id_test="${xero_client_id_test:-}"
    -e xero_client_secret_test="${xero_client_secret_test:-}"
)
if [ -n "$POSTHOG_PROJECT_API_KEY" ]; then
    DOCKER_RUN_ARGS+=(-e POSTHOG_PROJECT_API_KEY="$POSTHOG_PROJECT_API_KEY")
fi
# The test database password comes from the job or host environment and is never committed here. Without
# it the app cannot connect to its database and never starts serving.
DB_PASSWORD="${POSTGRES_PASSWORD:-${POSTGRES_PASSWORD_TEST:-}}"
if [ -n "$DB_PASSWORD" ]; then
    DOCKER_RUN_ARGS+=(-e POSTGRES_PASSWORD="$DB_PASSWORD")
else
    echo "⚠️  No POSTGRES_PASSWORD or POSTGRES_PASSWORD_TEST in this environment: the app will not reach its database."
fi

docker run "${DOCKER_RUN_ARGS[@]}" "$RUN_IMAGE"

echo "✅ Test environment started on port 8001"
echo "View logs with: docker logs -f workflow-engine-test"
echo "Browse to: https://test-workflow-engine.whistlebird.co.nz"
