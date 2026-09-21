#!/usr/bin/env bash
# Rebuild the disposable Whistlebird Ltd replay tenant from the committed manifests.
#
# Prerequisites:
#   * `uv sync --extra dev` has been run;
#   * the local app is reachable at https://localhost:8001 (override with
#     WHISTLEBIRD_REPLAY_BASE_URL); and
#   * KeePassXC is available, unless WHISTLEBIRD_ADMIN_PASSWORD is exported.
#
# The target database URL is derived from app/config/local.ini, so no password
# needs to be copied into a shell command. This is intentionally destructive to
# Whistlebird Ltd only: it resets that tenant and recreates it from version control.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/replay_whistlebird.sh --confirm [--discard-unsnapshotted-np3]

Rebuild Whistlebird Ltd through the local API using the committed replay manifests.

Required:
  --confirm                       Reset and rebuild the Whistlebird Ltd tenant.

Optional:
  --discard-unsnapshotted-np3     Discard NP3 evidence entered in the app but not
                                  yet saved to its committed manifest.
  --help                          Show this help.

Environment overrides:
  WHISTLEBIRD_REPLAY_BASE_URL     App endpoint (default: https://localhost:8001).
  WHISTLEBIRD_REPLAY_INSECURE     Set to 0 to verify the app TLS certificate.
  BIZE_MIGRATION_DATABASE_URL     Target database URL. By default it is derived
                                  from the local app configuration.
  WHISTLEBIRD_ADMIN_PASSWORD      Admin password. If unset, the established
                                  KeePassXC entry is used by the rebuild script.

Example:
  scripts/replay_whistlebird.sh --confirm
EOF
}

confirm=0
discard_unsnapshotted_np3=0
for argument in "$@"; do
    case "$argument" in
        --confirm) confirm=1 ;;
        --discard-unsnapshotted-np3) discard_unsnapshotted_np3=1 ;;
        --help|-h) usage; exit 0 ;;
        *)
            printf 'Unknown argument: %s\n\n' "$argument" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$confirm" -ne 1 ]]; then
    printf 'Refusing to reset Whistlebird Ltd without --confirm.\n\n' >&2
    usage >&2
    exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export ENVIRONMENT="${ENVIRONMENT:-local}"
export WHISTLEBIRD_REPLAY_BASE_URL="${WHISTLEBIRD_REPLAY_BASE_URL:-https://localhost:8001}"
export WHISTLEBIRD_REPLAY_INSECURE="${WHISTLEBIRD_REPLAY_INSECURE:-1}"

if [[ -z "${BIZE_MIGRATION_DATABASE_URL:-}" ]]; then
    BIZE_MIGRATION_DATABASE_URL="$(uv run python - <<'PY' 2>/dev/null | tail -n 1
from sqlalchemy.engine import URL

from app.utils.config_loader import config

print(
    URL.create(
        "postgresql+psycopg2",
        username=config.db_user,
        password=config.db_password,
        host=config.db_host,
        port=config.db_port,
        database=config.db_name,
    ).render_as_string(hide_password=False)
)
PY
)"
    export BIZE_MIGRATION_DATABASE_URL
fi

arguments=(
    --base-url "$WHISTLEBIRD_REPLAY_BASE_URL"
    --confirm-reset-whistlebird-ltd
)
if [[ "$WHISTLEBIRD_REPLAY_INSECURE" == "1" ]]; then
    arguments+=(--insecure)
fi
if [[ "$discard_unsnapshotted_np3" -eq 1 ]]; then
    arguments+=(--discard-unsnapshotted-np3)
fi

exec uv run python scripts/whistlebird_rebuild_api.py "${arguments[@]}"
