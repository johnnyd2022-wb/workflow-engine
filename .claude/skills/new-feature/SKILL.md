---
name: new-feature
description: "End-to-end orchestrator for building a new feature in the Flask app: interviews the user for name and details, creates the blueprint, builds to spec with unit tests, then drives the verification chain (migration-safety, security-audit, e2e-playwright, observability, ci-gate) via subagents until every gate is green. Use this skill whenever the user asks to build, add, or create a feature, endpoint, page, or capability, even if they don't say 'new feature'. This is the front door for feature work; individual skills are the rooms."
---

# New Feature

You are the orchestrator. You interview, scaffold, build, then delegate verification to subagents running the specialist skills, and you do not declare the feature done until every gate reports green. The chain and its order exist for a reason: each stage consumes the previous stage's artifact, and verification is done by agents that did not write the code.

Read `.agents/autonomy.md` before starting. In an unattended run the MR is the gate: build to a reviewable MR with assumptions surfaced rather than stopping to ask.

## The chain

Engines below are what `.agents/model-routing.json` assigns; `agent_launch.py plan` prints the live table.

```
0. preflight              (script, ~3s)          -> capabilities + decisions
1. spec-first             (inline, OPUS 5)       -> .agents/specs/<slug>.md [approved]
1b. spec-critic           (CODEX sol, blocking)  -> sound | gaps-found (before any code)
2. scaffold + build       (SONNET 5, xhigh)      -> blueprint + unit tests passing
2b. build-review          (CODEX sol, advisory)  -> Breaker on the diff
3. migration-safety       (SONNET 5, xhigh)      -> only if spec says data model changes
4. security-audit         (SONNET 5)  \  parallel after build is green
   e2e-playwright         (SONNET 5)  /
4b. security-tenant-audit (CODEX sol)            -> the classes scanners miss
4c. perf-guardrails       (SONNET 5)             -> only if the spec touches a page/API
                                                    route; measure after e2e passes
5. observability          (SONNET 5)
6. test-author            (SONNET 5)
6b. test-evaluator        (CODEX sol, blocking)  -> valid | weakened | gamed
6c. ci-gate verify        (SONNET 5, always last)
7. patch loop             (back to 2 with findings; max 2 rounds, then escalate)
8. merge-request          (SONNET 5)             -> the human gate
```

Skill locations: resolve each skill's SKILL.md from the installed skills directories before launching; pass the absolute path in the stage prompt.

## Step 0: Preflight (once, then pass it down)

```bash
python3 scripts/preflight.py --json
```

Repair blockers per the **preflight** skill's table, then read `decisions`: `verification_mode` (`herdr-tabs` | `herdr-adversarial` | `subagents`) settles how steps 3-6 run, `grader_engine` says whether the graders get an independent engine or fall back to Claude, and `live_server_tests` tells you whether the live suites will run or skip. Pass the report to each stage in its prompt instead of having every stage re-probe — one environment, one opinion about it.

**Make E2E ground truth, not a skip.** If the spec touches a page or an API route and `live_server_tests` is `skip` (no dev server listening), start the dev server yourself before Step 4 — `uv run workflow start`, backgrounded — so `e2e-playwright` runs against a real server instead of auto-skipping. `.agents/autonomy.md` authorises starting local infra without asking. This matters most in an unattended run: an E2E stage that silently skipped reports green while never having driven the app, which is the opposite of what "just works when I come back" needs. Note in the run report whether you started the server or it was already up. Read the `learnings` block preflight now prints — it carries what prior runs learned (crying-wolf stages, escaped defects) so you don't repeat them.

## Step 1: Spec (inline, never delegated)

Run the **spec-first** skill yourself; it interviews the user, and subagents cannot talk to the user. Do not proceed past this step until the spec file exists with `status: approved` — or, in an unattended run, `status: approved-unattended` with its assumptions listed (see spec-first §3; those assumptions must lead the MR description). The slug from the spec drives everything downstream.

## Step 1b: Spec critique (before a line of code)

Spawn **spec-critic** as a subagent on the freshly written spec — the one gate that checks the *spec* against reality instead of the code against the spec. This is the cheapest possible place to catch ambiguity: a vague AC fixed here is a one-line edit; the same ambiguity found after build is a wrong MR you come back to. Fresh eyes matter, so this is a subagent (spec-first authored the spec; spec-critic must not be the same author), using the Steps 3-6 prompt template but pointed at the spec, not the branch.

- `VERDICT: sound` → proceed to build.
- `VERDICT: gaps-found` → **interactive**: take its gap list back to the user via spec-first, edit the spec, re-run. **Unattended**: spec-first converts each gap into an explicit `ASSUMPTION:` line (default chosen + rejected), re-runs spec-critic once, and those assumptions lead the MR description. Do not start building on a `gaps-found` spec — that is the walk-away-and-come-back-to-garbage failure this step exists to prevent.

Two rounds on the same unresolved gap trips the circuit breaker (Step 7): escalate, don't invent the missing requirement.

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

**After the build is green, hand the diff to the Breaker.** Per `.agents/model-routing.json`, `build-review` runs on Codex (`gpt-5.6-sol`) — fresh eyes on a separate quota pool. It is **advisory**: log its findings into the round file and carry on, surfacing them in the MR description. A Codex quota exhaustion must not strand an unattended run. In tabs mode this is one command (`agent_launch.py launch build-review --base main`); in adversarial mode it is the herdr-multi-agent-collab Workflow A handoff.

## Steps 3-6: Verification

**`.agents/verification-chain.md` is the contract** — execution mode, model routing, read-only graders, blocking rules, concurrency, and the stage prompt template all live there, shared with `fix-bug` and `review-feature`. Read it; don't restate it. In short: read `verification_mode` and `grader_engine` from preflight, then drive stages via `scripts/agent_launch.py` (tabs), the herdr-multi-agent-collab handoff (adversarial), or subagents. The chain and its verdicts are identical in all three.

Two routing points specific to this chain:

`security-audit` **splits deliberately**. The scanner pass is Sonnet; the "hunt what scanners miss — tenant isolation, missing auth" half is `security-tenant-audit` on Codex. Reasoning about `org_id` leakage across a multi-tenant schema is the one genuinely open-ended task here; everything else is rubric-following, which is why Sonnet carries the rest.

`spec-first` is **the only Opus 5 stage in the system**. That is where the money goes because a vague acceptance criterion is the one error every downstream gate can pass while the result is still wrong.

### Stage prompts

Each stage gets the template from the shared contract and nothing else. Fresh eyes are the point: the stage gets the spec and the skill, not your reasoning or excuses.

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
- **security-audit** and **e2e-playwright** are independent; spawn them in the same turn so they run in parallel. This is the *only* pair to parallelise: stage agents draw on the same subscription quota as you, so extra concurrency buys no capacity and burns the window faster. Keep the rest serial.
- **security-tenant-audit** follows the security-audit scanner pass, on Codex. Treat its findings exactly like security-audit's — they merge into one security verdict for step 8.
- **observability** runs after those pass, instrumenting anything the build missed.
- **test-author** runs after observability: it reconciles the *rest* of the suite against this feature's diff (tests in other areas the change rippled into) and refreshes `.agents/test-map.md` — the build wrote this feature's own tests; this stage catches what those tests didn't know they touched.
- **test-evaluator** grades every new or changed test in the diff (this feature's inline AC tests plus anything test-author added) for validity — falsifiability, no silently-widened assertions, no tautologies. Its verdict must be `valid` before ci-gate; treat `weakened`/`gamed`/`inconclusive` as a `findings-open` returned to you.
- **ci-gate** in verify mode is always last, because it checks that everything the other stages produced (tests, rules, migrations) is actually collected and enforced. Parse its `GATE <name>: pass|fail` lines.

Read each stage's report file, not just its verdict line — and never the pane transcript, which scrolls and truncates. A `patched` verdict means code changed: re-run the unit suite before moving on, since one stage's patch can break another's assumptions.

Note which stages *can* return `patched` at all: the routing table gives graders `access: read`, so `spec-critic`, `test-evaluator`, `build-review`, `security-audit` and `security-tenant-audit` cannot edit the code they judge. Their findings come back to you to fix in step 7. That is the fresh-eyes principle enforced at the permission layer rather than trusted to the grader.

## Step 7: Patch loop and circuit breaker

`findings-open` from any stage comes back to you: fix (that is builder work), then re-run only the failed stage plus ci-gate. Track rounds in `.agents/reports/<slug>/rounds.md`. If the same finding survives **two full rounds**, stop, write up what was tried and your best hypotheses, and escalate to the user. Grinding a third round on the same wall burns tokens and usually means the spec or the design is wrong, which is a human decision.

**Escalation must reach the human, not wait silently.** "Escalate to the user" fails the walk-away case if there is no user in the room. When the breaker trips (or any impasse per `.agents/autonomy.md`), do both: (1) push what you have as a **`Draft:` MR** via merge-request with the impasse, the two-or-three hypotheses, and the failing stage's report linked in the description — a reviewable artifact beats a lost session; (2) fire a **`PushNotification`** summarising the block and the MR link, so the founder finds it at their leisure instead of discovering a stalled run. A notification the human reads later is not a blocking question — it's the autonomy policy's escalation channel (`.agents/autonomy.md` → Escalation, point 5).

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
