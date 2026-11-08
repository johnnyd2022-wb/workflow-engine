#!/usr/bin/env bash
# Look at the daily restored copy of production (the database scripts/prod_backup.sh
# restores into `workflow-engine-restored`). Installed as `biz-e-restored`.
#
#   biz-e-restored                  open psql on the copy, read-only
#   biz-e-restored status           when it was restored, from which dump, and how it compares with live
#   biz-e-restored tables           every table with its row count, largest first
#   biz-e-restored query "SQL"      run one statement and print the result (add --csv for CSV)
#   biz-e-restored write            open psql with writes allowed (the copy is replaced at the next backup)
#   biz-e-restored help
#
# Everything is read-only unless you ask for `write`, so a mistyped statement cannot change
# anything. Nothing here can touch production: it only ever connects to the copy.
#
# Install or update:  install -m 755 scripts/restored_db.sh ~/.local/bin/biz-e-restored
set -euo pipefail

CONTAINER=workflow-engine-prod-db
DB=workflow-engine-restored
LIVE_DB=workflow-engine
DB_USER=workflow_rw
READ_ONLY="-c default_transaction_read_only=on"
# cron and bare shells do not read ~/.bashrc, where this is set for interactive shells.
export DOCKER_API_VERSION="${DOCKER_API_VERSION:-1.43}"

if [ -t 1 ]; then bold=$'\e[1m' dim=$'\e[2m' red=$'\e[31m' green=$'\e[32m' reset=$'\e[0m'; else bold= dim= red= green= reset=; fi
die() { echo "${red}biz-e-restored:${reset} $*" >&2; exit 1; }
usage() { sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
# psql against DATABASE with OPTIONS; stdin is passed through for interactive use.
run() { local database="$1" options="$2"; shift 2; docker exec ${TTY:-} -e PGOPTIONS="$options" "$CONTAINER" psql -U "$DB_USER" -d "$database" "$@"; }
value() { run "$1" "$READ_ONLY" -v ON_ERROR_STOP=1 -Atc "$2"; }

require_copy() {
    docker version >/dev/null 2>&1 || die "cannot talk to Docker."
    [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ] || die "$CONTAINER is not running."
    [ "$(value postgres "select count(*) from pg_database where datname = '$DB'")" = "1" ] \
        || die "there is no restored copy yet. Run the backup once: ~/biz-e_db_backups.sh"
}

banner() {
    local note; note="$(value postgres "select coalesce(shobj_description(oid, 'pg_database'), 'restore time not recorded') from pg_database where datname = '$DB'")"
    echo "${bold}Restored copy of production${reset} ${dim}($DB)${reset}"
    echo "${dim}$note${reset}"
}

command="${1:-shell}"
[ $# -gt 0 ] && shift
case "$command" in
shell)
    require_copy; banner
    echo "${green}Read-only.${reset} ${dim}\\dt lists tables, \\q quits.${reset}"; echo
    TTY=-it run "$DB" "$READ_ONLY" -v PROMPT1="restored=> " -v PROMPT2="restored-> "
    ;;
write)
    require_copy; banner
    echo "${red}Writes allowed.${reset} ${dim}Changes last until the next backup replaces this copy.${reset}"; echo
    TTY=-it run "$DB" "" -v PROMPT1="restored(write)=> " -v PROMPT2="restored(write)-> "
    ;;
status)
    require_copy; banner; echo
    facts="select (select version_num from alembic_version), (select count(*) from organisations),
           (select count(*) from users), (select count(*) from audit_logs),
           (select to_char(max(timestamp) at time zone 'Pacific/Auckland', 'YYYY-MM-DD HH24:MI') from audit_logs),
           pg_size_pretty(pg_database_size(current_database()))"
    IFS='|' read -r r_schema r_orgs r_users r_audit r_last r_size <<<"$(value "$DB" "$facts")"
    IFS='|' read -r l_schema l_orgs l_users l_audit l_last l_size <<<"$(value "$LIVE_DB" "$facts")"
    printf "${bold}%-22s %-32s %s${reset}\n" "" "Restored copy" "Live production"
    printf "%-22s %-32s %s\n" "Schema version" "$r_schema" "$l_schema" "Organisations" "$r_orgs" "$l_orgs" \
        "Users" "$r_users" "$l_users" "Audit entries" "$r_audit" "$l_audit" \
        "Last activity (NZ)" "${r_last:-none}" "${l_last:-none}" "Size" "$r_size" "$l_size"
    echo
    echo "${bold}Organisations in the copy${reset}"
    run "$DB" "$READ_ONLY" -c "select o.name, o.status, count(u.id) as users, o.created_at::date as created
                               from organisations o left join users u on u.org_id = o.id group by o.id order by o.name"
    ;;
tables)
    require_copy
    # Exact counts, not planner estimates: a fresh restore has no statistics yet.
    run "$DB" "$READ_ONLY" -c "select table_name as \"table\",
        (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from %I', table_name), false, true, '')))[1]::text::bigint as rows
        from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' order by rows desc, 1"
    ;;
query)
    require_copy
    format=()
    [ "${1:-}" = "--csv" ] && { format=(--csv); shift; }
    [ -n "${1:-}" ] || die 'give one SQL statement, e.g.  biz-e-restored query "select count(*) from users"'
    run "$DB" "$READ_ONLY" -v ON_ERROR_STOP=1 "${format[@]}" -c "$1"
    ;;
help | -h | --help)
    usage
    ;;
*)
    usage >&2
    exit 2
    ;;
esac
