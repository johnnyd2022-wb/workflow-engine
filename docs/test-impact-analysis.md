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
   | A file no test executed in-process (Node-tested JS, a new file) | the test modules that name it; none if nothing does, since the full suite gives no signal on it either |
   | A test module | that module |
   | `conftest.py`, `tests/` support files, `pyproject.toml`, `uv.lock`, `app/config/*.ini`, migrations, `ci/setup_database.sh`, test factories | everything |
   | Docs, skills, reports | nothing |

   Selection then merges with `scripts/select_relevant_tests.py`. The path rules still decide
   docs-only skips and which services the job needs (database, Node, browser, server), and
   keep their hand-mapped targets. The map replaces only their full-suite fallback.
3. **Never blocks.** If the database is unreachable, there's no recorded ancestor run, or
   anything goes wrong, the job uses the path rules' own targets. Every decision is logged
   to `tia.selections` with its reasons, map run and estimated seconds.

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
