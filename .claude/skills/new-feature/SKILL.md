---
name: new-feature
description: "End-to-end orchestrator for building a new feature in the Flask app: interviews the user for name and details, creates the blueprint, builds to spec with unit tests, then drives the verification chain (migration-safety, security-audit, e2e-playwright, observability, ci-gate) via subagents until every gate is green. Use this skill whenever the user asks to build, add, or create a feature, endpoint, page, or capability, even if they don't say 'new feature'. This is the front door for feature work; individual skills are the rooms."
---

# New Feature

You are the orchestrator. You interview, scaffold, build, then delegate verification to subagents running the specialist skills, and you do not declare the feature done until every gate reports green. The chain and its order exist for a reason: each stage consumes the previous stage's artifact, and verification is done by agents that did not write the code.

Read `.agents/autonomy.md` before starting. In an unattended run the MR is the gate: build to a reviewable MR with assumptions surfaced rather than stopping to ask.

## The chain

```
0. preflight           (script, ~3s)             -> capabilities + decisions
1. spec-first          (inline, interactive)     -> .agents/specs/<slug>.md [approved]
2. scaffold + build    (this agent / Architect)  -> blueprint + unit tests passing
3. migration-safety    (subagent, only if spec says data model changes)
4. security-audit      (subagent)  \  parallel after build is green
   e2e-playwright      (subagent)  /
4b. perf-guardrails    (subagent, only if the spec touches a page/API route: measure
                        budgets on the touched routes after e2e passes)
5. observability       (subagent)
6. ci-gate verify      (subagent, always last)
7. patch loop          (back to 2 with findings; max 2 rounds, then escalate)
```

Skill locations: resolve each skill's SKILL.md from the installed skills directories before spawning; pass the absolute path to the subagent.

## Step 0: Preflight (once, then pass it down)

```bash
python3 scripts/preflight.py --json
```

Repair blockers per the **preflight** skill's table, then read `decisions`: `verification_mode` (`herdr-adversarial` | `subagents`) settles how steps 3-6 run, and `live_server_tests` tells you whether the live suites will run or skip. Pass the report to subagents in their prompt instead of having each re-probe — one environment, one opinion about it.

## Step 1: Spec (inline, never delegated)

Run the **spec-first** skill yourself; it interviews the user, and subagents cannot talk to the user. Do not proceed past this step until the spec file exists with `status: approved` — or, in an unattended run, `status: approved-unattended` with its assumptions listed (see spec-first §3; those assumptions must lead the MR description). The slug from the spec drives everything downstream.

## Step 2: Scaffold and build

Read `.agents/conventions.md` first (owned by the **repo-conventions** skill) — it is
evidence-based and supersedes the shape below wherever the two disagree. As of this
writing, this repo's real pattern is subdirectories per concern, not flat files:

```
app/features/<slug>/
  routes/            # api_routes.py, page_routes.py — thin, one Blueprint each
  services/          # <slug>_service.py — business logic, no Flask imports
  repositories/      # <name>_repo.py — one per model, org_id explicit on every method
  models/            # one file per SQLAlchemy model, only if spec's data model says changes
  frontend/          # templates/, css/, js/ if the feature has UI
tests/test_<slug>.py  # flat, alongside the rest of tests/ — no tests/unit|integration split
```

Use the **test-fixtures** skill's factories (`tests/factories.py`) and
`two_org_two_user` fixture (`tests/conftest.py`) for any org/user test data instead of
hand-seeding; add a new factory there if the spec introduces a model nothing seeds yet.

Register the blueprint in the app factory. Then build to the spec:

- Every route carries `@requires_auth`; every tenant-scoped repository method takes
  `org_id` explicitly and filters inline (`Model.query.filter(Model.org_id == org_id)`)
  from the first line, not patched in later. The security audit will check this; write
  it so the audit is boring.
- Unit tests named to ACs (`test_ac1_...`), one per criterion minimum, plus the unhappy paths. Run until green: `uv run pytest tests/test_<slug>.py -v`. (Run pytest with `ENVIRONMENT` unset — it resolves to local, which points at the test DB on `localhost:8401`. `ENVIRONMENT=test` hangs from a host shell; see preflight's `test_db` check.) A failure that never reached an assertion — connection error, missing service — is **suite-warden**'s, not a bug in your build. These inline AC tests are graded by **test-evaluator** in the chain below before the MR — write them to be falsifiable (each would go red if its AC broke), not merely green.
- Log state changes per the observability event convention (`<slug>.<verb_past>`); it is cheaper to emit them now than to retrofit in step 5.
- Commit on a feature branch `feat/<slug>`. Verification agents audit the tree, not your intentions.

**If running inside Herdr with a Codex pane** (`HERDR_ENV=1` and a partner exists): route the verification stages below through the herdr-multi-agent-collab protocol instead of spawning subagents. Claude stays Architect (builds, patches findings); Codex-as-Breaker runs the verification stages in its own pane per its Workflow A, reporting findings back via the handoff file, with the protocol's two-round circuit breaker in place of step 7's. Otherwise use subagents as described; the chain is identical either way.

## Steps 3-6: Verification by subagents

Spawn each verification stage as a subagent whose prompt follows this template. Fresh eyes are the point: the subagent gets the spec and the skill, not your reasoning or excuses.

```
Read and follow the skill at: <absolute path to SKILL.md>
Feature slug: <slug>
Spec: .agents/specs/<slug>.md
Branch: feat/<slug>
Task: <one line, e.g. "Audit this feature per the skill and write your report">
Write your report to .agents/reports/<slug>/<stage>.md and end your reply with
exactly one line: VERDICT: clean | patched | findings-open
```

Sequencing rules:
- **migration-safety** runs before security/e2e whenever the spec's data model section says changes (both need a migratable schema to test against). Skip it, and say you skipped it, when the spec says `changes: none`.
- **security-audit** and **e2e-playwright** are independent; spawn them in the same turn so they run in parallel.
- **observability** runs after those pass, instrumenting anything the build missed.
- **test-author** runs after observability: it reconciles the *rest* of the suite against this feature's diff (tests in other areas the change rippled into) and refreshes `.agents/test-map.md` — the build wrote this feature's own tests; this stage catches what those tests didn't know they touched.
- **test-evaluator** grades every new or changed test in the diff (this feature's inline AC tests plus anything test-author added) for validity — falsifiability, no silently-widened assertions, no tautologies. Its verdict must be `valid` before ci-gate; treat `weakened`/`gamed`/`inconclusive` as a `findings-open` returned to you.
- **ci-gate** in verify mode is always last, because it checks that everything the other stages produced (tests, rules, migrations) is actually collected and enforced. Parse its `GATE <name>: pass|fail` lines.

Read each subagent's report file, not just its verdict line. A `patched` verdict means code changed: re-run the unit suite before moving on, since one stage's patch can break another's assumptions.

## Step 7: Patch loop and circuit breaker

`findings-open` from any stage comes back to you: fix (that is builder work), then re-run only the failed stage plus ci-gate. Track rounds in `.agents/reports/<slug>/rounds.md`. If the same finding survives **two full rounds**, stop, write up what was tried and your best hypotheses, and escalate to the user. Grinding a third round on the same wall burns tokens and usually means the spec or the design is wrong, which is a human decision.

## Step 8: Done means demonstrated

Confirm true before proceeding: spec approved, unit tests green with AC coverage, migrations up/down/up verified (or none), security verdict clean/patched, E2E green and flake-checked, observability instrumented, test-map reconciled and **test-evaluator verdict `valid`**, all ci gates passing. Set the spec's `status: built`. Then call the **merge-request** skill to write the MR from the spec and stage reports, push, open it, and watch the pipeline — do not assemble the MR description yourself. Present the summary as a short table of stage -> verdict -> report path, then the MR link merge-request returns.

**Record the run** (`.agents/autonomy.md` → Measure yourself). Append one metrics row per verification stage that ran, using its report verdict and finding count, so the scorecard can see this chain's shape:

```bash
python scripts/skill_metrics.py record --skill <stage> --run-type chained \
  --scope <slug> --verdict <clean|patched|findings-open> --findings <n> --ref feat/<slug>
```

Do this for the stages you drove (security-audit, e2e-playwright, perf-guardrails, etc.). The MR's eventual merge/close is recorded later as an `outcome` on the same `--ref feat/<slug>` — not now.

## Rules

- Never skip a stage silently. Skips are stated with reasons ("no data model changes, migration-safety skipped").
- Never weaken a gate to get green; that rule from ci-gate binds the orchestrator hardest of all, because you have the motive.
- If the user asks for "just a quick feature, skip the checks", comply with what they explicitly waive, record the waived stages in the report, and keep spec + unit tests as the floor you argue for.
