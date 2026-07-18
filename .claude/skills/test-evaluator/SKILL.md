---
name: test-evaluator
description: "Adversarially grades new or changed tests for validity — that they are honest claims about the code, not tests quietly shaped to pass. Checks falsifiability (would this test go red if the behaviour it guards broke?) with mutation spot-checks, reviews assertion diffs for silent weakening, hunts tautologies and catch-all asserts, and sense-checks that each test proves what its name says. Use this skill when test-author finishes a batch (mandatory), when new-feature/fix-bug/review-feature want their inline tests graded before the MR, or when the user says 'are these tests real', 'did the test actually test anything', 'check these tests aren't gamed'. NOT for writing or fixing tests (test-author), NOT for runtime signal — flakes, skips, quarantine (suite-warden). It never edits code or tests — it reports and blocks. Autonomous: grades and returns a verdict; the caller's ship is blocked on 'valid'."
---

# Test Evaluator

An agent that writes both the code and the test that grades it can — with no malice at all
— produce a test that passes because it asserts nothing, mirrors the implementation it is
supposed to check, or was quietly loosened until it went green. A green result from such a
test is worse than a red one: red says "look here", green says "certified, move on". This
skill is the independent grader that makes green mean something. It reviews **only new or
changed tests** and it **never edits what it grades** — the separation of author and grader
is the entire mechanism; an evaluator that fixes what it finds is just a second author.

Read `.agents/autonomy.md`. Runs unattended; returns a verdict that gates the caller's MR.

## Step 1: Scope the batch

Grade exactly the tests that are new or whose assertions changed — not the whole suite.

```bash
git diff --name-only main...HEAD -- 'tests/**'          # changed test files
git diff main...HEAD -- 'tests/**'                       # the actual changes to read
```

For each changed file, read the diff, not just the final text: a test that *lost* an
assertion looks fine at rest and only indicts in the diff. Build the list of individual
tests in scope (added, or assertion-changed).

## Step 2: Static checks — read every test in scope

Four checks, applied to each test. None requires running anything yet.

1. **Does it assert anything at all?** A test whose only "assertion" is that the code ran
   without raising is a smoke test mislabelled as a unit test. Flag it unless the thing
   under test genuinely is "does not raise" (and then the name must say so).
2. **Assertion-diff review** (changed tests only): flag any assertion that got *broader* —
   `==` → `in`, an exact value → `>= 0` or `is not None`, a dropped field from an expected
   dict, a widened tolerance — and any assertion that was *deleted*. Flag any new
   `skip` / `xfail` / `pytest.mark.quarantined` that lacks a `suite-warden`-legal reason
   (an absent dependency named, not "this was failing").
3. **Tautology hunt:** asserting a mock against itself; asserting a fixture value back at
   the fixture; catch-all status assertions like `assert resp.status_code in (200, 302,
   404)`; `try/except: pass` wrapped around the assert; and the subtle one — a test that
   **recomputes the expected value using the same function under test**, so it can never
   disagree with it.
4. **Sense check:** does the test name match what it proves? Does an AC-named test
   (`test_ac3_...`) actually exercise that acceptance criterion? Is an org-scoped endpoint
   tested with the **hostile** org too, or only its owner — because a scoped-route test
   that never tries the other org proves nothing about isolation.

## Step 3: Mutation spot-checks — the falsifiability probe

The static checks catch shape; this catches substance. A test only protects a behaviour
if it goes **red when that behaviour breaks**. Prove it on a risk-ranked subset:

**Always probe** — auth/decorators, tenant isolation, inventory quantity-write guard
(`InventoryQuantityWriteReason` paths), idempotency, and any money/invoice path.
**Sample** — cosmetic or presentational assertions.

The probe, per selected test:

```bash
# 1. capture a clean tree first — nothing uncommitted must be lost
git stash list && git status --porcelain        # know your starting state

# 2. break the guarded code path in-place (invert a condition, neuter the org filter,
#    drop the reason check) — a surgical edit to app/, NEVER committed
uv run pytest tests/test_<area>.py::test_<name> -q   # EXPECT: red

# 3. restore exactly
git checkout -- app/<file>                        # or `git stash pop` if you stashed
uv run pytest tests/test_<area>.py::test_<name> -q   # EXPECT: green again
git status --porcelain                            # MUST be back to the pre-probe state
```

If breaking the behaviour leaves the test **green**, the test does not protect it —
verdict `gamed` (or `weakened` if it once did and an edit loosened it), naming the test and
the mutation that slipped past. This is the inverse of `fix-bug`'s red-first rule, applied
to any test rather than only a bug repro.

**Never commit a mutation. Never leave one behind.** Verify `git status --porcelain` is
clean-relative to where you started before you finish — a stray inverted condition left in
`app/` is the one way this skill can do real damage.

## Step 4: Verdict and report

`.agents/reports/test-evaluator/<date>.md`:

```markdown
# TEST EVALUATION — <date>
batch: <files / tests in scope>
static:   <per-test: asserts? diff-widened? tautology? sense?>
mutations: <test — path broken → red? yes/no> | none run (<why>)
findings: <test :: the specific problem, and what would fix it> | none
verdict: valid | weakened | gamed | inconclusive
```

- **valid** — every test in scope asserts a real, falsifiable claim; no assertion was
  silently widened or dropped; probed tests went red when their behaviour broke.
- **weakened** — a previously-real test was loosened (broadened/deleted assertion, widened
  tolerance, unjustified skip). Names the test and the diff.
- **gamed** — a test passes without protecting anything (tautology, asserts-the-mock,
  recomputes-with-the-code-under-test, green under mutation). Names the test and the
  manipulation.
- **inconclusive** — can't complete the grade (e.g. a `live_server`-marked test can't be
  probed with no app server up). Says exactly what blocked it and what would resolve it.

The caller's handoff to `merge-request` is **blocked on anything but `valid`** —
`inconclusive` blocks exactly like `gamed`, because an ungraded test is not a passed one.

## Rules

- **Never edit or fix a test or the code.** Report and block. An evaluator that patches is
  an author, and the whole point is that they are different agents.
- **Never leave a mutation in the tree.** Stash or checkout-restore every probe; verify
  `git status --porcelain` returns to its starting state before returning a verdict.
- Don't grade the whole suite — only the batch in scope. Grading unchanged tests is
  `suite-warden`'s health run, not this.
- `inconclusive` is an honest, blocking verdict — never round it up to `valid` to unblock
  a caller. That would be the exact shading `.agents/autonomy.md`'s honest-reporting
  section prohibits.
- A finding names the specific test and the specific manipulation. "Tests look weak" is
  not a finding the author can act on; `test_x_leaks :: asserts resp.ok but never checks
  the other org's rows are absent` is.

## Handoffs

- ← **test-author**: mandatory grade on every authored/edited batch — the primary caller.
- ← **new-feature** / **fix-bug** / **review-feature**: grades their inline tests before
  the `merge-request` step (one line added to each front door's chain).
- ← **herdr-multi-agent-collab**: when `HERDR_ENV=1`, the Breaker pane may execute this
  checklist in its own pane — same contract, different engine — instead of a subagent.
- → the **caller**: returns the verdict; the caller fixes what's named and re-submits.
  This skill does not fix anything itself.
- → **suite-warden**: anything it notices that is a runtime-signal problem (a flake, a
  gating issue) rather than a validity one.
