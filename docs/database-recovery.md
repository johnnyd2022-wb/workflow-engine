# Database backup and isolated restore rehearsal

Real tenants belong in the production database. Automated tests and demos belong in
separate databases containing synthetic data. Never restore real tenants into the
ordinary test database. The old `restore-db` shortcut now directs operators here.

## Backup

Run on the Docker host that holds the production database, using its actual container,
database and role names:

```bash
install -d -m 700 /var/backups/workflow-engine
python3 scripts/database_recovery.py backup \
  --container workflow-engine-prod-db --database workflow-engine \
  --user workflow_rw --directory /var/backups/workflow-engine
```

`pg_dump` creates a consistent custom-format archive. Files are private (0600), with an
atomic archive publish and a JSON SHA256 manifest. Failed dumps leave no partial file.
The immutable local source-image ID is saved for rehearsal compatibility. Preserve that
image on the recovery host; archives and manifests alone do not retain the Docker image.
Local backups are not off-host protection: copy both files to encrypted storage with
restricted access and a documented retention policy. This tool does not delete backups.
Monitor disk capacity and age of the newest successful manifest.

## Nightly scheduling

Install the service and timer from `deploy/systemd/workflow-database-backup.*` into
`/etc/systemd/system/`. Create `/etc/workflow-engine/database-backup.env` (0600):

```ini
WORKFLOW_CHECKOUT=/opt/workflow-engine
WORKFLOW_DB_CONTAINER=workflow-engine-prod-db
WORKFLOW_DB_NAME=workflow-engine
WORKFLOW_DB_USER=workflow_rw
WORKFLOW_BACKUP_DIRECTORY=/var/backups/workflow-engine
```

Use the real deployment paths; the defaults above are examples. The service runs as
root to access Docker and private backups. Run it manually and inspect its result before
enabling the timer:

```bash
sudo systemctl daemon-reload
sudo systemctl start workflow-database-backup.service
sudo journalctl -u workflow-database-backup.service --no-pager
sudo systemctl enable --now workflow-database-backup.timer
sudo systemctl list-timers workflow-database-backup.timer
```

It runs at 00:30 Pacific/Auckland with up to five minutes of jitter and catches missed
runs. A failed service needs an operator alert; installing this timer alone does not
provide alerting or remote copies.

## Rehearse

Use the archive and its adjacent JSON manifest:

```bash
scripts/db_restore.sh /var/backups/workflow-engine/ARCHIVE.dump /var/backups/workflow-engine/rehearsal-UNIQUE.json
```

The command verifies SHA256, creates a randomly named container using the saved image,
restores via a Unix socket, records structural counts, and removes its container and
volumes. No network, published ports or host mounts are attached. Data directories use
tmpfs; allow enough RAM for the restored database. It never stops or modifies the
source database or the shared test container. Do not use untrusted archives/manifests:
restoring a PostgreSQL archive executes database commands.

Successful evidence is only written after both restore and container cleanup succeed;
it contains no customer rows. The evidence file must be new. Retain it with the backup
and record the operator/date. This proves archive restoration, not full application
recovery or external integrations. Before go-live, rehearse the actual production
backup and record the application recovery procedure and time budget too.

## Current evidence and remaining go-live work

A rehearsal of the disposable synthetic source-to-sale scenario database was performed
on 28 September 2026: 51 public tables and 584 constraints restored in 1.8 seconds,
with no network or published ports; the rehearsal container was removed. Production was not running on the development host, so no live
backup schedule was installed. Plan 0.1 remains open until production/test separation,
production scheduling, off-host retention and a real backup rehearsal are evidenced.
