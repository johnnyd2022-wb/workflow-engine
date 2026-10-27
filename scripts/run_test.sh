#!/usr/bin/env bash
# Human-triggered staging deploy from clean tracked files at current main. Build, back up, migrate,
# check a candidate alongside the running app, then hand over with app rollback.
# TEST_HOST_PORT defaults to 8001. The registry CD path is deploy_test_simple.sh.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
# shellcheck source=scripts/deploy_common.sh
source "$repo_root/scripts/deploy_common.sh"
DEPLOY_ENV="test"
DEPLOY_NAME=Staging
CONTAINER=workflow-engine-test
NETWORK=workflow-observability
HOST_PORT="${TEST_HOST_PORT:-8001}"
APP_PORT=8001
PUBLISH_ADDRESS="127.0.0.1:${HOST_PORT}:8001"
acquire_deploy_lock

echo "== Checkout"
check_checkout
source_sha="$(git rev-parse HEAD)"
release="$(git rev-parse --short=12 HEAD)-$(date +%s)-$$"
IMAGE="workflow-engine:test-$release"
CANDIDATE="$CONTAINER-candidate-$release"
PREVIOUS="$CONTAINER-previous-$release"

export ENVIRONMENT=test
echo "== Secrets"
if [ -z "${FLASK_SECRET_KEY:-}" ]; then
    FLASK_SECRET_KEY="$(uv run python -c 'from scripts.local_secrets import get_keepass_entry; print(get_keepass_entry(entry_name="workflow-engine/FLASK_SECRET_KEY_TEST").get("Password", "").strip())')"
fi
if [ "${#FLASK_SECRET_KEY}" -lt 32 ] || [ "$FLASK_SECRET_KEY" = "dev-secret-key-change-in-production" ]; then
    echo "A strong FLASK_SECRET_KEY is required before starting test." >&2
    exit 1
fi
if [ -z "${GOOGLE_CLIENT_ID:-}" ]; then
    GOOGLE_CLIENT_ID="$(uv run python -c 'from scripts.local_secrets import get_keepass_entry; print(get_keepass_entry(entry_name="workflow-engine/GOOGLE_CLIENT_ID").get("Password", "").strip())')"
fi
if [ -z "${GOOGLE_CLIENT_SECRET:-}" ]; then
    GOOGLE_CLIENT_SECRET="$(uv run python -c 'from scripts.local_secrets import get_keepass_entry; print(get_keepass_entry(entry_name="workflow-engine/GOOGLE_CLIENT_SECRET").get("Password", "").strip())')"
fi
# Prefer the test-specific password over a generic host environment value.
POSTGRES_PASSWORD="${POSTGRES_PASSWORD_TEST:-${POSTGRES_PASSWORD:-}}"
if [ -z "$POSTGRES_PASSWORD" ]; then
    POSTGRES_PASSWORD="$(uv run python -c 'from app.utils.config_loader import config; print(config.db_password)')"
fi
for name in POSTGRES_PASSWORD GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET; do
    [ -n "${!name:-}" ] || { echo "Missing $name." >&2; exit 1; }
done
export FLASK_SECRET_KEY GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET POSTGRES_PASSWORD
export XERO_CLIENT_ID_TEST="${XERO_CLIENT_ID_TEST:-}" XERO_CLIENT_SECRET_TEST="${XERO_CLIENT_SECRET_TEST:-}"
export xero_client_id_test="${xero_client_id_test:-}" xero_client_secret_test="${xero_client_secret_test:-}"
# Telemetry is optional, as in the registry CD path. Resolve before starting Docker.
POSTHOG_PROJECT_API_KEY="${POSTHOG_PROJECT_API_KEY:-}"
if [ -z "$POSTHOG_PROJECT_API_KEY" ]; then
    POSTHOG_PROJECT_API_KEY="$(uv run python -c 'from app.utils.config_loader import config; print(config.rum_posthog_api_key)' 2>/dev/null || true)"
fi
export POSTHOG_PROJECT_API_KEY
APP_ARGS=(--add-host host.docker.internal:host-gateway
    -e ENVIRONMENT=test -e FLASK_SECRET_KEY -e GOOGLE_CLIENT_ID -e GOOGLE_CLIENT_SECRET
    -e POSTHOG_PROJECT_API_KEY -e POSTGRES_PASSWORD
    -e XERO_CLIENT_ID_TEST -e XERO_CLIENT_SECRET_TEST -e xero_client_id_test -e xero_client_secret_test)

echo "== Build"
build_image_from_head test "$IMAGE" "$source_sha"
check_checkout "$source_sha"

echo "== Database backup"
backup_file="$(backup_database workflow-engine-test-db workflow_rw workflow-engine-test \
    "${TEST_DB_BACKUP_DIR:-$HOME/db-backups/workflow-engine-test}" workflow-engine-test)"
echo "Backup: $backup_file"
# The shared development/test database must already be running. Never recreate,
# downgrade, restore, or change its schema to a branch's head as deployment recovery.
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
echo "== Migrations"
docker run --rm --network "$NETWORK" "${APP_ARGS[@]}" "$IMAGE" uv run alembic upgrade head

deploy_app
