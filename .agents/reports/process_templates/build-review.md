# build-review — process_templates

**Status: inconclusive, not a finding.** Advisory stage (`blocking: false` per
`.agents/model-routing.json`), so this does not gate the chain.

## What happened

Launched via `scripts/agent_launch.py launch build-review --scope process_templates
--prompt-file <prompt> --base proc-template` (herdr-tabs mode, pane `w1A:p2`, Codex
`gpt-5.6-sol`, effort `medium`). The prompt used "Architect/Breaker" framing (echoing
`build-review`'s own `why` field in `model-routing.json`) which inadvertently triggered
Codex's ambient `herdr-multi-agent-collab-breaker` skill — it spent part of its budget
reading that skill's protocol docs and probing `herdr` CLI commands looking for a
handoff file/partner pane that don't exist for this one-shot advisory review, before
moving on to actually reading the diff (registry.py, test_process_templates.py,
service.py, and a repo-wide `org_id = UUID(g.org_id)` grep across backend.py).

The pane reported `idle` (settled) with `scroll.offset_from_bottom: 0` (viewing the
true end of its output), but the transcript ends mid-tool-call (a grep dump) with no
closing summary, no findings list, and no `VERDICT:` line. It did not write this
report file itself (correctly — `access: read` via `--sandbox read-only`, confirmed:
no report file existed after the run). Most likely it exhausted its `medium`-effort
budget partway through a genuinely large diff (~2240 lines, 22 files) after spending
some of that budget on the ambient-skill detour, rather than reaching a real
conclusion.

## Why this doesn't block

`build-review` is deliberately advisory precisely so a Codex hiccup — quota, budget,
or (as here) a prompt that accidentally triggered the wrong ambient skill — cannot
stall an unattended chain. The diff is still covered by: `security-audit` and
`security-tenant-audit` below (blocking, independent Codex/Sonnet passes with
prompts that avoid the "Breaker" trigger word), `test-evaluator` (blocking), and the
27 inline AC tests already green in `tests/test_process_templates.py`.

## Action taken

Noted for the MR description. No code changes made on the strength of this
inconclusive pass — nothing here rose to an actual finding, just an incomplete run.

VERDICT: findings-open (procedural: the stage itself did not complete, not that it found something to fix — treated as advisory/non-blocking per its `blocking: false` routing)
