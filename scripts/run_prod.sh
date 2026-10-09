#!/usr/bin/env bash
# Build and (re)start production on this machine.
#
#   scripts/run_prod.sh            build the image from this checkout, back up, migrate, restart
#   PROD_HOST_PORT=8010 scripts/run_prod.sh
#
# What it does, in order, stopping at the first failure:
#   1. loads production secrets from KeePassXC (scripts/prod_secrets.py); never from a file
#   2. builds the `production` image
#   3. makes sure the database container is up (scripts/prod_db.sh)
#   4. backs the database up, if it already has a schema -- a failed backup stops the deploy
#   5. runs migrations with the new image
#   6. replaces the app container and waits for its health check
#
# The app listens on 127.0.0.1:${PROD_HOST_PORT} only; whatever fronts production (the
# Cloudflare tunnel) connects to it there. Uploaded files live on named volumes, so a
# redeploy keeps them.
set -euo pipefail

CONTAINER=workflow-engine-prod
IMAGE=workflow-engine:prod
NETWORK=workflow-engine-prod
DB_CONTAINER=workflow-engine-prod-db
HOST_PORT="${PROD_HOST_PORT:-8010}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "== Secrets"
eval "$(python3 scripts/prod_secrets.py export)"
for name in POSTGRES_PASSWORD FLASK_SECRET_KEY BACKUP_CODE_ENCRYPTION_KEY XERO_TOKEN_ENCRYPTION_KEY \
    GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET; do
    [ -n "${!name:-}" ] || { echo "Missing $name." >&2; exit 1; }
    export "${name?}"
done
export XERO_CLIENT_ID="${XERO_CLIENT_ID:-}" XERO_CLIENT_SECRET="${XERO_CLIENT_SECRET:-}"
[ -n "$XERO_CLIENT_ID" ] || echo "Note: no Xero credentials; Sales cannot connect to Xero until they are added."

SECRET_ENV=(-e ENVIRONMENT=prod -e POSTGRES_PASSWORD -e FLASK_SECRET_KEY -e BACKUP_CODE_ENCRYPTION_KEY
    -e XERO_TOKEN_ENCRYPTION_KEY -e XERO_CLIENT_ID -e XERO_CLIENT_SECRET
    -e GOOGLE_CLIENT_ID -e GOOGLE_CLIENT_SECRET)

echo "== Build"
docker build --target production -f Dockerfile.multi -t "$IMAGE" .

echo "== Database"
scripts/prod_db.sh up
if docker exec "$DB_CONTAINER" psql -U workflow_rw -d workflow-engine -Atc "select 1 from alembic_version limit 1" >/dev/null 2>&1; then
    echo "Backup: $(scripts/prod_db.sh backup)"
else
    echo "No schema yet, so nothing to back up."
fi

echo "== Migrations"
docker run --rm --network "$NETWORK" "${SECRET_ENV[@]}" "$IMAGE" uv run alembic upgrade head

echo "== App"
docker volume create workflow-engine-prod-evidence >/dev/null
docker volume create workflow-engine-prod-process-docs >/dev/null
# Exact-name match: a plain "name=" filter is a substring match and would also hit the database.
docker stop $(docker ps -aqf "name=^${CONTAINER}$") 2>/dev/null || true
docker rm $(docker ps -aqf "name=^${CONTAINER}$") 2>/dev/null || true
docker run -d --name "$CONTAINER" --restart unless-stopped \
    --network "$NETWORK" -p "127.0.0.1:${HOST_PORT}:8000" \
    "${SECRET_ENV[@]}" \
    -v workflow-engine-prod-evidence:/data/evidence \
    -v workflow-engine-prod-process-docs:/data/process_docs \
    "$IMAGE" >/dev/null

echo "== Health"
for _ in $(seq 1 60); do
    if curl -kfs "https://127.0.0.1:${HOST_PORT}/healthcheck" >/dev/null 2>&1; then
        echo "Production is up at https://127.0.0.1:${HOST_PORT} (container $CONTAINER)."
        echo "Logs: docker logs -f $CONTAINER"
        exit 0
    fi
    sleep 2
done
echo "Production did not pass its health check. Last log lines:" >&2
docker logs --tail 40 "$CONTAINER" >&2
exit 1
