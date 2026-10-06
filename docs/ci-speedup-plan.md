# CI speed-up plan

Started 2026-10-06. Measured on merge-request pipelines 2916684470 and 2916743651 and
`main` pipeline 2914902715, on the single local runner (`biz-e`, Docker executor, 20 cores,
15.5 GB given to WSL of the host's 32 GB).

## Where the time went

| What | Measured |
| --- | --- |
| Waiting for a runner slot when two pipelines overlap | about 5 minutes per job (3 slots, 14 jobs per merge-request pipeline) |
| Full test suite (`relevant_tests` full mode, `unit_tests` on `main`) | 10.5 minutes, 9.5 of them pytest on one core |
| Browser smoke (`mr_e2e`) | 111 seconds for 10 seconds of tests; the rest installs dependencies, system packages and Chromium |
| Every other Python job | about 10 seconds installing uv and syncing dependencies before it starts work |
| Pulling the job image | 4 to 10 seconds per job (`pull_policy` defaults to `always`) |
| Duplicate pipelines | every push to a merge-request branch started a branch pipeline (an 86-second SAST scan) as well as the merge-request pipeline |

## Steps

Status: `[ ]` to do, `[x]` done.

### This MR: CI configuration
- [x] **One pipeline per push.** `workflow:rules` in `.gitlab-ci.yml` skips the branch
      pipeline when the branch has an open merge request. The SAST scan (`semgrep-sast`),
      which only ran on branch pipelines, now runs in the merge-request pipeline instead.
      `main`, tags, schedules and branches with no merge request yet are unchanged.
- [x] **Cancel superseded merge-request pipelines.** Jobs are `interruptible` by default,
      so a new push cancels the previous pipeline's running jobs rather than leaving them
      on the runner. `main` opts out (`auto_cancel: on_new_commit: none`): a later merge
      never cancels the release pipeline or a deploy.

### Runner configuration (on the runner host, not in the repository)
Both need a runner restart, which kills jobs in flight, so do them when nothing is running.

- [ ] **Raise `concurrent` from 3 to 6.** Six jobs at about 1 to 1.5 GB each fit in WSL's
      15.5 GB with the app and databases already running. Going higher needs more memory
      for WSL (`.wslconfig`, then a WSL restart).
- [ ] **Stop re-pulling images and cache uv downloads.** `pull_policy = ["if-not-present"]`
      on the Docker runner, and a shared uv cache volume with `UV_CACHE_DIR` pointing at it.
      Images then need a deliberate `docker pull` to pick up a new base image.

### Later, as their own pieces of work
- [ ] **Pre-built CI image** with uv, the locked dependencies, the PostgreSQL client and
      Chromium installed. Expected: `mr_e2e` from about 110 to about 30 seconds, and about
      10 seconds off each of eight other jobs. The image must be rebuilt when `uv.lock`
      changes, so it needs a build job and a tag derived from the lockfile.
- [ ] **Run the full suite in parallel** (pytest-xdist). Expected: 10 minutes to perhaps 3.
      Blocked on test isolation: the suite shares one database and some tests assert global
      row counts, so each worker needs its own database first.
- [ ] **Let `main`'s security and migration stages run alongside its tests** (`needs:`),
      so the release pipeline, which every merge request's `main_green` waits on, finishes
      sooner.

## Not worth doing
- More runner slots than memory allows: jobs would start sooner and then swap.
- Dropping `mr_e2e` or the full suite on `main`: they are the gates, not the waste.
