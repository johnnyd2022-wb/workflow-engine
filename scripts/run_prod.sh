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

# This lock is shared across worktrees for this operator. Other users must not deploy
# concurrently. Nothing below reads production secrets or changes Docker until Git passes.
mkdir -p "$HOME/.cache/workflow-engine"
exec 9>"$HOME/.cache/workflow-engine/prod-deploy.lock"
flock -n 9 || { echo "Another production deploy is running." >&2; exit 1; }

check_checkout() {
    local checkout_status head_sha remote_sha
    checkout_status="$(git status --porcelain --untracked-files=all)"
    [ -z "$checkout_status" ] || {
        echo "Production requires a clean checkout (including untracked files)." >&2; exit 1;
    }
    git fetch origin '+refs/heads/main:refs/remotes/origin/main'
    head_sha="$(git rev-parse HEAD)"
    remote_sha="$(git rev-parse refs/remotes/origin/main)"
    [ "$head_sha" = "$remote_sha" ] || {
        echo "Production requires HEAD to equal freshly fetched origin/main. Update your checkout." >&2; exit 1;
    }
    if [ -n "${1:-}" ] && [ "$head_sha" != "$1" ]; then
        echo "Checkout commit changed during the build. Run the deployment again." >&2; exit 1;
    fi
}
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

candidate_created=0
old_moved=0
new_attempted=0
committed=0
cleanup() {
    local result=$?
    trap - EXIT INT TERM
    if [ "$committed" = 0 ]; then
        if [ "$new_attempted" = 1 ]; then
            docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
        fi
        if [ "$old_moved" = 1 ] && docker container inspect "$PREVIOUS" >/dev/null 2>&1; then
            echo "Restoring previous app container (database migrations are not reversed)." >&2
            if docker rename "$PREVIOUS" "$CONTAINER" && docker start "$CONTAINER" >/dev/null; then
                if ! wait_health "$CONTAINER" published; then
                    echo "CRITICAL: previous app failed its health check; manual recovery required." >&2
                fi
            else
                echo "CRITICAL: could not restore $PREVIOUS; manual recovery required." >&2
            fi
        fi
    fi
    if [ "$candidate_created" = 1 ]; then
        docker rm -f "$CANDIDATE" >/dev/null 2>&1 || true
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

start_app() {
    local name=$1
    shift
    docker run -d --name "$name" "$@" --network "$NETWORK" \
        "${SECRET_ENV[@]}" \
        -v workflow-engine-prod-evidence:/data/evidence \
        -v workflow-engine-prod-process-docs:/data/process_docs \
        "$IMAGE" >/dev/null
}

wait_health() {
    local name=$1 mode=$2
    for _ in $(seq 1 60); do
        # Never accept a healthy response from a different process on the host port.
        if [ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" != true ]; then
            break
        fi
        if [ "$mode" = published ]; then
            if curl --max-time 5 -kfs "https://127.0.0.1:${HOST_PORT}/healthcheck" >/dev/null 2>&1; then
                return 0
            fi
        elif docker exec "$name" curl --max-time 5 -kfs https://127.0.0.1:8000/healthcheck >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    echo "$name did not pass its health check. Last log lines:" >&2
    docker logs --tail 40 "$name" >&2 || true
    return 1
}

echo "== Candidate health (existing app stays running)"
candidate_created=1
# No host port or restart policy: a failed candidate can never take over traffic.
start_app "$CANDIDATE"
wait_health "$CANDIDATE" internal
docker rm -f "$CANDIDATE" >/dev/null
candidate_created=0

echo "== Port handover"
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    # Record intent before Docker: INT/TERM may arrive after the daemon renames it
    # but before the command returns. Cleanup reconciles whether PREVIOUS exists.
    old_moved=1
    docker rename "$CONTAINER" "$PREVIOUS"
    docker stop "$PREVIOUS" >/dev/null
fi
new_attempted=1
start_app "$CONTAINER" --restart unless-stopped -p "127.0.0.1:${HOST_PORT}:8000"
wait_health "$CONTAINER" published
committed=1
if [ "$old_moved" = 1 ]; then
    echo "Previous app retained stopped as $PREVIOUS (remove manually after acceptance)."
fi
echo "Production is up at https://127.0.0.1:${HOST_PORT} (container $CONTAINER, image $IMAGE)."
echo "Logs: docker logs -f $CONTAINER"
