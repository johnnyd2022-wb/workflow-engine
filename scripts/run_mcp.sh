#!/usr/bin/env bash
# Start (or replace) the public MCP server container (bize_mcp, Dockerfile.multi target `mcp`).
#
#   scripts/run_mcp.sh            the TEST server: mcp-test.biz-e.app
#   scripts/run_mcp.sh test       the same, said out loud
#   scripts/run_mcp.sh prod       the PRODUCTION server: mcp.biz-e.app
#
#   target   container                  host port        network                 the app it calls
#   test     workflow-engine-mcp-test   127.0.0.1:8030   workflow-observability  https://workflow-engine-test:8001
#   prod     workflow-engine-mcp        127.0.0.1:8031   workflow-engine-prod    https://workflow-engine-prod:8000
#
# It listens on loopback only; the Cloudflare tunnel connects to it there (terraform/cloudflare).
# It holds no database credentials and no app secrets, so none are passed: the three addresses
# below and one TLS switch are its whole environment. The addresses come from the app's own
# [mcp] section (app/config/<target>.ini), never from the caller's shell, so the resource the
# server advertises is always the one the app binds tokens to.
#
# What it does, in order, stopping at the first failure:
#   1. takes a per-target lock
#   2. gets an image: MCP_IMAGE (already built or pulled by the caller), else it builds the `mcp`
#      target from a `git archive` of MCP_SOURCE_SHA (the commit the caller already verified), else
#      of freshly fetched origin/main (a clean checkout is required, as for run_admin.sh)
#   3. starts a candidate beside the running container (no host port, no restart policy) and
#      health-checks it. A bad candidate is removed and the running container is left alone.
#   4. hands over: the running container is renamed and stopped, the new one takes the name and the
#      port, and is health-checked again. If that fails the previous container is put back.
#
# The health probe is /healthz?deep=1 from INSIDE the container: a CI job runs in a container of
# its own and cannot reach the Docker host's loopback, and "deep" also calls the app's
# /healthcheck, so a wrong app address or TLS setting fails the deploy, not the first assistant.
#
# Exit codes: 0 up; 2 usage; anything else means it failed and the previous container, if there
# was one, is serving again.
set -euo pipefail

TARGET="${1:-test}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
case "$TARGET" in test|prod) ;; *) echo "Usage: scripts/run_mcp.sh [test|prod]" >&2; exit 2 ;; esac

# shellcheck source=scripts/deploy_common.sh
source "$repo_root/scripts/deploy_common.sh"

case "$TARGET" in
test)
    CONTAINER=workflow-engine-mcp-test
    HOST_PORT="${MCP_HOST_PORT:-8030}"
    NETWORK=workflow-observability
    API_BASE_URL=https://workflow-engine-test:8001
    ;;
prod)
    CONTAINER=workflow-engine-mcp
    HOST_PORT="${MCP_HOST_PORT:-8031}"
    NETWORK=workflow-engine-prod
    API_BASE_URL=https://workflow-engine-prod:8000
    ;;
esac
MCP_PORT=8030 # what the image listens on

# ini_value FILE SECTION KEY -> the value of KEY in [SECTION], or nothing.
ini_value() {
    awk -v section="[$2]" -v key="$3" '
        /^[[:space:]]*\[/ { line = $0; gsub(/[[:space:]]/, "", line); in_section = (line == section); next }
        in_section && /^[[:space:]]*[#;]/ { next }
        in_section {
            split($0, kv, "=")
            name = kv[1]; gsub(/[[:space:]]/, "", name)
            if (name == key) {
                value = substr($0, index($0, "=") + 1)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
                print value
                exit
            }
        }' "$1"
}

config_file="app/config/${TARGET}.ini"
PUBLIC_URL="$(ini_value "$config_file" mcp resource)"
ISSUER_URL="$(ini_value "$config_file" mcp issuer)"
[ -n "$PUBLIC_URL" ] && [ -n "$ISSUER_URL" ] || {
    echo "$config_file needs an [mcp] section with issuer and resource." >&2
    exit 1
}

DEPLOY_ENV="mcp-$TARGET"
DEPLOY_NAME="The $TARGET MCP server deploy"
mkdir -p "$HOME/.cache/workflow-engine"
if command -v flock >/dev/null 2>&1; then
    acquire_deploy_lock
else
    echo "Note: flock is not installed here, so concurrent MCP deploys are not locked out." >&2
fi

release="$(date +%s)-$$"
CANDIDATE="$CONTAINER-candidate-$release"
PREVIOUS="$CONTAINER-previous-$release"

echo "== Image"
if [ -n "${MCP_IMAGE:-}" ]; then
    IMAGE="$MCP_IMAGE"
    echo "Using $IMAGE as prepared by the caller."
else
    if [ -n "${MCP_SOURCE_SHA:-}" ]; then
        source_sha="$MCP_SOURCE_SHA" # the caller has already checked this is the reviewed commit
    else
        check_checkout
        source_sha="$(git rev-parse HEAD)"
    fi
    IMAGE="workflow-engine:mcp-$TARGET-$release"
    build_image_from_head mcp "$IMAGE" "$source_sha"
    [ -n "${MCP_SOURCE_SHA:-}" ] || check_checkout "$source_sha"
fi

# Everything the container is told. No secret belongs here; run_mcp.sh's tests pin that.
# BIZE_API_VERIFY_TLS=false: the app serves a self-signed certificate (as every origin does here;
# the tunnel and the health checks skip verification too) under a name it does not cover, and
# this hop never leaves the private Docker network between two containers on this host.
RUN_ARGS=(
    --cap-drop ALL
    --security-opt no-new-privileges:true
    --network "$NETWORK"
    -e "BIZE_API_BASE_URL=$API_BASE_URL"
    -e "MCP_PUBLIC_URL=$PUBLIC_URL"
    -e "BIZE_ISSUER_URL=$ISSUER_URL"
    -e "BIZE_API_VERIFY_TLS=false"
)

candidate_created=0
old_moved=0
new_attempted=0
committed=0
# shellcheck disable=SC2329 # Invoked by the EXIT trap.
cleanup() {
    local result=$?
    trap - EXIT INT TERM
    if [ "$committed" = 0 ]; then
        if [ "$new_attempted" = 1 ]; then
            docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
        fi
        if [ "$old_moved" = 1 ] && docker container inspect "$PREVIOUS" >/dev/null 2>&1; then
            echo "Restoring the previous MCP container." >&2
            if docker rename "$PREVIOUS" "$CONTAINER" && docker start "$CONTAINER" >/dev/null; then
                wait_health "$CONTAINER" || echo "CRITICAL: the previous MCP container failed its health check; manual recovery required." >&2
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

wait_health() {
    local name=$1
    # 60 tries, 2s apart. The tests lower both: each try runs their fake docker.
    for _ in $(seq 1 "${MCP_HEALTH_ATTEMPTS:-60}"); do
        # A container that has exited will never answer; do not wait for it.
        if [ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" != true ]; then
            break
        fi
        if docker exec "$name" curl --max-time 5 -fs "http://127.0.0.1:${MCP_PORT}/healthz?deep=1" >/dev/null 2>&1; then
            return 0
        fi
        sleep "${MCP_HEALTH_INTERVAL:-2}"
    done
    echo "$name did not pass its health check. Last log lines:" >&2
    docker logs --tail 40 "$name" >&2 || true
    return 1
}

start_container() {
    local name=$1
    shift
    docker run -d --name "$name" "$@" "${RUN_ARGS[@]}" "$IMAGE" >/dev/null
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "== Candidate (the running container stays up)"
# Last deploy's stopped container is no longer needed once this one is being replaced.
for stale in $(docker ps -aq --filter "name=^${CONTAINER}-previous-"); do
    docker rm -f "$stale" >/dev/null 2>&1 || true
done
candidate_created=1
# No host port and no restart policy: a failed candidate can never take over traffic.
start_container "$CANDIDATE"
wait_health "$CANDIDATE"
docker rm -f "$CANDIDATE" >/dev/null
candidate_created=0

echo "== Handover ($TARGET)"
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    # Record intent first: a signal may land after Docker renames it but before the command
    # returns. Cleanup checks whether PREVIOUS exists.
    old_moved=1
    docker rename "$CONTAINER" "$PREVIOUS"
    docker stop "$PREVIOUS" >/dev/null
fi
new_attempted=1
start_container "$CONTAINER" --restart unless-stopped -p "127.0.0.1:${HOST_PORT}:${MCP_PORT}"
wait_health "$CONTAINER"
committed=1
if [ "$old_moved" = 1 ]; then
    echo "Previous MCP container retained stopped as $PREVIOUS (cleared by the next deploy)."
fi
echo "The $TARGET MCP server is up at http://127.0.0.1:${HOST_PORT} (container $CONTAINER, image $IMAGE), public at $PUBLIC_URL."
echo "Logs: docker logs -f $CONTAINER"
