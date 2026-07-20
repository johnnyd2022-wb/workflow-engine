# Registry-backed CD: build once, promote what's proven

## Why this exists

Before this, `scripts/git_workflow.sh` / `scripts/run_test.sh` / `scripts/deploy_test_simple.sh`
all built the Docker image **on the deploy target itself**, from whatever was checked out at
that moment. There was no registry, no immutable artifact, and no way to prove the thing
running in test was the thing CI had actually tested — CI and deploy were two separate,
unconnected processes that happened to use the same Dockerfile.

This flow decouples them: CI builds and pushes one immutable, SHA-addressed image; CD pulls
*that exact image* and never rebuilds. "Ship what was tested" is enforceable because the
deploy step is a `docker pull <sha>`, not a second build that could silently diverge.

## The pipeline (all `main`-only, after CI's `test`/`security`/`migrations` stages pass)

```
docker_build_publish          build+push $CI_REGISTRY_IMAGE/app:test-<sha> and :prod-<sha>
        |
deploy_test                   pull :test-<sha>, run it as workflow-engine-test
        |
cd_e2e                        Playwright against the just-deployed container (E2E_BASE_URL)
        |
   pass ----------------------------------------- fail
        |                                           |
promote_test_stable                    rollback_test_on_failure
(tag :test-<sha> -> :test-stable)      (redeploy whatever :test-stable
                                         already points to -- untouched,
                                         since promotion never ran)
```

`:test-stable` only ever moves forward in `promote_test_stable`, and only after a real
browser has exercised the deployed container and passed. A broken candidate never gets
promoted, so a failure can never leave `:test-stable` pointing at something broken — rollback
is just "redeploy the tag that was never advanced."

## Why one repository, not one tag

`$CI_REGISTRY_IMAGE/app` is a single image repository with environment-prefixed tags
(`test-<sha>`, `prod-<sha>`, `test-stable`) — not a shared registry with unrelated images
dumped into it as tags of a generic name, and not a single `:latest` tag a deploy blindly
trusts without knowing what SHA it actually is. Every deploy pulls a specific, immutable tag.

## Known scope limit: test and prod are parallel builds, not one promoted artifact

`docker_build_publish` builds **two** images from the same commit — `Dockerfile.multi`'s
`test` and `production` targets differ (baked-in `ENVIRONMENT`, `EXPOSE`d port, and a
hardcoded `HEALTHCHECK` port per stage). True single-artifact promotion (the same image byte-
for-byte moving from test to prod, the strongest version of "ship what was tested") would
require unifying those two targets into one image that takes `ENVIRONMENT`/port purely from
`-e` at `docker run` time, plus a `HEALTHCHECK` that reads the port dynamically. That's a
real, behavior-affecting Dockerfile change deserving its own review — flagged here rather than
done silently. Until then, "promoted" means: built from the same commit, in the same
pipeline, moments apart — a large improvement over today's host-side rebuild, but not
byte-identical to what gets shipped to prod.

## Runner setup — done

The `deploy-target` tag is a real, registered runner, not a placeholder: a second
`[[runners]]` entry (project runner id `54420399`) added to this project's existing
self-hosted `gitlab-runner` container, alongside the original `docker`-executor one
(`biz-e`, id `53089900`, untouched).

It's a **separate runner definition, not a converted one**, deliberately — the existing
runner's `docker` executor is what every other job here (`ruff`, `unit_tests`, `semgrep`,
etc.) relies on for `image:` isolation, and `image:` is silently ignored under `shell`
executor. Converting the existing runner wholesale would have broken all of those. The
new one uses `executor = "shell"` instead: the `docker` executor spins up a **fresh
container per job**, which by this runner's config only mounts `/cache`, not the host's
`/var/run/docker.sock` — no path to the real containers a tunnel/DNS actually points at.
`shell` executor runs job scripts directly in the runner's own environment, which has the
host socket bind-mounted in (`/var/run/docker.sock:/var/run/docker.sock`).

Two things the runner container needed that its base image doesn't ship with, found by
actually trying to run a job rather than assuming the socket mount was sufficient:
- **`docker` CLI itself** — `gitlab/gitlab-runner:latest` has the socket but no client
  binary. Installed via `apt-get install docker.io` inside the running container. This is
  a live modification to the container's writable layer, not baked into the image — if
  this container is ever removed and recreated from scratch, this step needs repeating.
- **`DOCKER_API_VERSION=1.43`** as a runner-level `environment` entry in `config.toml`.
  The apt-installed CLI (29.1.3) defaults to a newer Docker API than the host daemon
  (24.0.5, max 1.43) supports, and — unlike this machine's own host-side `docker` CLI,
  which auto-negotiates down — errors instead of downgrading automatically.

Still open: `XERO_CLIENT_ID_TEST` / `XERO_CLIENT_SECRET_TEST` (and the lowercase pair the
script also sets) as masked CI/CD variables, if the deployed test container needs a
working Xero OAuth connection. Optional in the same sense PostHog is below — omit them
and Xero connect just won't complete; nothing else breaks.

`POSTHOG_PROJECT_API_KEY` is **deliberately not wired up in CD at all** — it's genuinely
optional (an empty key just means client-side RUM doesn't initialize;
`config_loader.rum_posthog_api_key` falls back to `""`, no crash) and CD has no KeePassXC
to resolve it from. `scripts/deploy_test_simple.sh` only attempts KeePassXC resolution
when run locally with no image ref; CD never requests it and the container just runs
without that one env var.

**GitLab Container Registry** must be enabled for the project (Settings → General →
Visibility → Container Registry). `CI_REGISTRY`, `CI_REGISTRY_USER`,
`CI_REGISTRY_PASSWORD`, and `CI_REGISTRY_IMAGE` are then auto-populated by GitLab for every
job — no separate token needed for the registry itself, unlike Renovate/Socket.

## Production deploy is deliberately untouched

`docker_build_publish` also builds and pushes `:prod-<sha>` on every main merge, so the
artifact is there — but nothing in this pipeline auto-deploys it. Production still goes
through `scripts/git_workflow.sh prod` (build-locally, tag, manual trigger), per the existing
`deploy-runner` skill flow. Auto-deploying test on every green merge was an explicit decision;
auto-deploying *production* the same way is a materially bigger risk call that needs its own
explicit sign-off, not a side effect of this change. Wiring `:prod-stable` promotion the same
way test does it is the natural next step whenever that sign-off happens — the registry side
is already in place for it.

## Local dev is unaffected

`scripts/deploy_test_simple.sh` still works exactly as before when run with no arguments — it
builds locally, same as always. The registry-pull path only activates when it's given an
image reference as `$1` (what the CD jobs above do).
