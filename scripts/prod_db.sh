#!/usr/bin/env bash
# The production database: one PostgreSQL container on its own Docker network.
#
#   scripts/prod_db.sh up        create the network, volume and container if missing, and start it
#   scripts/prod_db.sh status    show the container, its volume and the migration revision
#   scripts/prod_db.sh backup    pg_dump to ~/db-backups/workflow-engine-prod/ (custom format)
#   scripts/prod_db.sh psql      open psql in the container
#   scripts/prod_db.sh url       print the connection URL for tools on this machine (secret)
#
# The app reaches the database by container name on the `workflow-engine-prod` network. The
# port is published on loopback only (127.0.0.1:8432) for tools run on this machine; it is
# never reachable from the network. Data lives on the named volume `workflow-engine-prod-db`,
# so removing or recreating the container does not lose it. Nothing here deletes that volume.
set -euo pipefail

NETWORK=workflow-engine-prod
CONTAINER=workflow-engine-prod-db
VOLUME=workflow-engine-prod-db
DB_NAME=workflow-engine
DB_USER=workflow_rw
HOST_PORT=8432
IMAGE=postgres:16
BACKUP_DIR="${PROD_DB_BACKUP_DIR:-$HOME/db-backups/workflow-engine-prod}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

load_password() {
    if [ -z "${POSTGRES_PASSWORD:-}" ]; then
        eval "$(python3 "$repo_root/scripts/prod_secrets.py" export)"
    fi
    [ -n "${POSTGRES_PASSWORD:-}" ] || { echo "No production database password available." >&2; exit 1; }
    export POSTGRES_PASSWORD
}

running() { [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]; }

wait_ready() {
    for _ in $(seq 1 60); do
        docker exec "$CONTAINER" pg_isready -q -U "$DB_USER" -d "$DB_NAME" && return 0
        sleep 1
    done
    echo "The production database did not become ready." >&2
    return 1
}

case "${1:-}" in
up)
    docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
    if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
        load_password
        # The password reaches the container through the environment, not the command line.
        docker run -d --name "$CONTAINER" --restart unless-stopped \
            --network "$NETWORK" -p "127.0.0.1:${HOST_PORT}:5432" \
            -e POSTGRES_DB="$DB_NAME" -e POSTGRES_USER="$DB_USER" -e POSTGRES_PASSWORD \
            -v "$VOLUME:/var/lib/postgresql/data" \
            "$IMAGE" postgres -c max_connections=200 >/dev/null
        echo "Created $CONTAINER."
    elif ! running; then
        docker start "$CONTAINER" >/dev/null
        echo "Started $CONTAINER."
    fi
    wait_ready
    echo "Production database is ready ($CONTAINER on network $NETWORK, 127.0.0.1:$HOST_PORT)."
    ;;
status)
    docker ps -a --filter "name=^${CONTAINER}$" --format '{{.Names}}  {{.Status}}  {{.Ports}}'
    docker volume inspect "$VOLUME" --format 'volume {{.Name}} at {{.Mountpoint}}' 2>/dev/null || echo "volume $VOLUME does not exist"
    if running; then
        docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -Atc \
            "select 'migration: ' || coalesce((select version_num from alembic_version limit 1), 'none')" 2>/dev/null \
            || echo "migration: schema not created yet"
        docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -Atc \
            "select 'organisations: ' || string_agg(name, ', ') from organisations" 2>/dev/null || true
    fi
    ;;
backup)
    running || { echo "$CONTAINER is not running." >&2; exit 1; }
    mkdir -p "$BACKUP_DIR"
    file="$BACKUP_DIR/workflow-engine-prod-$(date +%Y-%m-%d-%H%M%S).dump"
    docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB_NAME" >"$file"
    # A dump that cannot be listed is not a backup.
    docker exec -i "$CONTAINER" pg_restore -l <"$file" >/dev/null
    echo "$file"
    ;;
psql)
    exec docker exec -it "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME"
    ;;
url)
    load_password
    python3 - "$DB_USER" "$HOST_PORT" "$DB_NAME" <<'PY'
import os, sys
from urllib.parse import quote
user, port, name = sys.argv[1:]
print(f"postgresql+psycopg2://{user}:{quote(os.environ['POSTGRES_PASSWORD'], safe='')}@127.0.0.1:{port}/{name}")
PY
    ;;
*)
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
