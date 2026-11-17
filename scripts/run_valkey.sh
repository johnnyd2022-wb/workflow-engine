#!/usr/bin/env bash
# The shared Valkey beside an app (design review S4): rate-limit counts every gunicorn worker and the
# MCP server share. Named generically: it may get other uses.
#
#   scripts/run_valkey.sh            the TEST instance (valkey-test)
#   scripts/run_valkey.sh test       the same, said out loud
#   scripts/run_valkey.sh prod       the PRODUCTION instance (valkey-prod)
#
#   target   container     network                  volume            password
#   test     valkey-test   workflow-observability   valkey-test-data  VALKEY_PASSWORD, else VALKEY_PASSWORD_TEST,
#                                                                     else KeePassXC workflow-engine/VALKEY_PASSWORD_TEST
#   prod     valkey-prod   workflow-engine-prod     valkey-prod-data  VALKEY_PASSWORD, else KeePassXC via
#                                                                     scripts/prod_secrets.py (VALKEY_PASSWORD_PROD)
#
# The app reaches it as redis://:<password>@valkey-<target>:6379/0 on the app's Docker network. No port
# is published, not even on loopback. The password reaches the container by name in the environment
# (REDISCLI_AUTH, which valkey-cli also reads, so the health check never names it), never on a command
# line, and this script never prints it.
#
# Idempotent: a running instance that answers PING with this password is left alone; a stopped one is
# started; a missing one is created. Nothing here removes a container or a volume. A running instance
# with a different password is an error (rotate deliberately: see docs/production-deploy.md).
#
# Exit codes: 0 up; 1 failed; 2 usage.
set -euo pipefail

TARGET="${1:-test}"
IMAGE=valkey/valkey:9.1.3 # exact release, 2026-10-27; bump deliberately (tests pin it against CI)
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$TARGET" in
test)
    CONTAINER=valkey-test
    NETWORK=workflow-observability
    VOLUME=valkey-test-data
    ;;
prod)
    CONTAINER=valkey-prod
    NETWORK=workflow-engine-prod
    VOLUME=valkey-prod-data
    ;;
*)
    echo "Usage: scripts/run_valkey.sh [test|prod]" >&2
    exit 2
    ;;
esac

# For a throwaway rehearsal only (never for the real instances): VALKEY_CONTAINER, VALKEY_NETWORK and
# VALKEY_VOLUME override the three names above.
CONTAINER="${VALKEY_CONTAINER:-$CONTAINER}"
NETWORK="${VALKEY_NETWORK:-$NETWORK}"
VOLUME="${VALKEY_VOLUME:-$VOLUME}"

# shellcheck source=scripts/deploy_common.sh
source "$repo_root/scripts/deploy_common.sh"
resolve_valkey_password "$TARGET"
[ -n "${VALKEY_PASSWORD:-}" ] || {
    echo "No VALKEY_PASSWORD for $TARGET: set it, or add the KeePassXC entry (docs/production-deploy.md)." >&2
    exit 1
}
export REDISCLI_AUTH="$VALKEY_PASSWORD"

# ping_reply -> what PING answers with the current password (empty when nothing answers).
ping_reply() {
    docker exec -e REDISCLI_AUTH "$CONTAINER" valkey-cli --no-auth-warning ping 2>/dev/null || true
}

wait_ready() {
    local reply=""
    for _ in $(seq 1 "${VALKEY_HEALTH_ATTEMPTS:-30}"); do
        reply="$(ping_reply)"
        case "$reply" in
        PONG) return 0 ;;
        *WRONGPASS* | *NOAUTH* | *"AUTH failed"*)
            echo "$CONTAINER is running with a different password than VALKEY_PASSWORD. It was left as it is;" >&2
            echo "see 'Rotating the Valkey password' in docs/production-deploy.md." >&2
            return 1
            ;;
        esac
        sleep "${VALKEY_HEALTH_INTERVAL:-1}"
    done
    echo "$CONTAINER did not answer PING. Last log lines:" >&2
    docker logs --tail 20 "$CONTAINER" >&2 || true
    return 1
}

docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = true ]; then
        wait_ready
        echo "$CONTAINER is already up (network $NETWORK)."
        exit 0
    fi
    docker start "$CONTAINER" >/dev/null
    wait_ready
    echo "Started $CONTAINER (network $NETWORK)."
    exit 0
fi

docker volume create "$VOLUME" >/dev/null
# Persistence is Valkey's default RDB snapshots in /data, on the named volume. The password is read
# from the container's own environment by the shell inside it, so it is never in any argv here.
docker run -d --name "$CONTAINER" --restart unless-stopped \
    --network "$NETWORK" \
    --security-opt no-new-privileges:true \
    -v "$VOLUME:/data" \
    -e REDISCLI_AUTH \
    --health-cmd 'valkey-cli --no-auth-warning ping | grep -q PONG' \
    --health-interval 10s --health-timeout 3s --health-retries 3 \
    "$IMAGE" \
    sh -c 'exec valkey-server --requirepass "$REDISCLI_AUTH"' >/dev/null
wait_ready
echo "Created $CONTAINER from $IMAGE (network $NETWORK, volume $VOLUME, no published port)."
