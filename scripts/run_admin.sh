#!/usr/bin/env bash
# Build and (re)start an admin site on this machine.
#
#   scripts/run_admin.sh            the TEST admin site: admin-test.biz-e.app, test database
#   scripts/run_admin.sh test       the same, said out loud
#   ADMIN_PUBLIC_URL=https://admin.biz-e.app scripts/run_admin.sh prod
#                                   the PRODUCTION admin site, production database
#
# Either way the admin site is its own container from the same code (Dockerfile.multi target
# `admin`), listening on loopback only; the Cloudflare tunnel connects to it there. It runs no
# migrations: the database it points at must already be at the current schema.
#
#   target   container                    port   database                       documents volume
#   test     workflow-engine-admin-test   8020   workflow-engine-test (:8401)   workflow-engine-admin-test-documents
#   prod     workflow-engine-admin        8021   workflow-engine-prod-db        workflow-engine-admin-documents
#
# Secrets come from KeePassXC, never from a file. Each site gets its database password, its
# own session key and the admin Google client; production also gets the 2FA backup-code key
# (test uses the same built-in development key the test app does).
set -euo pipefail

TARGET="${1:-test}"
IMAGE=workflow-engine:admin
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

keepass() { # keepass ENTRY -> its password on stdout
    python3 -c 'import sys; sys.path.insert(0, "scripts"); from local_secrets import get_keepass_entry; print(get_keepass_entry(entry_name=sys.argv[1]).get("Password", "").strip())' "$1"
}

echo "== Secrets ($TARGET)"
case "$TARGET" in
test)
    CONTAINER=workflow-engine-admin-test
    HOST_PORT="${ADMIN_HOST_PORT:-8020}"
    PUBLIC_URL="${ADMIN_PUBLIC_URL:-https://admin-test.biz-e.app}"
    DOCUMENTS_VOLUME=workflow-engine-admin-test-documents
    export ADMIN_CUSTOMER_APP_URL="${ADMIN_CUSTOMER_APP_URL:-https://test.biz-e.app}"
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD_TEST:-$(keepass workflow-engine/workflow-engine-test-db)}"
    # Its own session key, derived from the test app's so there is nothing extra to provision.
    export ADMIN_FLASK_SECRET_KEY="$(keepass workflow-engine/FLASK_SECRET_KEY_TEST | python3 -c 'import hashlib, sys; print(hashlib.sha256(b"admin-site:" + sys.stdin.read().strip().encode()).hexdigest())')"
    export ADMIN_GOOGLE_CLIENT_ID="$(keepass workflow-engine/ADMIN_GOOGLE_CLIENT_ID)"
    export ADMIN_GOOGLE_CLIENT_SECRET="$(keepass workflow-engine/ADMIN_GOOGLE_CLIENT_SECRET)"
    REQUIRED=(POSTGRES_PASSWORD ADMIN_FLASK_SECRET_KEY ADMIN_GOOGLE_CLIENT_ID ADMIN_GOOGLE_CLIENT_SECRET)
    # The test database is published on the host; test.ini reaches it at host.docker.internal:8401.
    RUN_ARGS=(-e ENVIRONMENT=test --add-host=host.docker.internal:host-gateway)
    ;;
prod)
    CONTAINER=workflow-engine-admin
    HOST_PORT="${ADMIN_HOST_PORT:-8021}"
    PUBLIC_URL="${ADMIN_PUBLIC_URL:?Set ADMIN_PUBLIC_URL to the hostname the production admin site is reached on.}"
    DOCUMENTS_VOLUME=workflow-engine-admin-documents
    export ADMIN_CUSTOMER_APP_URL="${ADMIN_CUSTOMER_APP_URL:-https://biz-e.app}"
    eval "$(python3 scripts/prod_secrets.py export --scope admin)"
    export BACKUP_CODE_ENCRYPTION_KEY="${BACKUP_CODE_ENCRYPTION_KEY:-}"
    REQUIRED=(POSTGRES_PASSWORD ADMIN_FLASK_SECRET_KEY ADMIN_GOOGLE_CLIENT_ID ADMIN_GOOGLE_CLIENT_SECRET
        BACKUP_CODE_ENCRYPTION_KEY)
    scripts/prod_db.sh up
    RUN_ARGS=(-e ENVIRONMENT=prod -e BACKUP_CODE_ENCRYPTION_KEY --network workflow-engine-prod)
    ;;
*)
    echo "Usage: scripts/run_admin.sh [test|prod]" >&2
    exit 2
    ;;
esac
for name in "${REQUIRED[@]}"; do
    [ -n "${!name:-}" ] || { echo "Missing $name." >&2; exit 1; }
    export "${name?}"
done
# Where Google sends people back to. Must match the hostname the site is reached on and be
# registered on the Google client.
export ADMIN_GOOGLE_REDIRECT_URI="${PUBLIC_URL}/auth/google/callback"
echo "Google redirect URI: $ADMIN_GOOGLE_REDIRECT_URI"
export APP_VERSION="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

echo "== Build"
docker build --target admin -f Dockerfile.multi -t "$IMAGE" .

echo "== Admin site ($TARGET)"
docker volume create "$DOCUMENTS_VOLUME" >/dev/null
# Exact-name match: a plain "name=" filter is a substring match.
docker stop $(docker ps -aqf "name=^${CONTAINER}$") 2>/dev/null || true
docker rm $(docker ps -aqf "name=^${CONTAINER}$") 2>/dev/null || true
docker run -d --name "$CONTAINER" --restart unless-stopped \
    -p "127.0.0.1:${HOST_PORT}:8020" \
    "${RUN_ARGS[@]}" \
    -e POSTGRES_PASSWORD -e ADMIN_FLASK_SECRET_KEY \
    -e ADMIN_GOOGLE_CLIENT_ID -e ADMIN_GOOGLE_CLIENT_SECRET -e ADMIN_GOOGLE_REDIRECT_URI \
    -e ADMIN_CUSTOMER_APP_URL -e APP_VERSION \
    -e ADMIN_DOCUMENTS_ROOT=/data/admin_documents -v "${DOCUMENTS_VOLUME}:/data/admin_documents" \
    "$IMAGE" >/dev/null

echo "== Health"
for _ in $(seq 1 60); do
    if curl -kfs "https://127.0.0.1:${HOST_PORT}/healthcheck" >/dev/null 2>&1; then
        echo "The $TARGET admin site is up at https://127.0.0.1:${HOST_PORT} (container $CONTAINER), public at $PUBLIC_URL."
        echo "Logs: docker logs -f $CONTAINER"
        exit 0
    fi
    sleep 2
done
echo "The $TARGET admin site did not pass its health check. Last log lines:" >&2
docker logs --tail 40 "$CONTAINER" >&2
exit 1
