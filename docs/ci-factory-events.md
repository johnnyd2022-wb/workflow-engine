# CI events to Event Factory

Event Factory (`~/event-factory`, `whistlebird/event-factory`) reacts to CI and merge-request
events. Nothing polls CI.

## What Factory does with them

| Event | Factory's reaction |
|---|---|
| A job fails, or a pipeline fails, on any open MR | Adopts the MR: a `merge-request` agent works on the MR's own branch until its pipeline is green. It pushes to that branch, never opens a second MR and never force-pushes. |
| An MR has merge conflicts | Same adoption; the agent merges the target branch in and resolves the conflicts. |
| A job fails on `main`'s current tip | One `fix-bug` job for `main` being red, at most one at a time. |
| `uv_audit` fails on `main` | One `dependency-update` job. |

Never counted against an MR: `allow_failure` jobs, and `main_green` (it reports `main`'s state,
not the MR's). An MR is left alone when it:

- is labelled **`factory::hands-off`**;
- comes from a fork;
- already has a live Factory agent (that agent gets the CI repair instead).

A finished adoption re-arms only when someone pushes a new commit. Factory never merges;
merging stays a human step.

## How events arrive

1. **GitLab's project webhook** (primary). It sends job, pipeline, MR and push events,
   signed with the webhook secret. No CI change is involved.
2. **`ci/factory_event.sh`** (fallback). Every job runs it from `after_script` (the
   `default:` block in `.gitlab-ci.yml`). It posts only the project, job and pipeline IDs
   and `CI_JOB_STATUS`, with the masked CI variable `FACTORY_CI_TOKEN`. That token can only
   ask Factory to look: Factory reads the job from GitLab with its own access before
   acting, and `CI_JOB_TOKEN` never leaves CI. The script can't fail or noticeably slow a
   job (one 10-second attempt, all errors ignored), and it does nothing while
   `FACTORY_CI_TOKEN` is unset.

A job that defines its own `after_script` replaces the default, so it must end with
`- sh ci/factory_event.sh || true`. `tests/test_factory_event_ci.py` fails if one doesn't.

## Setup

- Factory: set `FACTORY_CI_SIGNAL_TOKEN`, deploy event-factory !4, and enable the skills it
  dispatches:

  ```bash
  factory repo activate workflow-engine --family work \
    --skill merge-request --skill dependency-update --evidence "event-driven CI reactions"
  ```

- GitLab: Settings → CI/CD → Variables → `FACTORY_CI_TOKEN`, with the same value, masked
  and **not** protected (merge-request pipelines run on unprotected branches).
