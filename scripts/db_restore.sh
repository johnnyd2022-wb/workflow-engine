#!/bin/bash
# Rehearsals are isolated; never copy production tenants into the shared test DB.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ "$#" -ne 2 ]; then
    echo 'Usage: db_restore.sh ARCHIVE.dump EVIDENCE.json (isolated restore rehearsal)' >&2
    exit 2
fi
exec python3 "$script_dir/database_recovery.py" rehearse "$1" --evidence "$2"
