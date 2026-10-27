#!/usr/bin/env bash
# Shared helpers for human-triggered run_prod.sh and run_test.sh.
# Sourcing only defines functions. Callers set environment-specific Docker arguments.

acquire_deploy_lock() {
    # This lock is shared across worktrees for this operator. Other users must not deploy
    # concurrently. Nothing below reads deployment secrets or changes Docker until Git passes.
    mkdir -p "$HOME/.cache/workflow-engine"
    exec 9>"$HOME/.cache/workflow-engine/${DEPLOY_ENV}-deploy.lock"
    flock -n 9 || { echo "Another ${DEPLOY_NAME} deploy is running." >&2; exit 1; }

}

check_checkout() {
    local checkout_status head_sha remote_sha
    checkout_status="$(git status --porcelain --untracked-files=all)"
    [ -z "$checkout_status" ] || {
        echo "${DEPLOY_NAME} requires a clean checkout (including untracked files)." >&2; exit 1;
    }
    git fetch origin '+refs/heads/main:refs/remotes/origin/main'
    head_sha="$(git rev-parse HEAD)"
    remote_sha="$(git rev-parse refs/remotes/origin/main)"
    [ "$head_sha" = "$remote_sha" ] || {
        echo "${DEPLOY_NAME} requires HEAD to equal freshly fetched origin/main. Update your checkout." >&2; exit 1;
    }
    if [ -n "${1:-}" ] && [ "$head_sha" != "$1" ]; then
        echo "Checkout commit changed during the build. Run the deployment again." >&2; exit 1;
    fi
}

# Full logical backup, including databases that have no Alembic metadata yet.
backup_database() (
    set -euo pipefail
    local backup_container=$1 user=$2 database=$3 directory=$4 prefix=$5 file
    [ "$(docker inspect -f '{{.State.Running}}' "$backup_container" 2>/dev/null)" = true ] || {
        echo "$backup_container is not running; start the database before deploying." >&2; exit 1;
    }
    umask 077
    mkdir -p "$directory"
    file="$(mktemp "$directory/$prefix-$(date +%Y-%m-%d-%H%M%S)-XXXXXX.dump")"
    trap 'rm -f "$file"' EXIT
    docker exec "$backup_container" pg_dump -U "$user" -Fc "$database" >"$file"
    docker exec -i "$backup_container" pg_restore -l <"$file" >/dev/null
    trap - EXIT
    echo "$file"
)

deploy_app() {
    set -euo pipefail
    candidate_created=0
    old_moved=0
    new_attempted=0
    committed=0
    # shellcheck disable=SC2329 # Invoked by the EXIT trap on the launcher shell.
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
            "${APP_ARGS[@]}" \
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
            elif docker exec "$name" curl --max-time 5 -kfs "https://127.0.0.1:${APP_PORT}/healthcheck" >/dev/null 2>&1; then
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
    start_app "$CONTAINER" --restart unless-stopped -p "$PUBLISH_ADDRESS"
    wait_health "$CONTAINER" published
    committed=1
    if [ "$old_moved" = 1 ]; then
        echo "Previous app retained stopped as $PREVIOUS (remove manually after acceptance)."
    fi
    echo "${DEPLOY_NAME} is up at https://127.0.0.1:${HOST_PORT} (container $CONTAINER, image $IMAGE)."
    echo "Logs: docker logs -f $CONTAINER"
}
