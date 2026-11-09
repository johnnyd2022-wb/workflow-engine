-- Biz-E development metrics store (database `bize_dev`, schema `metrics`).
--
-- Replaces the append-only repo files that conflicted on every MR:
--   .agents/metrics/runs.jsonl, .agents/metrics/outcomes.jsonl  -> skill_runs, skill_outcomes
--   .agents/reports/perf/last-run.json                          -> perf_runs, perf_results
--
-- Idempotent: scripts/metrics_db.py migrate re-applies it safely. Rows are append-only;
-- the CI/agent role gets INSERT + SELECT only, so a runaway job cannot rewrite history.

CREATE SCHEMA IF NOT EXISTS metrics;
SET search_path = metrics;

-- One row per skill run (who ran, what they found, verdict). Joins to skill_outcomes on ref.
CREATE TABLE IF NOT EXISTS skill_runs (
    id          bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    skill       text NOT NULL CHECK (skill <> ''),
    run_type    text NOT NULL CHECK (run_type IN ('chained', 'scheduled', 'interactive')),
    scope       text,
    findings    integer NOT NULL DEFAULT 0 CHECK (findings >= 0),
    verdict     text NOT NULL CHECK (verdict IN
                    ('clean', 'patched', 'findings-open', 'could-not-reproduce', 'error', 'skipped')),
    ref         text,               -- MR ref (!123) or branch name: the join key
    duration_s  double precision,
    notes       text,
    commit_sha  text,
    mr_iid      integer,
    pipeline_id bigint
);
-- Makes legacy imports and spool flushes idempotent (same instant + skill + ref == same run).
CREATE UNIQUE INDEX IF NOT EXISTS skill_runs_identity
    ON skill_runs (ts, skill, (coalesce(ref, '')));
CREATE INDEX IF NOT EXISTS skill_runs_ref ON skill_runs (ref);

-- One row per resolved run/MR. The latest row per ref wins (an MR closed, reopened and
-- merged scores as merged), so ordering is (ts, id).
CREATE TABLE IF NOT EXISTS skill_outcomes (
    id      bigserial PRIMARY KEY,
    ts      timestamptz NOT NULL DEFAULT now(),
    ref     text NOT NULL CHECK (ref <> ''),
    outcome text NOT NULL CHECK (outcome IN ('merged', 'closed', 'amended', 'escaped', 'superseded')),
    skill   text,
    notes   text
);
CREATE UNIQUE INDEX IF NOT EXISTS skill_outcomes_identity
    ON skill_outcomes (ts, ref, outcome, (coalesce(skill, '')));
CREATE INDEX IF NOT EXISTS skill_outcomes_ref ON skill_outcomes (ref, ts, id);

-- One row per perf test run, keyed to the commit / MR / pipeline that produced it.
CREATE TABLE IF NOT EXISTS perf_runs (
    id          bigserial PRIMARY KEY,
    measured_at timestamptz NOT NULL DEFAULT now(),
    commit_sha  text NOT NULL,
    branch      text,
    is_main     boolean NOT NULL DEFAULT false,   -- baselines are built only from these
    mr_iid      integer,
    pipeline_id bigint,
    job_id      bigint,
    source      text NOT NULL DEFAULT 'local' CHECK (source IN ('local', 'ci'))
);
CREATE INDEX IF NOT EXISTS perf_runs_main ON perf_runs (measured_at DESC) WHERE is_main;
CREATE INDEX IF NOT EXISTS perf_runs_commit ON perf_runs (commit_sha);

-- One row per (run, route, metric). `queries` is deterministic and gates; timings are noisy.
CREATE TABLE IF NOT EXISTS perf_results (
    run_id       bigint NOT NULL REFERENCES perf_runs (id) ON DELETE CASCADE,
    route        text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('api', 'page')),
    metric       text NOT NULL CHECK (metric IN ('backend_ms', 'queries', 'lcp_ms')),
    value        double precision NOT NULL,
    over_budget  boolean NOT NULL DEFAULT false,
    over_ceiling boolean NOT NULL DEFAULT false,
    PRIMARY KEY (run_id, route, metric)
);
CREATE INDEX IF NOT EXISTS perf_results_lookup ON perf_results (route, metric, run_id DESC);

-- Rolling baseline: median of the last 20 main-branch runs per route + metric. A single
-- stored number would flap on a noisy runner; the median over recent main does not, and an
-- MR can never move its own goalposts because only is_main runs feed it.
CREATE OR REPLACE VIEW perf_baseline AS
WITH recent AS (
    SELECT id FROM perf_runs WHERE is_main ORDER BY measured_at DESC, id DESC LIMIT 20
)
SELECT r.route,
       r.metric,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.value) AS median,
       count(*)                                              AS samples
FROM perf_results r
JOIN recent ON recent.id = r.run_id
GROUP BY r.route, r.metric;
