# REVIEW: inventory
date: 2026-07-27 → 2026-07-29
branch: work/2026-07-27-session (rebased onto `review-feature` @ 8d95f83 — **open MR !133, not merged**)
baseline: tests green (569 passed, 30 skipped), working tree clean
verdict: **patched** — one item needs a human decision before merge (see Release gates)

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration-safety | findings-open | 2 | [migration-safety.md](migration-safety.md) |
| security-audit | findings-open | 5 | [security-audit.md](security-audit.md) |
| e2e-playwright | clean | 0 | [e2e-playwright.md](e2e-playwright.md) |
| test-author | patched | — | [test-author.md](test-author.md) |
| test-evaluator (3 rounds) | invalid → fixed | 20 | [test-evaluator.md](test-evaluator.md) |
| observability | patched | 1 | this report |
| ci-gate | clean | 0 | this report |

Execution mode `herdr-tabs`, grader engine `codex` — graders ran read-only on a separate
engine, so the review had genuinely independent eyes.

## What was wrong, and what now stops it recurring

### F1 — cross-tenant read of another org's production data (CRITICAL)
Two independent defects that compose into a real tenant-boundary break:

- **Write side** (`backend.py:3591-3599`): `POST /api/core/inventory` took
  `source_execution_id`, `source_execution_step_id` and `source_output_id` straight from
  client JSON into FK columns with no ownership check. `executions` / `execution_steps`
  are global tables; `source_output_id` has no FK at all.
- **Read side** (`dagtraversal.py:_enrich_items_bulk`): fetched `ExecutionStep`,
  `Execution` and `Process` for those references **with no org filter**, then stitched
  `execution_data` (prompts), `actual_inputs`, `actual_outputs` and the process name into
  the response.

Chained: org A plants a reference to org B's execution step, calls
`GET /api/core/inventory/trace/<own_item>`, and reads back org B's process data.

Fixed in both layers — deliberately, because the read-side scoping is what would have
contained the blast radius on day one:
`InventoryRepository._assert_source_refs_belong_to_org` rejects out-of-org references
(and requires `source_output_id` to arrive with an in-org step and to be one of that
step's declared outputs, since there is no FK to lean on), and `_enrich_items_bulk` now
scopes every lookup by `org_id`.

### F2/F3 and their siblings — non-finite quantities reaching comparisons
`float("nan") <= 0` is `False`, so `"nan"` passed route-level gates; `Decimal("NaN") < 0`
then raises `InvalidOperation`, which is **not** a `ValueError` and so escaped handlers as
unlogged, non-JSON 500s. Four instances, all fixed:

- `set_inventory_item_quantity` — `is_finite()` checked before any ordering comparison.
- `coerce_stored_quantity` — `quantize()` moved inside the `try` (`"1e400"` is finite but
  needs ~404 significant digits).
- `reconciliation_service._parse_quantity` — now returns `None` for non-finite, fixing all
  13 downstream comparison sites at the choke point.
- `inventory_dispose_confirm` — its handler caught `(TypeError, ValueError)`, which
  excludes `InvalidOperation`, so `?quantity_wasted=nan` 500'd the page.

The last two were found by the semgrep rule written from the first two — the learning loop
paying for itself inside one audit.

### F4 — missing org filter on a join
`list_inventory_items` outer-joined `Execution` with no `Execution.org_id == org_id`,
unlike its sibling `get_untracked_items`. Fixed.

### F5 / AC20 — CSV raw-body path
Two problems in one branch: it never enforced the endpoint's own 2 MB cap (inheriting the
evidence-upload `MAX_CONTENT_LENGTH`, 5× larger and owned by unrelated config), and it
decoded with `errors="replace"`, so invalid UTF-8 became U+FFFD and the upload *proceeded*
— while the multipart branch returned 400 for identical bytes. On a traceability product,
silently mangling an item name is worse than refusing the file. Both fixed.

### F6 — `inventory_type` was unvalidated free text
A `String(50)` with no constraint and no route validation. An off-enum value (e.g.
`"RAW_MATERIAL"`) stored fine and then silently vanished from every exact-match view,
including `/out-of-stock` — the recall-tracing view. Now validated against the enum.

This one bit immediately: 18 E2E tests failed on the fix because their helpers had been
passing `"RAW_MATERIAL"` and relying on the bug. The test data was corrected; the
validation was not loosened.

### Observability — cross-tenant rejections were invisible
The new rejections return an ordinary 400, so a tenant-boundary probe left no trace at
all. `_assert_source_refs_belong_to_org` now emits a structured `access_denied` warning —
the same event name the auth decorators use, so one query covers both surfaces — with a
test that fails if the log line is dropped.

## Deliverables that outlive this conversation

- **`.semgrep/rules/learned.yml` +1 rule**: `bize-decimal-compare-without-finite-guard`,
  with a verified fixture pair. Fires on its bug, silent on the fix, **0 findings on the
  current codebase**, and it found two of the six fixes above.
- **A rule I wrote and then withdrew**: `bize-orm-join-without-org-filter`. It flagged 5
  sites including my own fix and code security-audit had explicitly praised as correctly
  scoped — semgrep can't see an org filter applied in a *separately chained* `.filter()`.
  CI runs `--error` over the whole rules directory, so shipping it would have failed the
  build on correct code and taught everyone to sprinkle `nosemgrep`. Recorded here rather
  than shipped; needs a pattern that can traverse chained calls before it's enforceable.
- **`.agents/specs/inventory.md`** — 33 ACs, reconstructed (`status: reviewed`).
- **145 new/changed tests** across 10 files.

## Before / after

| | baseline | now |
|---|---|---|
| suite | 569 passed, 30 skipped | **752 passed, 0 skipped** |
| coverage (audited modules) | 55% | **84%** |
| `inventory_upload_routes.py` | 22% | 81% |
| `reconciliation_routes.py` | 37% | 75% |
| `inventory_quantity.py` | 67% | 100% |
| endpoints with zero test references | 7 | 0 |
| enforced semgrep findings on `app/` | 0 | 0 |

The 30 skips are gone because the dev server was started, so the live-server suites now
run rather than skip. No test was weakened, skipped, quarantined or deleted to get green —
test-evaluator verified that against the diff in all three rounds.

## Release gates

1. **Destructive-migration permit — RESOLVED 2026-07-29: acknowledged, roll forward.**
   `.agents/reports/migrations/inventory_quantity_numeric_001.md`. The March 2026 migration
   altered `inventory_items.quantity` from `String(50)` to `NUMERIC(18,4)` in place:
   precision beyond 4dp silently rounded, and blank legacy quantities coerced to `0` by a
   `CASE WHEN trim(...) = ''` clause — a data edit hidden inside a schema migration. It is
   already applied everywhere, so the fix is the paper trail, not a rewrite, and **nothing
   backs up the lost values**.

   Founder's decision: the feature is **not yet live in production**, so no customer stock
   figures are at risk and there is nothing to investigate; the losses are accepted risk on
   pre-production data. Prevention (a CI check that fails a destructive revision lacking a
   permit) is being assigned to a separate agent rather than done in this MR. Recorded in
   the permit's Decision section, dated.

   The underlying fact does not expire: if this reaches production with real stock, "nothing
   backs it up" stops being cheap. That is why the permit keeps saying so.

2. **MR !133 is still open.** Everything here sits on unmerged work. If !133 changes during
   review, this branch needs re-rebasing.

## Out of scope, found anyway — routed, not fixed

- **First migration in the chain (`0e781c27351d`) breaks full-history reversibility.** Its
  downgrade drops its four tables but not the two enum types it creates, so
  `base → head → base → head` dies with `DuplicateObject: type "organisation_status"
  already exists`. CI can't see this: `migration_reversibility` only runs `downgrade -1`
  against a DB already at head, never provisioning from empty. The correct pattern already
  exists in-repo (`add_core_process_execution_models` drops its enums with
  `checkfirst=True`). Belongs to auth/org, not inventory → **follow-up review-feature pass**.
- **`agent_launch.py` is broken for every Codex grader stage.** It always injects `--base`,
  and `codex review` rejects `--base` alongside a piped prompt
  (`error: the argument '--base <BRANCH>' cannot be used with '[PROMPT]'`). Affects
  `test-evaluator`, `spec-critic`, `build-review`. Worked around here with `codex exec` at
  the same routed model/effort/read-only sandbox, so the grade stayed independent →
  **skill-smith**.
- **CLAUDE.md documents "252 passed, 30 skipped"**; reality was 569 before this audit and
  752 after → **docs-truth**.
- **9 pre-existing ruff findings** in `test_perf_budgets.py`, `test_corechecks.py`,
  `test_executions.py`. CI only lints `app/`, so they don't block. Untouched.

## Disclosed coverage gaps

Round 3 states explicitly that none of these independently reaches AC14's former
ship-blocking severity:

- **AC18** — advisory-lock concurrency. Needs true concurrency, not a serial test. The
  unique `(org_id, key)` constraint plus transaction rollback is a secondary safety net.
- **AC9-AC11** — guard internals beyond `tests/test_inventory_quantity_guard.py`. The DB
  trigger itself was verified *live* by migration-safety: a direct `INSERT` into
  `inventory_items` without the GUC is rejected by PostgreSQL, and with it set, succeeds.
- **AC31/AC32** — reconcile via-execution (Path B), declared out of scope by the router.
- **`EntityEventSummary.org_id`** — defense-in-depth only; security-audit established the
  pre-fix query was not exploitable. Already fixed:
  `tests/test_inventory.py::test_list_inventory_enriches_items_with_their_own_org_event_summary`
  now covers it (verified 2026-08-08 by findings-sweep).

## Note on the grading rounds

test-evaluator returned `invalid` three times, and was right each time:

- **Round 1** caught that my own docstring falsely claimed every test was red-first, that
  the headline leak test could pass via a no-enrichment response, and that one of its
  assertions was tautological (I asserted the neighbour's process name was absent while
  planting only the *step* id — process-name enrichment follows the *execution* id, so it
  could never have appeared).
- **Round 2** proved by mutation that my `source_output_id` tests guarded nothing: the
  foreign-step case is rejected at step-ownership before membership is ever checked, so
  deleting the membership condition left all three green. It also identified AC20 as an
  *implementation* gap I had filed as mere missing coverage.
- **Round 3** executed mutations against the new batch and found two tests that stayed
  green when the behaviour they named was removed.

Every one of those was a defect that would otherwise have shipped looking like coverage.

## Two incidents during the final step — recorded because they matter

### Five security fixes were silently reverted in the working tree, and a regression test caught it

After the chain finished and `merge-request` was launched, five of the fixes had vanished
from the working tree: the F4 join org-filter and its `and_` import, the F2 `is_finite()`
guard in `set_inventory_item_quantity`, the F6 `inventory_type` enum validation, the
`InvalidOperation` handler in `inventory_dispose_confirm`, and the `EntityEventSummary`
org filter. Nothing had been committed (`HEAD` was still 8d95f83) and the `merge-request`
stage had stopped to ask permission before committing, so this was not a bad commit — the
working tree itself had lost the edits.

**The regression tests did their job.** `test_list_inventory_by_process_id_does_not_match_another_orgs_execution`
failed immediately on the reverted F4 code — the exact scenario it was written for — and
running the rest of `tests/test_inventory.py` surfaced the other four in the same pass.
All five were restored and re-verified: 24/24 inventory regressions green, then the full
suite.

The exact mechanism is **not established**. The stage had written reconstruction artifacts
(`.final_inventory_repo.py`, `.final_backend.py`, `.backend_full.diff`, `.repo_full.diff`)
into the repo root, but the reconstructed copy of `inventory_repo.py` *does* contain both
fixes — so blaming those files would be a guess. What is verified: the fixes were present
at the 752-pass run, absent after the stage ran, and are present and green again now. The
artifacts have been moved out of the repo root; nothing was committed at any point.

The lesson worth keeping: this audit's value was not the fixes, which were reversible in
seconds. It was the tests, which noticed. A reverted fix with no test is indistinguishable
from a fix that was never made — and this is the second time in this audit that the tests
caught a regression the prose would have missed (the first being test-evaluator's mutation
probes).

### One suite error was leftover data, not code

The full run then errored once in `tests/test_org_routes.py::test_delete_own_account_is_rejected`
with `UniqueViolation: Key (name)=(Test Org 127) already exists`. It passed in isolation
and alongside `tests/test_inventory.py`, and reproduced only in the full run.

Cause: `OrganisationFactory` names orgs from a **per-process sequence** (`Test Org {n}`)
while rows persist in the shared test database, so any run whose teardown fails leaves a
row that poisons the next run at that sequence number. Several earlier runs in this audit
failed mid-way (deliberately — the red phase) and left exactly such a row. Purging it
returned the suite to green.

This is pre-existing fragility, not a defect introduced here — `tests/test_inventory.py`
sidesteps it by naming its orgs with a UUID suffix, which is what the factory itself should
do. Routed to **suite-warden**: a shared-DB factory keyed on a per-process sequence is a
flake generator, and it presents as an unrelated failure in whichever test happens to draw
the colliding number.

## Final state

```
uv run pytest tests/ -q
752 passed, 0 failed, 0 skipped in 325s
```
