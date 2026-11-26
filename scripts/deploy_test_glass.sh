#!/bin/bash
# GLASS PROTOTYPE: deploy branch proto/glass-theme as test-glass.biz-e.app (host port 8003).
#
#   ./scripts/deploy_test_glass.sh            build this checkout and (re)start workflow-engine-test-glass
#
# It is test's twin: same image target, same test.ini, same database and Valkey, same secrets, so the
# same people sign in. The secrets are read from the running workflow-engine-test container (or from
# the job's environment in CI) into a private env file that is removed on exit; nothing is printed.
# It never migrates: the schema belongs to main, and this branch changes no models.
#
# Exit codes: 0 up and healthy; 1 failed before the running glass app was touched; 3 started but unhealthy.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAME=workflow-engine-test-glass
PORT="${GLASS_PORT:-8003}"
IMAGE=workflow-engine:test-glass

ENV_FILE="$(mktemp)"
chmod 600 "$ENV_FILE"
trap 'rm -f "$ENV_FILE"' EXIT
KEYS='^(FLASK_SECRET_KEY|GOOGLE_CLIENT_ID|GOOGLE_CLIENT_SECRET|XERO_CLIENT_ID_TEST|XERO_CLIENT_SECRET_TEST|xero_client_id_test|xero_client_secret_test|POSTGRES_PASSWORD|VALKEY_PASSWORD|POSTHOG_PROJECT_API_KEY)='
if docker inspect workflow-engine-test >/dev/null 2>&1; then
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' workflow-engine-test | grep -E "$KEYS" > "$ENV_FILE" || true
else
    env | grep -E "$KEYS" > "$ENV_FILE" || true
fi
echo "ENVIRONMENT=test" >> "$ENV_FILE"
if ! grep -q '^FLASK_SECRET_KEY=.\{32,\}' "$ENV_FILE"; then
    echo "❌ No FLASK_SECRET_KEY from workflow-engine-test or the environment; nothing was changed."
    exit 1
fi

echo "Building $IMAGE from $(git rev-parse --short HEAD) ..."
docker build --target test -f Dockerfile.multi -t "$IMAGE" .

# Exact-name filter: a substring filter would also match other workflow-engine-test-* containers.
docker stop $(docker ps -aqf "name=^${NAME}$") 2>/dev/null || true
docker rm $(docker ps -aqf "name=^${NAME}$") 2>/dev/null || true

docker run -d --name "$NAME" -p "${PORT}:8001" --network workflow-observability \
    --restart unless-stopped --env-file "$ENV_FILE" \
    --label "glass.commit=$(git rev-parse --short HEAD)" "$IMAGE" >/dev/null

PROBE="import ssl,sys,urllib.request
try:
    r = urllib.request.urlopen('https://127.0.0.1:8001/healthcheck', context=ssl._create_unverified_context(), timeout=5)
    sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)"
for _ in $(seq 1 60); do
    if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != true ]; then break; fi
    if docker exec "$NAME" python -c "$PROBE" >/dev/null 2>&1; then
        echo "✅ $NAME healthy on port $PORT (https://test-glass.biz-e.app)"
        exit 0
    fi
    sleep 2
done
echo "❌ $NAME did not pass its health check. Last log lines:"
docker logs --tail 40 "$NAME" 2>&1 || true
exit 3
