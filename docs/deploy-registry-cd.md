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

## Manual setup required (not done by any commit — these are account/infra actions)

1. **Runner tag.** Every deploy-stage job below is tagged `deploy-target` as a placeholder.
   Replace it with whatever tag actually identifies a GitLab Runner with `docker` access to
   the box serving `test-workflow-engine.whistlebird.co.nz` — this repo's runner (see
   `gitlab-runner/` at repo root) appears to already be colocated with that box, based on the
   containers visible from a plain dev shell here, but its real registered tag isn't
   discoverable from the repo itself.
2. **`POSTHOG_PROJECT_API_KEY`** as a masked GitLab CI/CD variable. Local dev resolves this
   from KeePassXC; a CD job can't reach the host's KeePassXC database, so it needs the plain
   value instead. `scripts/deploy_test_simple.sh` already handles both paths (env var first,
   KeePassXC fallback for local use).
3. **`XERO_CLIENT_ID_TEST` / `XERO_CLIENT_SECRET_TEST`** (and the lowercase pair the script
   also sets) as masked CI/CD variables, same reasoning.
4. **GitLab Container Registry** must be enabled for the project (Settings → General →
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
