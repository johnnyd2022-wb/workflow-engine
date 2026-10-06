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
Applied 2026-10-06 in `/etc/gitlab-runner/config.toml` inside the `gitlab-runner` container
(`~/.config/gitlab-runner/config.toml` on the host). The runner reloads this file on its
own, so no restart was needed and running jobs were not interrupted. The previous file is
kept beside it as `config.toml.bak-2026-10-06`.

- [x] **`concurrent` raised from 3 to 6.** Six jobs at about 1 to 1.5 GB each fit in WSL's
      15.5 GB with the app and databases already running. Going higher needs more memory
      for WSL (`.wslconfig`, then a WSL restart).
- [x] **Images are no longer re-pulled every job** (`pull_policy = ["if-not-present"]` on
      the Docker runner). A new base image now needs a deliberate `docker pull` on the host,
      for example `docker pull python:3.14-bookworm`.
- [x] **uv downloads are cached across jobs.** The host directory
      `~/.cache/gitlab-runner-uv` is mounted at `/uv-cache`, with `UV_CACHE_DIR=/uv-cache`
      and `UV_LINK_MODE=copy` set for every job on this runner.

### Second MR: pre-built image and parallel stages
- [x] **Pre-built CI image.** `ci/Dockerfile.ci` holds uv, the locked dependencies, the
      PostgreSQL client, Node.js 20 and Chromium. The eight Python jobs that installed these
      on every run now use `$CI_REGISTRY_IMAGE/ci:$CI_IMAGE_TAG`. Measured inside the image:
      dependency setup about 1 second instead of 10, Chromium already present.
  - The tag is a hash of `ci/Dockerfile.ci`, `pyproject.toml` and `uv.lock`
    (`scripts/ci_image_tag.py`), because the runner caches images and a reused tag would
    never be re-pulled.
  - A stale image is safe. Every job still runs `uv sync`, which installs only the
    difference, and every install step is skipped only when `CI_PREBUILT` is set, so the
    jobs also still run on a bare `python` image.
  - After a dependency or Dockerfile change: `main` builds the new image
    (`ci_image_build`), `ci_image_current` shows a warning until `CI_IMAGE_TAG` in
    `.gitlab-ci.yml` is bumped to the tag it prints. Bump it only after `main` has built
    the image; a tag that does not exist yet fails every job at image pull.
  - The first image (`1ec1fed1ea484a7e`) was built and pushed by hand, since nothing on
    `main` could build it before this change merged.
- [x] **`main`'s security and migration checks no longer wait for its tests.** Those jobs
      carry `needs: []` and start with the pipeline. Build and deploy still wait for every
      earlier stage. On `main` this takes the scans and the migration check off the end of
      the ten-minute suite, which is also how long each merge request's `main_green` waits.

### Later, as its own piece of work
- [ ] **Run the full suite in parallel** (pytest-xdist). Expected: 10 minutes to perhaps 3.
      Blocked on test isolation: the suite shares one database and 99 assertions across 20
      test files check exact row counts, so each worker needs its own database first.
      Land it in stages: per-worker databases with parallelism off, then parallel on merge
      requests, then on `main`.

## Not worth doing
- More runner slots than memory allows: jobs would start sooner and then swap.
- Dropping `mr_e2e` or the full suite on `main`: they are the gates, not the waste.
