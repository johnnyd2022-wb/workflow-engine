#!/bin/bash
target=$(date -d "23:30" +%s); now=$(date +%s); [ $target -gt $now ] && sleep $((target-now))
cd /home/johnny/workflow-engine
before=$(ls -t ~/.codex/sessions/2026/11/*/*.jsonl | head -1)
python3 scripts/agent_launch.py launch build-review --scope live-cogs-8.1c2 --prompt-file /home/johnny/wt-live-cogs-rules/.agents/reports/live-cogs/review-8.1c2-r1.prompt.md >/dev/null 2>&1
for i in $(seq 1 40); do f=$(ls -t ~/.codex/sessions/2026/11/*/*.jsonl | head -1); [ "$f" != "$before" ] && break; sleep 3; done
for i in $(seq 1 240); do tail -1 "$f" | grep -q '"task_complete"' && break; sleep 15; done
tail -1 "$f" | python3 -c "import sys,json; p=json.loads(sys.stdin.read())['payload']; print(p.get('last_agent_message') or ('ERROR: '+str(p.get('error'))))" > /home/johnny/wt-live-cogs-rules/.agents/reports/live-cogs/review-8.1c2-r1.md
