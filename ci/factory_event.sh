#!/bin/sh
# Report this job's end state to Event Factory, which turns a failing job, a red main or a
# conflicted merge request into agent work (docs/ci-factory-events.md). Runs from every job's
# after_script, where CI_JOB_STATUS is set.
#
# This is the fallback path: GitLab's project webhook already sends Factory every job event.
# It sends only identifiers and the status, authenticated by FACTORY_CI_TOKEN, a masked CI
# variable that can do nothing but ask Factory to look; Factory reads the job from GitLab
# itself before acting. No GitLab credential is sent. Never fails or slows the job: one
# 10-second attempt, every error swallowed. Unset FACTORY_CI_TOKEN to turn it off.

[ -n "${FACTORY_CI_TOKEN:-}" ] || exit 0
[ -n "${CI_JOB_ID:-}" ] && [ -n "${CI_PIPELINE_ID:-}" ] && [ -n "${CI_PROJECT_ID:-}" ] || exit 0

url="${FACTORY_EVENTS_URL:-https://events.biz-e.app/v1/webhooks/gitlab}"
body="{\"project_id\":${CI_PROJECT_ID},\"job_id\":${CI_JOB_ID},\"pipeline_id\":${CI_PIPELINE_ID},\"status\":\"${CI_JOB_STATUS:-unknown}\"}"

if command -v curl >/dev/null 2>&1; then
  printf 'X-Factory-CI-Token: %s\n' "$FACTORY_CI_TOKEN" | curl -sS --max-time 10 -o /dev/null \
    -H @- -H "Content-Type: application/json" --data "$body" "$url" >/dev/null 2>&1
elif command -v python3 >/dev/null 2>&1; then
  python3 - "$url" "$body" <<'PY' >/dev/null 2>&1
import os, sys, urllib.request
request = urllib.request.Request(
    sys.argv[1],
    data=sys.argv[2].encode(),
    headers={"X-Factory-CI-Token": os.environ["FACTORY_CI_TOKEN"], "Content-Type": "application/json"},
)
urllib.request.urlopen(request, timeout=10).read()
PY
elif command -v wget >/dev/null 2>&1; then
  wget -q -T 10 -O /dev/null --header="X-Factory-CI-Token: ${FACTORY_CI_TOKEN}" \
    --header="Content-Type: application/json" --post-data="$body" "$url" >/dev/null 2>&1
fi
exit 0
