# Test impact analysis

Merge request pipelines run only the tests a change can affect, chosen from a recorded map
of which lines every test executes. `main` still runs the whole suite on every merge, so
anything a selection misses fails there.

## Why

Before this, `relevant_tests` was about 11.4 of an MR pipeline's 11.8 minutes. Its path rules
fell back to all ~3,200 tests whenever a change touched a file they didn't know: any CSS,
JS or HTML file, `scripts/ui_shots.py`, or a migration. That was 10 of 12 recent MRs.

We replayed the last 40 merges against a measured map:

- The median code-changing merge needs about **0.2 minutes** of tests, against 12.5 for the
  full suite.
- Only changes to code every test runs at startup (`app_factory.py`, `config_loader.py`)
  still need everything.

## How it works

1. **Record (main).** `unit_tests` runs the full suite with per-test coverage
   (`--cov-context=test`, `ci/tia.coveragerc`) and `scripts/tia_probe.py`. The probe adds the
   templates and static files each test renders or serves, and every test's outcome and
   duration. `scripts/tia.py record` writes the run to the `tia` schema of the `bize_dev`
   database (127.0.0.1:8402; CI reaches it as `host.docker.internal:8402` through the
   `BIZE_METRICS_*` variables), in one transaction. The extra cost is about 17% of
   `unit_tests`. A failed recording never fails the job.
2. **Select (merge requests).** `relevant_tests` calls `scripts/tia.py select`. It finds the
   newest recorded `main` run that is an ancestor of the MR's base, diffs the changed files
   from that run's commit to the MR head, and asks the database which tests executed those
   lines:

   | Change | Runs |
   |---|---|
   | Lines of a Python file | the tests that executed those lines (an insertion counts its neighbours) |
   | A template or static file | every test that rendered or served it |
   | A file a test ran in a child process (Node-tested JS, `python script.py`) | the test that started the process |
| A file no test executes (a new file, CI config) | the test modules that name it (JS tests by their runner); none if nothing does, since the full suite gives no signal on it either |
   | A test module | that module |
   | `conftest.py`, `tests/` support files, `pyproject.toml`, `uv.lock`, `app/config/*.ini`, migrations, `ci/setup_database.sh`, test factories | everything |
   | Docs, skills, reports | nothing |

   Selection then merges with `scripts/select_relevant_tests.py`. The path rules still decide
   docs-only skips and which services the job needs (database, Node, browser, server), and
   keep their hand-mapped targets. The map replaces only their full-suite fallback.
3. **Never blocks.** If the database is unreachable, there's no recorded ancestor run, or
   anything goes wrong, the job uses the path rules' own targets. Every decision is logged
   to `tia.selections` with its reasons, map run and estimated seconds.

## How accurate it is

It was measured with mutation checks on places recent merges actually changed:

1. One small behaviour-changing edit per site, on top of the recorded `main` commit: a flipped comparison, `and`/`or` swapped, a constant or return value changed, an id or text removed from markup.
2. The **full** suite runs on each mutant, and its failures are the ground truth.
3. Any failing test the selector didn't pick is an escape.

| Round | Mutants | Detected by the full suite | Failing tests | Escapes |
|---|---|---|---|---|
| 1: 30 Python, 6 templates, 4 JS | 40 | 20 | 132 | **0** |
| 2: every Node-tested JS file, 12 new Python | 22 | 8 | 24 | **0** |

- **Selections stayed small.** The typical one was 1–20 tests, often exactly the failing ones (13 of 13, 11 of 11). The largest was 346, for `app/core/backend/event_writer.py`, which almost every write path calls. No mutant needed the full suite.
- **Templates and most JS aren't checked by the Python suite.** No template mutant and no JS mutant outside the Node-tested files failed even under the full suite. Selection can't add signal the suite doesn't have; that's the browser tests' job.

`main` keeps checking accuracy on real changes after every merge: `scripts/tia.py escapes` lists any test that failed on `main` which an MR merged since the previous run skipped.

## Checking it

```bash
python3 scripts/tia.py status          # newest recorded runs, selection counts
```

```sql
-- what an MR ran and why
SELECT mr_iid, decision, selected_tests, round(selected_seconds) AS s, round(full_seconds) AS full, reasons
FROM tia.selections ORDER BY id DESC LIMIT 20;
```

**Escapes.** A test that fails on `main` when an MR's selection skipped it is a selection
escape. Find it by joining the failing `tia.results` row to that MR's `tia.selections.tests`.
Event Factory's red-`main` handling already turns the failure into a fix job.

## Admin

`python3 scripts/tia.py migrate` applies `tia_db/schema.sql` and `tia_db/grants.sql` as
`bize_dev_admin` through `docker exec`. It's idempotent. CI's `bize_dev_rw` role can only
read and append.

## Next

- Run the full-suite paths (`main`, global-input MRs) on pytest-xdist workers, each with its
  own database cloned from a migrated template.
- Skip tests whose recorded inputs are byte-identical to a passing run (a result cache).
- Record MR file claims, to warn about overlapping MRs before they conflict.
