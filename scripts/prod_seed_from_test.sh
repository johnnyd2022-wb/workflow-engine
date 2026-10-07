#!/usr/bin/env bash
# Seed production with ONE organisation from the local test database, and nothing else.
#
#   scripts/prod_seed_from_test.sh "Whistlebird Ltd" [--disable-user EMAIL]... [--replace]
#
# Rows:  scripts/tenant_copy.py copies every tenant table filtered to that organisation,
#        verifies the counts and commits only if they match. The Xero connection token is
#        left behind on purpose: production connects with its own Xero app.
# Files: uploads are on disk, not in the database. The organisation's folders are copied
#        from the test app container when they exist there; an NP3 record file that is
#        missing is restored from docs/evidence/ when a committed file has the same
#        checksum. Anything still missing is listed at the end.
#
# --replace deletes that organisation's rows in production first. Use it only before
# go-live, to refresh the copy; after go-live production is the source of truth.
set -euo pipefail

[ $# -ge 1 ] || { sed -n '2,5p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }
ORG_NAME="$1"; shift
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

TEST_APP=workflow-engine-test
TEST_DB=workflow-engine-test-db
PROD_DB=workflow-engine-prod-db

SOURCE_URL="$(ENVIRONMENT=local uv run python - <<'PY' 2>/dev/null | tail -n 1
from sqlalchemy.engine import URL
from app.utils.config_loader import config
print(URL.create("postgresql+psycopg2", username=config.db_user, password=config.db_password, host=config.db_host,
                 port=config.db_port, database=config.db_name).render_as_string(hide_password=False))
PY
)"
TARGET_URL="$(scripts/prod_db.sh url)"

echo "== Rows"
uv run python scripts/tenant_copy.py copy --source-url "$SOURCE_URL" --target-url "$TARGET_URL" \
    --org-name "$ORG_NAME" --skip-table xero_oauth_tokens "$@" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("copied", d["copied_rows"], "rows across", sum(1 for v in d["tables"].values() if v), "tables; other organisations in production:", d["other_organisations_in_target"], "; accounts locked:", d["users_disabled"])'

ORG_ID="$(docker exec "$PROD_DB" psql -U workflow_rw -d workflow-engine -Atc "select id from organisations where name = \$\$${ORG_NAME}\$\$")"

echo "== Files"
copy_tree() { # <path in test app container> <production volume>
    if docker exec "$TEST_APP" test -d "$1/$ORG_ID" 2>/dev/null; then
        docker exec "$TEST_APP" tar -C "$1" -cf - "$ORG_ID" | docker run --rm -i -v "$2:/data" alpine tar -C /data -xf -
        echo "copied $(docker exec "$TEST_APP" sh -c "find '$1/$ORG_ID' -type f | wc -l") file(s) from $1"
    else
        echo "no folder for this organisation under $1 in $TEST_APP"
    fi
}
docker volume create workflow-engine-prod-evidence >/dev/null
docker volume create workflow-engine-prod-process-docs >/dev/null
copy_tree /app/app/core/evidence_storage workflow-engine-prod-evidence
copy_tree /app/app/core/process_docs_storage workflow-engine-prod-process-docs

# NP3 record files live at <evidence root>/<org>/np3-<record>/<storage_name>.
missing=0
while IFS='|' read -r record_id storage_name checksum file_name; do
    [ -n "$record_id" ] || continue
    target="/data/$ORG_ID/np3-$record_id/$storage_name"
    # </dev/null: a container must not swallow the list this loop is reading.
    if docker run --rm -v workflow-engine-prod-evidence:/data alpine test -f "$target" </dev/null; then
        continue
    fi
    # No early exit in awk: with pipefail, closing the pipe early would fail the whole script.
    source_file="$(find docs/evidence -type f -exec sha256sum {} + 2>/dev/null | awk -v sum="$checksum" '$1 == sum {found = $2} END {print found}')"
    if [ -n "$source_file" ]; then
        docker run --rm -i -v workflow-engine-prod-evidence:/data alpine sh -c "mkdir -p '$(dirname "$target")' && cat > '$target'" <"$source_file"
        echo "restored $file_name from $source_file"
    else
        echo "MISSING: $file_name (record $record_id) is not in the test container or docs/evidence"
        missing=$((missing + 1))
    fi
done < <(docker exec "$PROD_DB" psql -U workflow_rw -d workflow-engine -At -F'|' -c \
    "select record_id, storage_name, checksum_sha256, file_name from compliance_record_files where org_id = '$ORG_ID'")
[ "$missing" -eq 0 ] && echo "every NP3 record file is in place" || echo "$missing NP3 record file(s) could not be found"
