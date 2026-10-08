#!/usr/bin/env bash
# Build and (re)start the admin site (admin-test.biz-e.app) on this machine.
#
#   scripts/run_admin.sh
#   ADMIN_HOST_PORT=8020 scripts/run_admin.sh
#   ADMIN_PUBLIC_URL=https://admin.biz-e.app scripts/run_admin.sh   (default https://admin-test.biz-e.app)
#
# The admin site is its own container from the same code (Dockerfile.multi target `admin`),
# on production's Docker network so it reaches the production database by name. It runs no
# migrations and takes no backup: scripts/run_prod.sh owns the schema. It listens on
# 127.0.0.1:${ADMIN_HOST_PORT} only; the Cloudflare tunnel connects to it there.
#
# Secrets come from KeePassXC (scripts/prod_secrets.py --scope admin), never from a file.
# It gets the database password, its own session key and Google client, and the 2FA
# backup-code key (staff can read a locked-out person their codes): none of the customer
# app's other keys. Documents staff upload live on the volume workflow-engine-admin-documents.
set -euo pipefail

CONTAINER=workflow-engine-admin
IMAGE=workflow-engine:admin
NETWORK=workflow-engine-prod
HOST_PORT="${ADMIN_HOST_PORT:-8020}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "== Secrets"
eval "$(python3 scripts/prod_secrets.py export --scope admin)"
for name in POSTGRES_PASSWORD ADMIN_FLASK_SECRET_KEY ADMIN_GOOGLE_CLIENT_ID ADMIN_GOOGLE_CLIENT_SECRET \
    BACKUP_CODE_ENCRYPTION_KEY; do
    [ -n "${!name:-}" ] || { echo "Missing $name." >&2; exit 1; }
    export "${name?}"
done
# Where Google sends people back to. Must match the hostname the site is reached on and be
# registered on the Google client. Override with ADMIN_PUBLIC_URL when the site moves hostname.
export ADMIN_GOOGLE_REDIRECT_URI="${ADMIN_PUBLIC_URL:-https://admin-test.biz-e.app}/auth/google/callback"
echo "Google redirect URI: $ADMIN_GOOGLE_REDIRECT_URI"
export APP_VERSION="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

echo "== Build"
docker build --target admin -f Dockerfile.multi -t "$IMAGE" .

echo "== Database"
scripts/prod_db.sh up

echo "== Admin site"
docker volume create workflow-engine-admin-documents >/dev/null
# Exact-name match: a plain "name=" filter is a substring match.
docker stop $(docker ps -aqf "name=^${CONTAINER}$") 2>/dev/null || true
docker rm $(docker ps -aqf "name=^${CONTAINER}$") 2>/dev/null || true
docker run -d --name "$CONTAINER" --restart unless-stopped \
    --network "$NETWORK" -p "127.0.0.1:${HOST_PORT}:8020" \
    -e ENVIRONMENT=prod -e POSTGRES_PASSWORD -e ADMIN_FLASK_SECRET_KEY \
    -e ADMIN_GOOGLE_CLIENT_ID -e ADMIN_GOOGLE_CLIENT_SECRET -e ADMIN_GOOGLE_REDIRECT_URI \
    -e BACKUP_CODE_ENCRYPTION_KEY -e APP_VERSION \
    -e ADMIN_DOCUMENTS_ROOT=/data/admin_documents -v workflow-engine-admin-documents:/data/admin_documents \
    "$IMAGE" >/dev/null

echo "== Health"
for _ in $(seq 1 60); do
    if curl -kfs "https://127.0.0.1:${HOST_PORT}/healthcheck" >/dev/null 2>&1; then
        echo "The admin site is up at https://127.0.0.1:${HOST_PORT} (container $CONTAINER)."
        echo "Logs: docker logs -f $CONTAINER"
        exit 0
    fi
    sleep 2
done
echo "The admin site did not pass its health check. Last log lines:" >&2
docker logs --tail 40 "$CONTAINER" >&2
exit 1
