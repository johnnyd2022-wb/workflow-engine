# SETUP & BUILD BRIEF — read this first, Claude

You are Claude (Claude Code or Cowork) working in Johnny's environment. This zip contains
skills built in a prior session plus this brief. Your job, in order: (1) install the built
skills to the right locations, (2) build the remaining "doing work" skills listed below,
cross-referencing the existing agents pack so nothing overlaps and everything hands off
cleanly. Ask before overwriting anything that already exists.

The existing agents pack lives in Johnny's `agents/` directory (15 role skills under
`agents/skills/`, shared context under `agents/context/`, state under `agents/projects/`).
Read `agents/skills/*/SKILL.md` frontmatter + `context/operating-principles.md` before
building anything — the overlap notes below were checked against that pack on 12 Jul 2026,
but the pack is the live source of truth.

---

## PART 1 — Install (do this first)

| What | From (this zip) | Install to |
|---|---|---|
| Herdr collab, Claude side | 1-herdr-collab/claude-side/herdr-multi-agent-collab/ | `~/.claude/skills/` (global) or repo `.claude/skills/` |
| Herdr collab, Codex side | 1-herdr-collab/codex-side/herdr-multi-agent-collab-breaker/ | `~/.codex/skills/` or repo `.codex/skills/` |
| biz-e code suite (8 skills) | 2-bize-code-suite/* (skip README.md) | biz-e repo `.claude/skills/` |
| licence-study-coach | 3-whistlebird-licence/licence-study-coach/ | agents pack: `agents/skills/licence-study-coach/` |

Post-install steps:
- licence-study-coach: create `agents/projects/whistlebird/LICENCE_STUDY.md` from its
  `templates/study-progress.md`; add a study row to `projects/whistlebird/ACTIVE_PROJECTS.md`.
- biz-e: run `ci-gate` bare against the repo (it self-discovers DB config from `app/config/`).
  Remind Johnny of the one human-only step: protected branch + "Pipelines must succeed"
  merge check in GitLab, or every gate is decorative.
- Herdr: suggest one seeded round-trip test on a deliberate bug before real work.

## PART 2 — Build: biz-e "doing work" skills (in this order)

These complete the code suite. Read the installed suite first and honor its contracts:
`.agents/` layout, `VERDICT: clean|patched|findings-open` final lines,
`GATE <name>: pass|fail`, the 2-round circuit breaker, gates are append-only.

1. **repo-conventions** — extract patterns from the 3 best existing blueprints as rules
   with file:line references (auth decorator, scoped-query helper, schema style, naming,
   where utilities live). Owns `.agents/conventions.md`. Every builder reads it first;
   new-feature appends one lesson per shipped feature. Build from evidence in the repo,
   never from summary. Cross-ref: complements `cto-software-architect` (which owns ADRs /
   architecture decisions); conventions.md is code-level style+patterns — link to ADRs,
   don't duplicate them.
2. **test-fixtures** — owns factory-boy factories and the seeded two-org/two-user world
   that e2e-playwright and security-audit currently assume exists. Single source for
   test data; both verification skills get pointed at it.
3. **fix-bug** — third front door beside new-feature/review-feature. Flow: observability
   triage → write the failing repro test FIRST (prove it red) → fix → run the relevant
   chain subset → merge-request. No overlap in either pack.
4. **merge-request** — the last mile for all three front doors. Writes the MR description
   from spec + stage reports (ACs linked to tests), watches the pipeline via `glab`,
   handles rebase conflicts, responds to review threads. When built, wire it in: add it
   as the final step of new-feature, review-feature, and fix-bug (one-line edits).
5. **release-deploy** — ⚠ OVERLAP: the agents pack already has `release-manager`
   (pre-release checklist, release notes, changelog, marketing/sales handoffs). Do NOT
   duplicate. Build only the technical half it lacks — tag, deploy job, post-deploy smoke
   (reuse the e2e suite), rehearsed rollback — and hand off to release-manager for
   notes/changelog/downstream comms. Name it `deploy-runner` to keep ownership obvious.
6. **dependency-update** — consumes pip-audit findings + routine bumps: upgrade, read
   changelog for breaking changes, run chain subset, merge-request. No overlap.

## PART 3 — Build: business-ops skills (cross-referenced against the agents pack)

Rules for all of these: draft-never-send (founder owns every send/post), report files as
state so `business-operator` can orchestrate, match the pack's SKILL.md conventions
(business/owns/triggers frontmatter, ownership boundaries, handoffs).

DO NOT BUILD (already owned by the pack — extend instead):
- ~~voice-guide~~ → `context/brand-bize.md`, `context/brand-whistlebird.md`, and
  `content-producer` already own voice. If drafts still sound like AI, tighten those
  context files (add banned-phrase list + 3 real writing samples per brand).
- ~~Monday brief~~ → `business-operator` owns the Weekly Command Centre. Instead, teach
  it to read the new report files the skills below produce (one Handoffs edit).
- ~~follow-up chaser / prospect prep~~ → `sales-manager` owns follow-ups and outreach,
  and Johnny already runs a daily sales-inbox drafting skill. Extend sales-manager with:
  a daily stalled-thread scan (quiet 4+ days → drafted nudge) and a pre-call prospect
  prep section. Extension, not a new skill.

BUILD (genuine gaps):
1. **community-triage** — daily scan of target subreddits for threads matching the biz-e
   angles; score fit, flag sub-rule risks, draft replies for the top 2–3 via
   content-producer's voice sources; log to the existing marketing command-centre
   workflow. Hard rules: skip threads requesting unsupported capabilities (or engage
   with no product mention); trust-sensitive communities (Society of Spirits Discord)
   permanently out of scope — human-only. Hands off to `marketing-director` for strategy,
   `content-producer` for drafting standards.
2. **discovery-synthesis** — after each demo/discovery call: transcript in → pains,
   objections (feed `sales-manager/objection-handling/`), feature asks (feed
   `bize-product-manager`), verbatim quotes appended to a running insight file. The
   cross-feeding into TWO existing skills is why this is its own skill, not part of either.
3. **competitor-watch** — weekly (not daily) diff of competitor pricing pages, changelogs,
   reviews → short digest to `marketing-director` and `bize-product-manager`. No overlap.

## PART 4 — Status ledger

| Item | Status |
|---|---|
| Herdr collab pair | **installed** (`.claude/skills/herdr-multi-agent-collab`, `.codex/skills/herdr-multi-agent-collab-breaker`) — still untested live, seeded round trip not run this session |
| biz-e code suite (8) | **installed** into `.claude/skills/`; ci-gate run bare against the repo (see below) — first *feature* run through new-feature/review-feature/fix-bug still pending |
| licence-study-coach | **installed**, `LICENCE_STUDY.md` created, `ACTIVE_PROJECTS.md` row added — usable immediately; grow bank after HPA guide + DLC sample PDFs are read |
| Part 2 skills (6) | **built**: repo-conventions (+ `.agents/conventions.md` from real evidence), test-fixtures (+ real `tests/conftest.py`/`tests/factories.py`, factory-boy added as dev dep), fix-bug, merge-request (wired into new-feature/review-feature/fix-bug), deploy-runner, dependency-update |
| Part 3 skills (3 + 2 extensions) | **built**: community-triage, discovery-synthesis, competitor-watch; sales-manager extended (daily stalled-thread scan, pre-call prep); business-operator extended (reads the new report files) |
| ci-gate bare run | **done** — see `.agents/ci-gate-setup.md`: added `gitleaks`, `pip_audit`, `migration_reversibility` jobs to the existing `.gitlab-ci.yml` (additive only, nothing pre-existing changed); extended `.pre-commit-config.yaml` to match |
| GitLab branch protection | human-only step, still pending — nothing above is actually merge-blocking until this happens |

## Discrepancies found this session, flagged rather than silently resolved

1. **`g.org_id` vs `g.current_org_id` duplication** and **`requires_org_scope` barely
   used outside `org_routes.py`** — real, pre-existing pattern, not a bug. Documented in
   `.agents/conventions.md` §3 with recommendation (prefer `g.current_org_id` for new
   code) but not mechanically migrated across 95 call sites — that's a judgment call for
   you, not something to silently do mid-brief.
2. **`ruff` CI job runs `--fix` (mutating) instead of `--check`** — existing,
   merge-blocking job I did not change without sign-off. See
   `.agents/ci-gate-setup.md` item 1.
3. **`new-feature`'s original scaffold** (flat `routes.py`/`service.py`/`schemas.py`,
   `tests/unit/<slug>/`) **didn't match this repo's real layout** (subdirectories per
   concern, flat `tests/test_<slug>.py`, no `requirements.txt`/pip — `uv`/`pyproject.toml`).
   Corrected in `new-feature`, `review-feature`, `security-audit`, `e2e-playwright`,
   `observability` where they had the same stale assumption (Sentry mentioned but not
   used here — this repo already runs structlog + OTel + Grafana LGTM + PostHog).
4. **`/home/johnny/biz-e` is a different, unrelated repo** (React/Supabase, GitLab
   `biz-e/biz-e`) from this one (`workflow-engine`, GitLab `whistlebird/workflow-engine`).
   This brief's "biz-e repo" instructions were executed against **this** repo — it's the
   one matching the ci-gate/new-feature skills' stack assumptions (Flask/SQLAlchemy/
   Postgres/Alembic) and the one this session was invoked in. Flagging in case that
   wasn't the intended target.
5. **Test DB connectivity** (`host.docker.internal`) was unreachable from this session's
   sandbox — confirmed pre-existing/environmental by reproducing the identical failure
   on an already-passing test, not caused by anything built this session. The new
   `tests/conftest.py`/`tests/factories.py` are verified by import/syntax/ruff only; run
   `ENVIRONMENT=test uv run pytest tests/ -v` in a normal dev environment to confirm the
   live round trip.

Cross-cutting rule for everything you build: read the target repo / the agents pack
first and write from evidence; where this brief and the live pack disagree, the pack
wins — flag the discrepancy to Johnny rather than silently choosing.
