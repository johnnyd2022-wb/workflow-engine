# biz-e agentic skill suite

Eight skills. Two are front doors, six are specialists. Everything communicates through files under `.agents/` so any agent (or human) can reconstruct state.

## Call graph

```
new-feature ──┬─ spec-first            (inline, interviews you)
              ├─ build + unit tests    (inline / Herdr Architect)
              ├─ migration-safety      (subagent, if models change)
              ├─ security-audit        (subagent) ─┐ parallel
              ├─ e2e-playwright        (subagent) ─┘
              ├─ observability         (subagent)
              └─ ci-gate [verify]      (subagent, always last)

review-feature ─ same chain, minus the interview, plus spec
                 reconstruction, unit-coverage gap-fill, and a
                 patch loop on existing code
```

Both orchestrators use the herdr-multi-agent-collab skills instead of subagents when running inside Herdr with a Codex pane: Architect builds, Breaker takes the verification stages.

## Shared conventions

- `.agents/specs/<slug>.md` - the spec, single source of truth, AC IDs drive test names
- `.agents/reports/<slug>/` - one report per stage: security.md, e2e.md, migrations.md, observability.md, review.md, rounds.md
- `.semgrep/` - custom rules; every manually-found vuln class becomes a rule
- Subagent contract: each stage ends with `VERDICT: clean | patched | findings-open`
- ci-gate contract: `GATE <name>: pass|fail` lines
- Circuit breaker everywhere: same finding survives 2 rounds -> escalate to human
- Gates are append-only: weakening any check requires explicit human approval

## Install

Copy each folder into your skills directory (Claude Code: `.claude/skills/` or `~/.claude/skills/`; Codex: `.codex/skills/`). Stack assumptions baked in: GitLab CI, PostgreSQL, Alembic, ruff, semgrep, pytest.. The herdr collab skills from earlier live alongside these.

## Build order for the repo itself

1. ci-gate first (foundation; everything else registers checks into it)
2. spec-first + new-feature (start building features through the front door)
3. security-audit, e2e-playwright, migration-safety, observability as new-feature calls them
4. review-feature to bring pre-existing blueprints up to standard, one at a time
