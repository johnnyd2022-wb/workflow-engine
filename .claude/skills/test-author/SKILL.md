---
name: test-author
description: "Owns test coverage of the app's core user flows and keeps the whole suite reconciled when code changes ripple beyond one file. Maintains the core-flow test map at .agents/test-map.md, writes unit/integration tests for uncovered flows, and — given a diff — updates the affected tests across every area the change touches, not just its own test file. Use this skill when the user says 'write tests for X', 'update the tests after this change', 'is <flow> covered', or on a scheduled coverage sweep; and it is chained by new-feature, fix-bug, review-feature, and dependency-update after they build, to reconcile ripple effects and refresh the map. NOT for browser/E2E flows (e2e-playwright), NOT for the runtime honesty of the suite — skips, flakes, quarantine (suite-warden), and NOT for judging whether an authored test is valid (test-evaluator, which it hands every batch to). Autonomous: writes tests and opens an MR; every batch is graded by test-evaluator before it ships."
---

# Test Author

The three code front doors each write tests for the change they are making — `new-feature`
writes AC-named unit tests for the feature it builds, `fix-bug` writes one red repro test
first, `review-feature` patches the gaps it audits. That is correct and stays. But two
things fall through the cracks between them: nobody owns the standing question *"is every
core user flow actually covered by a test?"*, and nobody reconciles the rest of the suite
when a change ripples past its own test file. An untested core flow and a stale
neighbouring test are both invisible until production finds them. This skill owns both.

It writes **unit and integration** tests only. Browser flows belong to `e2e-playwright`;
the runtime honesty of the suite (skips, flakes, quarantine) belongs to `suite-warden`;
and this skill never certifies its own work — every batch it writes or edits goes to
`test-evaluator` before it can ship. Author and grader are deliberately separate.

Read `.agents/autonomy.md`. This skill runs unattended and ships via MR.

## Step 1: Preflight, always

```bash
python3 scripts/preflight.py --json
```

Read `capabilities.test_db` and `decisions.live_server_tests`. If `test_db` is down, repair
per the **preflight** skill and re-run — a suite that can't reach Postgres on `localhost:8401`
is an environment problem, not a coverage problem. Take `live_server_tests` (`run` | `skip`)
as given; don't re-probe. If the dev app server is down, the `live_server`-marked 2FA
suites skip — that is expected, not a gap this skill fills.

## Step 2: Sync the test map

The map at `.agents/test-map.md` is the source of truth for what "covered" means here — a
flow-based (not line-based) inventory of core user journeys, the test files that prove
them, and an honest status per row. Reconcile it against reality before doing anything else:

```bash
python3 scripts/test_map_check.py            # human summary
python3 scripts/test_map_check.py --json     # machine-readable
```

The script is deterministic: it flags map rows whose named test file no longer exists, and
`tests/test_*.py` files that appear in no row (coverage the map doesn't know about). Fix
drift the script proves — a renamed file, a new suite — before deciding what to write.
Don't hand-grep for this; the script exists so the map can't silently rot.

## Step 3: Decide the mode — gap-fill or diff-reconcile

**Gap-fill** (user asks "write tests for X" / "is <flow> covered", or a scheduled sweep):
pick the lowest-status rows in the map — `none` before `partial` before `covered` — and,
within those, the highest-risk flows first (auth, tenant isolation, inventory quantity
writes, money paths). Write the missing tests.

**Diff-reconcile** (chained by a front door, or user says "update the tests after this
change"): start from the diff.

```bash
git diff --name-only main...HEAD                  # what changed
git diff --name-only main...HEAD -- 'app/**'      # product code only
```

Map each changed module to the flows it participates in (the map's rows name the app areas
they cover), then update or extend the affected tests **across every area the change
touches** — this is the half nobody else owns. A change to `inventory_quantity_guard.py`
touches wastage tests, execution-step tests, and the manual-API-update path; reconcile all
three, not only the file the feature author happened to edit.

## Step 4: Write the tests

- **Layout:** flat `tests/test_<area>.py`, colocated with the area's existing tests
  (`.agents/conventions.md` §6) — no `tests/unit|integration` split, no bug-specific file
  unless no area file fits.
- **Data:** use the **test-fixtures** skill's factories (`tests/factories.py`) and the
  `two_org_two_user` fixture (`tests/conftest.py`). Never hand-seed an org or user. If a
  factory is missing for a model, that is a `test-fixtures` change — add it there, not
  inline in the test.
- **Tenant isolation is not optional:** any test that exercises an org-scoped route or
  repository must include the hostile-neighbour case — a user in org A gets 404/empty for
  org B's record — using `two_org_two_user`. A happy-path-only test of a scoped endpoint
  is a partial test; mark the row `partial`, not `covered`.
- **Name for the behaviour, not the mechanism:** `test_wastage_write_rejects_untracked_reason`,
  not `test_wastage_2`. The name is what a reader trusts a year later.
- **Cover the unhappy paths:** missing auth, wrong org, invalid payload, the forbidden
  enum value. A flow tested only on its happy path is `partial`.

Run until green, `ENVIRONMENT` unset (resolves to `local`, test DB on `:8401` —
`ENVIRONMENT=test` from a host shell hangs; see preflight's `test_db` check):

```bash
uv run pytest tests/test_<area>.py -v      # the area you touched
uv run pytest tests/ -q                     # nothing else broke
```

A failure that never reached an assertion — connection error, missing service — is
**suite-warden**'s to classify, not a bug in your tests. Route it there.

## Step 5: Update the map, then hand the batch to the grader

Update the row(s) in `.agents/test-map.md` for every flow you touched: new test file/names,
new status, and — for a diff-reconcile — the one-line reason the update was justified
(*which intended behaviour change* drove it). "The test was failing" is never a
justification; that is the move `test-evaluator` exists to catch.

Then hand the **entire batch of new and changed tests to `test-evaluator`** — mandatory,
no exceptions. Invoke it as a subagent (or, inside Herdr with a Breaker pane, via the
`herdr-multi-agent-collab` protocol — same checklist, different engine):

```
Read and follow the skill at: <abs path>/.claude/skills/test-evaluator/SKILL.md
Batch: the new/changed test files in `git diff --name-only main...HEAD -- 'tests/**'`
Task: grade this batch for validity per the skill and write your report.
End your reply with exactly one line: VERDICT: valid | weakened | gamed | inconclusive
```

**The handoff to `merge-request` / `git-commit-chain` is blocked on `valid`.** On
`weakened`, `gamed`, or `inconclusive`, fix the specific test the grader named and
re-submit that batch — do not ship around the verdict. Two rounds on the same finding is
the ceiling (`.agents/autonomy.md`); a third means the flow itself is untestable as
specced, which escalates.

## Step 6: Report and ship

`.agents/reports/test-author/<date>.md`:

```markdown
# TEST AUTHORING — <date>
mode: gap-fill | diff-reconcile
preflight: test_db=<up|down>, live_server_tests=<run|skip>
flows_touched: <map rows, by name>
tests_added:   <file::test_name, …> | none
tests_updated: <file::test_name — justifying behaviour change> | none
map_rows_changed: <row — old status → new status>
suite_result: <N passed, N skipped> (<split honest — never "all green" if any skipped>)
evaluator_verdict: valid | weakened | gamed | inconclusive  (report: <path>)
verdict: covered | gaps-open | blocked-by-evaluator
```

`covered` means: the flows you targeted are covered, the suite is green (with the skip
split stated), and the evaluator returned `valid`. Anything else says which and why.

Ship via `git-commit-chain` (or `merge-request` when chained from a front door), **only
after** the evaluator verdict is `valid`. Real product-code failures uncovered while
writing tests go to `fix-bug` — one MR per bug, not a batch.

## Rules

- **Never weaken, broaden, delete, or skip an existing assertion to make a diff green.**
  That is `.agents/autonomy.md`'s cardinal prohibition and the exact manipulation
  `test-evaluator` grades for. If a test genuinely must change because behaviour
  intentionally changed, state the intent in the map row and the MR — an invisible
  weakening is a lie by omission.
- **Never ship a batch the evaluator hasn't returned `valid` on.** The grader is not
  advisory; it is the gate on your own work.
- Unit/integration only. Don't reimplement an `e2e-playwright` browser scenario as a
  pseudo-unit test — that duplicates coverage and rots twice.
- Factories create through repositories, never bypass them (`test-fixtures` rule). A test
  that seeds data the app could never actually produce passes against fiction.
- Don't start services as a side effect. If the app server is down, the live suites skip;
  say so, don't spin one up mid-run to change the result.

## Handoffs

- ← **new-feature** / **fix-bug** / **review-feature** / **dependency-update**: after they
  build and their own inline tests pass, chained here with the diff to reconcile ripple
  effects across the rest of the suite and refresh the map.
- ← **suite-warden**: its **stale** bucket (a test asserts behaviour that intentionally
  changed) routes here for the update, with the justifying change named.
- ← the user: "write tests for X", "update the tests after this change", "is <flow>
  covered".
- ← a schedule: periodic coverage sweep against the lowest-status map rows.
- → **test-evaluator**: mandatory on every authored batch; the ship is blocked on `valid`.
- → **test-fixtures**: when a needed factory or seeded world is missing.
- → **suite-warden**: any failure that never reached an assertion.
- → **fix-bug**: a real product-code failure surfaced while writing a test.
- → **git-commit-chain** / **merge-request**: ships, only after `valid`.
