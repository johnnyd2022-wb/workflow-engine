#!/usr/bin/env bash
# Build and (re)start production on this machine.
#
#   scripts/run_prod.sh            build the image from this checkout, back up, migrate, restart
#   PROD_HOST_PORT=8010 scripts/run_prod.sh
#
# What it does, in order, stopping at the first failure:
#   0. requires a clean checkout of freshly fetched origin/main and takes a deploy lock
#   1. loads production secrets from KeePassXC (scripts/prod_secrets.py); never from a file
#   2. builds the `production` image
#   3. makes sure the database container is up (scripts/prod_db.sh)
#   4. backs the database up (including on first deploy) -- a failed backup stops the deploy
#   5. runs migrations with the new image
#   6. checks a candidate alongside the old app, then hands over the port with rollback
#
# The app listens on 127.0.0.1:${PROD_HOST_PORT} only; whatever fronts production (the
# Cloudflare tunnel) connects to it there. Uploaded files live on named volumes, so a
# redeploy keeps them.
set -euo pipefail

CONTAINER=workflow-engine-prod
NETWORK=workflow-engine-prod
HOST_PORT="${PROD_HOST_PORT:-8010}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# shellcheck source=scripts/deploy_common.sh
source "$repo_root/scripts/deploy_common.sh"
DEPLOY_ENV=prod
DEPLOY_NAME=Production
APP_PORT=8000
PUBLISH_ADDRESS="127.0.0.1:${HOST_PORT}:8000"
acquire_deploy_lock

echo "== Checkout"
check_checkout
source_sha="$(git rev-parse HEAD)"
release="$(git rev-parse --short=12 HEAD)-$(date +%s)-$$"
IMAGE="workflow-engine:prod-$release"
CANDIDATE="$CONTAINER-candidate-$release"
PREVIOUS="$CONTAINER-previous-$release"

echo "== Secrets"
# Keep the export's exit status: eval "$(...)" would hide a KeePass failure.
secret_exports="$(python3 scripts/prod_secrets.py export)"
eval "$secret_exports"
unset secret_exports
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
# Catch edits or a newer main arriving during the build before touching the database.
check_checkout "$source_sha"

echo "== Database"
scripts/prod_db.sh up
backup_file="$(scripts/prod_db.sh backup)"
echo "Backup: $backup_file"

echo "== Migrations"
docker run --rm --network "$NETWORK" "${SECRET_ENV[@]}" "$IMAGE" uv run alembic upgrade head

echo "== App"
docker volume create workflow-engine-prod-evidence >/dev/null
docker volume create workflow-engine-prod-process-docs >/dev/null

APP_ARGS=("${SECRET_ENV[@]}"
    -v workflow-engine-prod-evidence:/data/evidence
    -v workflow-engine-prod-process-docs:/data/process_docs
)
deploy_app
