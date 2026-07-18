# Plan: `test-author` + `test-evaluator` skills

status: planned (awaiting execution)
branch: plan/test-authoring-skills
author: Claude (Fable 5) — planning pass only; execution to follow on Opus
date: 2026-07-18

## The ask

Two new registered skills:

1. **A test-writing/updating skill** — writes tests for every core flow in the app
   (the key things a human user would actually run into), and dynamically updates/edits
   existing tests when code changes land — wired off the skills that make those changes
   (`new-feature`, `fix-bug`, `review-feature`, `dependency-update`).
2. **A test-evaluation skill** — triggered from the first skill, adversarially checks
   the *logic* of new/changed tests: that they haven't been manipulated to pass, that
   they're valid claims about the code and make sense.

## Gap analysis: what already exists (and what doesn't)

Neither skill exists. Four skills sit near this territory, and the new skills must be
carved to not overlap them (skill-smith rule: two skills claiming the same trigger is
worse than one big one — the router picks wrong):

| Existing skill | What it owns | What it explicitly does NOT own |
|---|---|---|
| `suite-warden` | Runtime honesty of the suite signal: skips/markers, flake detection, quarantine registry, "green means green" | Writing tests — its own SKILL.md says "It does not write feature tests (that's new-feature/fix-bug)" |
| `test-fixtures` | Shared factories (`tests/factories.py`) + seeded worlds (`two_org_two_user` in `tests/conftest.py`) | Test logic itself — it's the data layer under tests |
| `e2e-playwright` | Headless browser E2E mapped to acceptance criteria | Unit/integration coverage of core flows |
| `herdr-multi-agent-collab` | Adversarial Breaker review — but only cross-pane, only when `HERDR_ENV=1` | A standing, always-available test-validity check |

Test *writing* today happens inline inside the three front doors, scoped to their own
change: `new-feature` writes AC-named unit tests for the feature it builds; `fix-bug`
writes one red repro test first; `review-feature` patches gaps it audits. **Nobody owns
the standing question "are all core flows covered?"** and **nobody owns ripple effects**
— when a change makes tests in *other* areas stale, that's suite-warden's "stale" bucket,
which today just says "the change's author updates it".

Test *validation* today is only two things: fix-bug's red-first rule (proves a repro test
can fail) and suite-warden's prohibition on weakening tests to get green (a rule, not a
check). There is no skill that inspects whether a green test is actually asserting
anything. That's the classic agentic failure mode this second skill exists to close.

Conclusion: **both skills are genuinely new.** The blanks to fill are boundary lines, not
missing halves.

## Skill 1: `test-author`

Location: `.claude/skills/test-author/SKILL.md` (engineering skill — no symlink needed).

**Why it exists (first paragraph of the SKILL.md):** the front doors write tests for the
change they're making; nothing writes tests for the flows a human actually walks through
end to end, and nothing reconciles the rest of the suite when a change ripples beyond its
own test file. Untested core flows and stale neighbouring tests are both invisible until
production finds them.

### Owns

1. **The core-flow test map** — new file `.agents/test-map.md`: an enumerated list of
   core user flows → the test files that prove them → coverage status. Seed it from the
   real app surface (verified against blueprints during execution):
   - signup → login → TOTP 2FA setup/verify → session security
   - org creation, membership, org-scope enforcement
   - process definition → DAG traversal → execution lifecycle (start, complete step,
     idempotency via `ApiIdempotencyKey`, lineage)
   - inventory quantity writes (every `InventoryQuantityWriteReason` path), unit
     conversion, wastage entry + batch-hash idempotency
   - multi-tenant isolation: every scoped model, org A cannot read/write org B (uses
     `two_org_two_user`)
   - CRM + Xero invoicing (feature-flagged: `crm_enabled`)
   - lineage tracing (`workflow_engine_enabled`)
   - CSRF/rate-limit/auth-decorator behavior on the routes above
2. **Gap-driven test writing** — for any flow in the map with missing/partial coverage,
   write unit/integration tests in the existing flat `tests/test_<area>.py` layout
   (`.agents/conventions.md` §6), using `test-fixtures` factories — never hand-rolled
   seed data.
3. **Diff-driven test updates** — given a diff (from a front door, or `git diff main`),
   identify which flows in the map the change touches, then update/extend the affected
   tests across the whole suite, not just the change's own file. This is the "dynamic"
   half of the ask, and it's where suite-warden's "stale" bucket gets a real owner.

### Triggered by (wiring — each edge edited into BOTH skills' files)

- ← `new-feature` step 5 (verification chain): after build + inline AC tests pass, chain
  test-author with the diff to reconcile ripple effects + update the test map.
- ← `fix-bug` step 4 (verify): after the repro test is green, same reconciliation pass.
- ← `review-feature`: its unit-coverage stage delegates gap-filling here.
- ← `dependency-update`: after a bump, checks whether behavior-pinning tests need updating.
- ← `suite-warden`: routes its **stale** bucket here (test asserts intentionally-changed
  behavior) instead of "the change's author updates it".
- ← the user: "write tests for X", "update the tests after this change", "is <flow>
  covered?"
- ← a schedule: periodic coverage sweep (add to `ROOTS` in `scripts/skill_graph.py` —
  legitimately user/schedule-invoked, so this is not ROOTS-padding).
- → `test-evaluator`: **mandatory, every batch** — no test it writes or edits reaches a
  commit without an evaluator verdict (see below).
- → `test-fixtures`: when a needed factory is missing, add it there, not inline.
- → `suite-warden`: any failure that never reached an assertion (connection error etc.).
- → `git-commit-chain` / `merge-request`: ships, only after evaluator verdict `valid`.

### Rules (the 3am prohibitions)

- Never weaken, broaden, delete, or skip an existing assertion to make a diff green —
  that call belongs to test-evaluator + suite-warden, and doing it here is the exact
  move test-evaluator exists to catch.
- A test update must state (in the test-map row or MR text) which intended behavior
  change justified it. "The test was failing" is not a justification.
- Distinguish repo layers: unit/integration only. Browser flows belong to
  `e2e-playwright`; don't duplicate an E2E scenario as a fake-unit test.
- Run pytest with `ENVIRONMENT` unset (resolves to `local`, test DB on :8401) — see
  preflight. `ENVIRONMENT=test` from a host shell hangs.

### Report contract

`.agents/reports/test-author/<date>.md`: flows touched, tests added/updated (file::name),
map rows changed, suite result split (passed/skipped), evaluator verdict + report link.
Verdict vocabulary: `covered | gaps-open | blocked-by-evaluator`.

## Skill 2: `test-evaluator`

Location: `.claude/skills/test-evaluator/SKILL.md`.

**Why it exists:** an agent that writes both the code and the test that grades it can —
without malice — write a test that passes because it asserts nothing, mirrors the
implementation, or was quietly weakened. Green from such a test is worse than red: it
certifies. This skill is the independent grader; it never edits what it grades.

### Owns

Adversarial review of **new or changed tests only** (scope = the diff's test files, plus
any test whose assertions changed), checking:

1. **Falsifiability** — would this test go red if the behavior it claims to protect
   broke? Technique: *mutation spot-checks* — temporarily invert/break the guarded code
   path (in-memory or a stash-revert cycle, never committed), run the test, confirm red,
   restore, confirm green. The inverse of fix-bug's red-first rule, applied to any test.
   Budget: every new test gets at least the "does it assert anything" static pass;
   mutation probes on a risk-ranked subset (auth, tenant isolation, inventory writes,
   money paths — always; cosmetic asserts — sampled).
2. **Assertion-diff review** — `git diff` of test files: flag any assertion that got
   broader (`==` → `in`, exact → `>= 0`, removed fields), any deleted assertion, any new
   `skip`/`xfail`/`quarantined` marker without a suite-warden-legal reason, any tolerance
   widening.
3. **Tautology hunt** — asserting the mock, asserting the fixture back at itself,
   `assert resp.status_code in (200, 302, 404)` catch-alls, try/except-pass around the
   assert, tests that recompute the expected value using the same code under test.
4. **Sense check** — test name matches what it proves; AC-named tests actually exercise
   that AC; org-scoped endpoints tested with the *hostile* org too, not just the owner.

### Triggered by / feeds

- ← `test-author`: mandatory on every batch (the primary edge — per the ask).
- ← `new-feature` / `fix-bug` / `review-feature`: on their *inline* tests before the
  merge-request step. Cheap to add: one line in each front door's verification chain.
- ← `herdr-multi-agent-collab`: when `HERDR_ENV=1`, the Breaker pane MAY be the executor
  of this skill's checklist — same contract, different engine. Outside Herdr it runs as
  a subagent. (Note this in both files so it's not a competing trigger.)
- → back to the caller with findings; caller fixes, evaluator re-checks. It **never
  edits tests or code itself** — separation of author and grader is the entire point.
- → `suite-warden`: anything it finds that's a runtime-signal issue (flake, gating).

### Report contract

`.agents/reports/test-evaluator/<date>.md`: batch scope, per-test check results,
mutation probes run (path broken → red? y/n), findings. Verdict vocabulary:
`valid | weakened | gamed | inconclusive` — and the caller's handoff to merge-request is
**blocked** on anything but `valid`. `gamed` names the specific test and the manipulation.

### Rules

- Never fix what it finds — report and block. An evaluator that edits is an author.
- Never run mutation probes against uncommitted author work without stashing safely;
  never leave a mutated code path behind (verify `git status` clean-relative afterwards).
- `inconclusive` is an honest verdict (e.g., can't probe a live-server-marked test with
  no server up) — it blocks like `gamed` does, but says why and what would resolve it.

## Boundary decisions (made in this plan, so execution doesn't re-litigate)

1. **Front doors keep writing their own inline tests.** test-author is chained *after*
   for ripple effects + map upkeep, and is the front door for test-only asks and
   scheduled sweeps. Rationale: the builder has the spec context; gutting `new-feature`'s
   build step would churn three stable skills for no coverage gain.
2. **suite-warden vs test-evaluator:** warden owns *runtime* signal (skips, flakes,
   quarantine, noise); evaluator owns *write-time* validity (is this test an honest
   claim). Warden's "stale" bucket routes to test-author; warden's "confirm the
   assertion still protects something" duty routes to test-evaluator.
3. **test-evaluator is not in `ROOTS`** — it's always invoked by a caller; its
   reachability is proven by the wired edges (skill_graph will verify).
4. **Naming:** `test-author` and `test-evaluator`. Considered `test-coverage` (sounds
   like a metric, not an actor) and `test-integrity` (collides with warden's territory
   in the router's mind).

## Execution checklist (for the Opus run)

Follow **skill-smith**'s creation procedure — this plan is the "check it should exist"
step done. Stay on this branch (`plan/test-authoring-skills`) or branch from it.

1. Write `.claude/skills/test-author/SKILL.md` to the house standard: routing-grade
   frontmatter description with real trigger phrases; why-paragraph; numbered steps with
   commands **you have actually run**; `.agents/autonomy.md` link (not restated);
   report contract; handoffs; rules — all as specced above.
2. Write `.claude/skills/test-evaluator/SKILL.md` likewise.
3. Seed `.agents/test-map.md` by reading the real blueprints/routes and the existing
   `tests/` files — every row verified against code, none invented. Mark honest initial
   statuses (much of executions/2FA/multi-tenant is already covered; map it, don't
   rewrite it).
4. Wire handoffs **both directions**: edit `new-feature`, `fix-bug`, `review-feature`,
   `dependency-update`, `suite-warden`, `test-fixtures`, `herdr-multi-agent-collab` to
   reference the new skills at the exact steps named above. One-directional handoffs are
   dangling pointers.
5. Register: add both to `.claude/skills/entrypoint/skill-index.md` — category 2
   (specialists) rows for both; test-author also in 2b (scheduled sweep). Add
   `test-author` to `ROOTS` in `scripts/skill_graph.py`.
6. Optional (recommended, small): `scripts/test_map_check.py` — deterministic check that
   every test file referenced in `.agents/test-map.md` exists and every `tests/test_*.py`
   appears in some row (stdlib, `--json`, meaningful exit codes — same pattern as
   `scripts/preflight.py`). Backs test-author's map-sync step with a script instead of
   tokens, per skill-smith step 4.
7. Verify: `python3 scripts/skill_graph.py --check` reports no orphans/unindexed; run
   every command written into both SKILL.mds; full suite still `252 passed, 30 skipped`
   (no product code changes in this MR).
8. Ship via `git-commit-chain` → MR. Update this spec's status to `built`.

## Out of scope (explicitly)

- No product-code or existing-test changes in the skill-creation MR.
- pytest-cov / coverage tooling: the map is flow-based, not line-based, on purpose.
  Line-coverage tooling can be a later add if the map proves too coarse — separate ask.
- Rewriting how front doors build (decision 1).
