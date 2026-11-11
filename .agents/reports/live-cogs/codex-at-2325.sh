#!/bin/bash
# Launch the Codex jobs that hit Codex's usage limit, once it resets (11:23 PM NZ).
target=$(date -d "23:25" +%s); now=$(date +%s); [ $target -gt $now ] && sleep $((target-now))
cd /home/johnny/workflow-engine
launch() {  # $1 stage, $2 scope, $3 prompt, $4 report
  before=$(ls -t ~/.codex/sessions/2026/11/11/*.jsonl | head -1)
  python3 scripts/agent_launch.py launch "$1" --scope "$2" --prompt-file "$3" >/dev/null 2>&1
  for i in $(seq 1 40); do f=$(ls -t ~/.codex/sessions/2026/11/*/*.jsonl | head -1); [ "$f" != "$before" ] && break; sleep 3; done
  for i in $(seq 1 240); do tail -1 "$f" | grep -q '"task_complete"' && break; sleep 15; done
  tail -1 "$f" | python3 -c "import sys,json; p=json.loads(sys.stdin.read())['payload']; print(p.get('last_agent_message') or ('ERROR: '+str(p.get('error'))))" > "$4"
}
launch security-tenant-audit live-cogs-8.1b /home/johnny/wt-live-cogs-xero/.agents/reports/live-cogs/audit-8.1b.prompt.md /home/johnny/wt-live-cogs-xero/.agents/reports/live-cogs/audit-8.1b.md &
sleep 60
launch build-review live-cogs-8.1c1 /home/johnny/wt-live-cogs-alloc/.agents/reports/live-cogs/review-8.1c1-r2.prompt.md /home/johnny/wt-live-cogs-alloc/.agents/reports/live-cogs/review-8.1c1-r2.md &
wait
tail -1 /home/johnny/wt-live-cogs-xero/.agents/reports/live-cogs/audit-8.1b.md
tail -1 /home/johnny/wt-live-cogs-alloc/.agents/reports/live-cogs/review-8.1c1-r2.md
