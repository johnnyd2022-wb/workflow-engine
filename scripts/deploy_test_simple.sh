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

# Session signing must use a private, stable key; validate before replacing the app.
FLASK_SECRET_KEY="${FLASK_SECRET_KEY:-}"
if [ -z "${FLASK_SECRET_KEY:-}" ] && [ -z "$IMAGE_REF" ]; then
    FLASK_SECRET_KEY="$(uv run python -c 'from scripts.local_secrets import get_keepass_entry; print(get_keepass_entry(entry_name="workflow-engine/FLASK_SECRET_KEY_TEST").get("Password", "").strip())')"
fi
if [ "${#FLASK_SECRET_KEY}" -lt 32 ] || [ "$FLASK_SECRET_KEY" = "dev-secret-key-change-in-production" ]; then
    echo "A strong FLASK_SECRET_KEY is required before deploying test."
    exit 1
fi
export FLASK_SECRET_KEY

# Resolve test Google credentials on the host; KeePassXC is unavailable in Docker.
# CD supplies protected environment variables instead of reading the host database.
if [ -z "$IMAGE_REF" ]; then
    if [ -z "${GOOGLE_CLIENT_ID:-}" ]; then
        GOOGLE_CLIENT_ID="$(uv run python -c 'from scripts.local_secrets import get_keepass_entry; print(get_keepass_entry(entry_name="workflow-engine/GOOGLE_CLIENT_ID").get("Password", "").strip())')"
    fi
    if [ -z "${GOOGLE_CLIENT_SECRET:-}" ]; then
        GOOGLE_CLIENT_SECRET="$(uv run python -c 'from scripts.local_secrets import get_keepass_entry; print(get_keepass_entry(entry_name="workflow-engine/GOOGLE_CLIENT_SECRET").get("Password", "").strip())')"
    fi
fi
if [ -z "${GOOGLE_CLIENT_ID:-}" ] || [ -z "${GOOGLE_CLIENT_SECRET:-}" ]; then
    echo "Google sign-in requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET before deploying test."
    exit 1
fi
export GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET

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

# The test database password comes from the job or host environment and is never committed here. Without
# it the app cannot connect to its database and never starts serving.
DB_PASSWORD="${POSTGRES_PASSWORD:-${POSTGRES_PASSWORD_TEST:-}}"
if [ -z "$DB_PASSWORD" ]; then
    echo "⚠️  No POSTGRES_PASSWORD or POSTGRES_PASSWORD_TEST in this environment: the app will not reach its database."
fi

# Migrate the test database with the new image before replacing the app, as production does
# (scripts/run_prod.sh). Nothing else migrates it: without this a merged migration's tables are
# missing and the deployed app answers 500 (main, 2026-10-27, tastings). A failure here leaves the
# running app untouched.
if [ -n "$DB_PASSWORD" ]; then
    echo "Migrating the test database..."
    if ! docker run --rm --network workflow-observability -e ENVIRONMENT=test -e FLASK_SECRET_KEY \
        -e POSTGRES_PASSWORD="$DB_PASSWORD" "$RUN_IMAGE" uv run alembic upgrade head; then
        echo "❌ Migrating the test database failed; the running app was left as it was."
        echo "   The database is shared with local development. If it is on a migration only a branch has"
        echo "   (applied while working on that branch), step it back from that branch's checkout with"
        echo "   'uv run alembic downgrade <main's head>' and deploy again."
        exit 1
    fi
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
    -e FLASK_SECRET_KEY
    -e GOOGLE_CLIENT_ID
    -e GOOGLE_CLIENT_SECRET
    -e XERO_CLIENT_ID_TEST="${XERO_CLIENT_ID_TEST:-}"
    -e XERO_CLIENT_SECRET_TEST="${XERO_CLIENT_SECRET_TEST:-}"
    -e xero_client_id_test="${xero_client_id_test:-}"
    -e xero_client_secret_test="${xero_client_secret_test:-}"
)
if [ -n "$POSTHOG_PROJECT_API_KEY" ]; then
    DOCKER_RUN_ARGS+=(-e POSTHOG_PROJECT_API_KEY="$POSTHOG_PROJECT_API_KEY")
fi
if [ -n "$DB_PASSWORD" ]; then
    DOCKER_RUN_ARGS+=(-e POSTGRES_PASSWORD="$DB_PASSWORD")
fi

# From here the old app is gone: any failure exits 3 so the CI job rolls back to :test-stable
# (a "name already in use" or port conflict used to exit 125 and leave test with no app).
if ! docker run "${DOCKER_RUN_ARGS[@]}" "$RUN_IMAGE"; then
    echo "❌ Could not start workflow-engine-test after removing the old app."
    exit 3
fi

# Don't report success until the app answers. cd_e2e used to start while the container was
# still booting and fail on ERR_CONNECTION_REFUSED (main 2026-09-30, 10-14, 10-25; see
# .agents/reports/ci/pipeline-health-2026-11.md). /healthcheck also proves the database
# connection. Exit 3 means "the new app is running but never became healthy" -- the old app
# is already gone, so the CI job rolls back to :test-stable on exactly that code.
# Probe from INSIDE the app container: deploy-target is a shell executor that itself runs in a
# container, so 127.0.0.1:8001 from the job is not the Docker host (main went red on 2026-11-07
# with a healthy app because curl in the job never reached it). The image always has python.
HEALTH_URL="${DEPLOY_HEALTH_URL:-https://127.0.0.1:8001/healthcheck}"
HEALTH_PROBE="import ssl,sys,urllib.request
try:
    r = urllib.request.urlopen(sys.argv[1], context=ssl._create_unverified_context(), timeout=5)
    sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)"
echo "Waiting for $HEALTH_URL (probed inside workflow-engine-test) ..."
healthy=""
for _ in $(seq 1 "${DEPLOY_HEALTH_ATTEMPTS:-60}"); do
    if [ "$(docker inspect -f '{{.State.Running}}' workflow-engine-test 2>/dev/null)" != true ]; then
        echo "❌ workflow-engine-test exited during startup."
        break
    fi
    if docker exec workflow-engine-test python -c "$HEALTH_PROBE" "$HEALTH_URL" >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep "${DEPLOY_HEALTH_INTERVAL:-2}"
done
if [ -z "$healthy" ]; then
    echo "❌ workflow-engine-test did not pass its health check. Last log lines:"
    docker logs --tail 40 workflow-engine-test 2>&1 || true
    exit 3
fi

echo "✅ Test environment started on port 8001 and passed its health check"
echo "View logs with: docker logs -f workflow-engine-test"
echo "Browse to: https://test-workflow-engine.whistlebird.co.nz"
