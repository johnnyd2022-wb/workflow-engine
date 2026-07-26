# SECURITY-TENANT-AUDIT: dilution_calculator (Codex re-run)
date: 2026-07-26
engine: codex (gpt-5.6-sol, effort=high, sandbox=read-only) — genuinely independent, per
`.agents/model-routing.json`'s designated engine for this stage
verdict: clean

## Why this report exists

MR !131's original `security-tenant-audit.md` disclosed that it ran on a Claude fallback
because Codex was unavailable in that environment (`preflight.py` reported
`grader_engine: claude` at build time). Codex is available now. This is that stage re-run
for real, on the actual designated engine, as an independent second reader distinct from
whoever authored the build — not a rubber-stamp of the prior report's conclusion.

## Method

Codex was launched via the established mechanism (`scripts/agent_launch.py`'s
`launch()`/`build_command()`, `--sandbox read-only` per this stage's `access: "read"` in
model-routing.json), in a live Herdr pane, cwd set to the `feat/dilution_calculator`
worktree. It read the actual route, service, and template code directly rather than being
told the prior conclusion and asked to confirm it — the prompt explicitly instructed it not
to defer to the existing report.

## Finding

No tenant-scoped surface exists to audit. Verbatim from the agent's own final message:

> The independent code review found no tenant-owned resource or tenant-scoped query
> surface: there are only two authenticated routes, one template render, and one
> request-to-pure-function calculation path. No lookup accepts an object ID, so neither
> `(id, org_id)` filtering nor a cross-tenant 404 response can arise; under the skill's
> wording, the required two-org test applies per scoped model, and this feature has none.

This matches the prior Claude-fallback report's conclusion, but arrived at independently —
by reading `app/features/dilution_calculator/routes/api_routes.py`,
`routes/page_routes.py`, `services/dilution_service.py`, and the template directly, not by
trusting the earlier report.

## A genuine gap this run surfaced, distinct from the audit's own verdict

This stage's read-only sandbox (`--sandbox read-only`, correct per
`.agents/model-routing.json` and the "graders are read-only, by construction" principle in
`.agents/verification-chain.md` §3) blocks the grader from writing its own report file —
confirmed live: `codex_core::tools::router: error=patch rejected: writing is blocked by
read-only sandbox`. The grader recognized this itself and declined to work around it
("I will not delegate or alter the audit conclusion"), correctly treating the write
restriction as intentional rather than a bug to route around.

**This is not a permissions bug to fix by loosening the sandbox.** Granting a grader write
access to produce its own report would also grant it write access to the code it is
grading, which is exactly the guarantee `agent_launch.py --check` exists to enforce. The
correct fix is procedural: the orchestrator (the write-capable Claude session driving the
stage) is responsible for capturing a read-only grader's final verdict and materializing
this report file on its behalf — which is what produced this file. Worth adding as an
explicit line in `.agents/verification-chain.md` §5 so the next orchestrator doesn't have
to rediscover this live.

## Verdict

VERDICT: clean
