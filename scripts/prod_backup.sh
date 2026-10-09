#!/usr/bin/env bash
# Nightly production database backup: dump, prove it restores, copy it to Google Drive.
#
#   scripts/prod_backup.sh             dump, rehearse the restore, upload, tidy up
#   scripts/prod_backup.sh --no-upload the same without the Google Drive copy
#
# It is self-contained on purpose (Docker and gam only, no KeePassXC, nothing else from the
# repository), so cron can run an installed copy whatever branch the checkout is on:
#
#   install -m 755 scripts/prod_backup.sh ~/biz-e_db_backups.sh
#   10 18 * * *  /home/johnny/biz-e_db_backups.sh >> /home/johnny/db-backups/biz-e_db_backups.log 2>&1
#
# What a run does, stopping at the first failure:
#   1. pg_dump (custom format) to ~/db-backups/workflow-engine-prod/
#   2. restores that dump into a scratch database beside production and checks it holds the
#      same organisations, users and schema version; the scratch database is then dropped
#   3. uploads the dump to the Google Drive folder biz-e_db_backups, as the existing
#      Whistlebird backups are (gam, johnny@whistlebird.co.nz)
#   4. deletes local dumps older than 30 days; Drive keeps every copy
#
# The dump holds everything in production, including password hashes. It is as sensitive as
# the database; the Drive folder inherits the Whistlebird folder's sharing.
set -euo pipefail

CONTAINER=workflow-engine-prod-db
DB_NAME=workflow-engine
DB_USER=workflow_rw
SCRATCH_DB=backup_rehearsal
BACKUP_DIR="${PROD_DB_BACKUP_DIR:-$HOME/db-backups/workflow-engine-prod}"
KEEP_DAYS=30
GAM="${GAM:-$HOME/bin/gam/gam}"
DRIVE_USER=johnny@whistlebird.co.nz
DRIVE_FOLDER_ID=14xgWF8Aw46OiQH1zkdV0vnnZeuyINtL2 # Whistlebird/biz-e_db_backups

# cron does not read ~/.bashrc, where this is set for interactive shells. Without it the
# docker client is newer than this machine's Docker engine accepts and every call fails.
export DOCKER_API_VERSION="${DOCKER_API_VERSION:-1.43}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
fail() { log "FAILED: $*" >&2; exit 1; }
sql() { docker exec "$CONTAINER" psql -U "$DB_USER" -d "$1" -v ON_ERROR_STOP=1 -Atc "$2"; }
# What must survive a restore: the schema version and how much is in the tables that matter.
fingerprint() {
    sql "$1" "select (select version_num from alembic_version) || ' orgs=' || (select count(*) from organisations)
              || ' users=' || (select count(*) from users) || ' audit=' || (select count(*) from audit_logs)"
}

docker version >/dev/null 2>&1 || fail "cannot talk to Docker: $(docker version 2>&1 | tail -1)"
[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ] || fail "$CONTAINER is not running"
mkdir -p "$BACKUP_DIR"
file="$BACKUP_DIR/workflow-engine-prod-$(date +%Y-%m-%d-%H%M%S).dump"

log "Dumping $DB_NAME"
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB_NAME" >"$file" || fail "pg_dump"
[ -s "$file" ] || fail "the dump is empty"

log "Rehearsing the restore"
live="$(fingerprint "$DB_NAME")"
trap 'docker exec "$CONTAINER" dropdb -U "$DB_USER" --if-exists "$SCRATCH_DB" >/dev/null 2>&1 || true' EXIT
docker exec "$CONTAINER" dropdb -U "$DB_USER" --if-exists "$SCRATCH_DB"
docker exec "$CONTAINER" createdb -U "$DB_USER" "$SCRATCH_DB"
docker exec -i "$CONTAINER" pg_restore -U "$DB_USER" -d "$SCRATCH_DB" --no-owner --exit-on-error <"$file" \
    || fail "the dump does not restore"
restored="$(fingerprint "$SCRATCH_DB")"
# Production keeps taking writes during the dump, so only the audit count may have moved on.
[ "${restored% audit=*}" = "${live% audit=*}" ] || fail "restored copy differs: live [$live], restored [$restored]"
log "Restore verified: $restored ($(du -h "$file" | cut -f1))"

if [ "${1:-}" = "--no-upload" ]; then
    log "Upload skipped"
else
    [ -x "$GAM" ] || fail "gam not found at $GAM"
    log "Uploading to Google Drive"
    "$GAM" user "$DRIVE_USER" add drivefile localfile "$file" parentid "$DRIVE_FOLDER_ID" || fail "the Google Drive upload"
fi

find "$BACKUP_DIR" -name 'workflow-engine-prod-*.dump' -mtime +"$KEEP_DAYS" -delete
log "Done: $file"
