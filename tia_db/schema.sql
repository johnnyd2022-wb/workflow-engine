-- Test impact analysis (TIA): which lines of which files every test executes, recorded from
-- main's full test run, so a merge request runs only the tests its changed lines can affect.
-- Lives in the bize_dev database (127.0.0.1:8402, CI: host.docker.internal:8402) next to the
-- metrics schema. Applied by `python3 scripts/tia.py migrate` as bize_dev_admin; idempotent.
-- Append-only: CI's bize_dev_rw role can read and insert, never update or delete.
-- See docs/test-impact-analysis.md.

CREATE SCHEMA IF NOT EXISTS tia;

-- Dictionaries, so the 90k-row map stores small integers instead of repeated paths.
CREATE TABLE IF NOT EXISTS tia.tests (
    id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nodeid  text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS tia.files (
    id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    path  text NOT NULL UNIQUE
);

-- One recorded full run of the suite. Written with all of its rows in one transaction, so a
-- run that is visible is complete.
CREATE TABLE IF NOT EXISTS tia.runs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha          text NOT NULL,
    ref          text NOT NULL,
    pipeline_id  bigint,
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    tests        integer NOT NULL,
    failed       integer NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_sha ON tia.runs (sha, id DESC);

-- What each test executed. lines is NULL when the whole file counts as used: a template the
-- test rendered or a static file it served.
CREATE TABLE IF NOT EXISTS tia.test_lines (
    run_id   bigint  NOT NULL REFERENCES tia.runs,
    file_id  integer NOT NULL REFERENCES tia.files,
    test_id  integer NOT NULL REFERENCES tia.tests,
    lines    integer[],
    PRIMARY KEY (run_id, file_id, test_id)
);

-- Outcome and duration of every test in a recorded run: balances parallel workers, estimates
-- a selection's cost, and is the history that spots flaky tests and selection escapes.
CREATE TABLE IF NOT EXISTS tia.results (
    run_id    bigint  NOT NULL REFERENCES tia.runs,
    test_id   integer NOT NULL REFERENCES tia.tests,
    outcome   text    NOT NULL CHECK (outcome IN ('passed', 'failed', 'skipped')),
    seconds   real    NOT NULL,
    PRIMARY KEY (run_id, test_id)
);

-- Every selection a merge request pipeline made (or, in shadow mode, would have made), so a
-- later failure on main can be checked against what the MR skipped.
CREATE TABLE IF NOT EXISTS tia.selections (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    mode              text NOT NULL CHECK (mode IN ('shadow', 'enforced')),
    mr_iid            integer,
    pipeline_id       bigint,
    base_sha          text NOT NULL,
    head_sha          text NOT NULL,
    map_run_id        bigint REFERENCES tia.runs,
    decision          text NOT NULL CHECK (decision IN ('select', 'full', 'none')),
    reasons           jsonb NOT NULL,
    selected_tests    integer NOT NULL,
    selected_seconds  real NOT NULL,
    full_seconds      real NOT NULL,
    tests             text[] NOT NULL
);
CREATE INDEX IF NOT EXISTS selections_by_head ON tia.selections (head_sha);
