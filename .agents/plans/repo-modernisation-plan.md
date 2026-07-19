# Repo Modernisation Plan

Owner: Johnny · Created: 2026-07-19 · Target repo: `gitlab.com/whistlebird/workflow-engine`

Five workstreams. Each is independently shippable as its own MR — do them in the
recommended order (§6) so the dependency-scanning churn settles before we bolt on
Renovate and CD. Checkboxes are the working list.

**Overall status (2026-07-19): all five branches built and committed, locally verified
where verification didn't require credentials or a real pipeline run.** §4, §1, §3, §5
are code-complete. §2 (Socket) is prepped but genuinely blocked on you creating a
socket.dev account/token. None of the five branches have been pushed or opened as MRs
yet — that's the next step, and needs your go-ahead since pushing/opening MRs is
visible outside this session. See each section for what got found and fixed along the
way (the datetime scope was 2x the original estimate; two doc/reality gaps got fixed
as prerequisites — Renovate's pre-commit manager and the E2E suite's `E2E_BASE_URL`).

---

## Review — what's actually here today

| Area | Current state | Implication |
|---|---|---|
| CI platform | GitLab.com, **self-hosted runner** (`gitlab-runner/`), scheduled pipelines already used (`only: schedules`) | Renovate-as-CI-job is a natural fit; **Dependabot is not an option** (GitHub-only) |
| CI stages | `test`, `security`, `migrations`. **No deploy stage.** | CD is greenfield — clean slate |
| Dependency CVEs | `pip_audit` job (blocking): `uv pip install pip-audit; uv run pip-audit --strict` | Works, but pip-audit is redundant with uv's new native scanner |
| Lockfile freshness | `check_dependency_updates` runs `uv lock --check` (schedules/MR, `allow_failure`) | Good hook point; Renovate supersedes the "is it stale" question |
| Deploy today | `git_workflow.sh test/prod` builds the image **on the host** (`docker build --target …`) and `docker run`s it. No registry. Prod gets a git tag; test gets nothing | No immutable artifact, no real rollback, CI and deploy are coupled through the host |
| E2E / Playwright | `tests/e2e/*` exists (14 files), `pytest-playwright` in dev deps, auto-skips when chromium absent — **but not wired into CI at all** | We can move it onto CD without disturbing the CI test job |
| `utcnow()` | 41 call sites across 15 files; some files already use `now(UTC)` | Mixed codebase; needs per-call-site care |
| Timestamp columns | `DateTime(timezone=True)` (TIMESTAMPTZ); containers run `Pacific/Auckland` TZ | **Latent bug** — see §4 |
| `requirements.txt` | Stale (`Flask==2.3.3`, `sqlalchemy==2.0.19`) — not the source of truth (pyproject/uv.lock are) | Two skills still `pip-audit -r requirements.txt`; must be cleaned up with the pip-audit removal |
| `uv` version | Local `uv 0.9.13` **does not have `uv audit`** (returns "unrecognized subcommand"); CI `pip install uv` pulls latest | Version skew risk — must pin (see §1) |

### Cross-cutting caveats found during review
- **`uv audit` is in preview / unstable** (shipped by Astral June 2026, OSV-backed, flagged as subject to breaking changes). Fine to adopt, but a *blocking* gate on an unstable command is a footgun — see §1 gating decision.
- **Renaming `pip_audit` ripples into the skill layer.** `dependency-update`, `security-audit`, and `ci-gate` skills plus `.agents/ci-gate-setup.md` / `autonomy.md` reference the `pip_audit` job by name and `pip-audit -r requirements.txt` by command. Memory note *"pip_audit CI job is now blocking → route CVE failures to dependency-update"* points at that job. If we rename/remove it, those references must move in the same MR or the skills silently point at nothing.
- **Socket is an external SaaS.** It uploads your dependency manifests to socket.dev and needs an API token (paid tier for private-repo org features). That's a data-egress + cost decision, not just a YAML change — flagged for your sign-off in §2.

---

## 1. Replace `pip-audit` with `uv audit`

**Goal:** single uv-native CVE/malware gate; drop the pip-audit install and the stale requirements.txt path.

**STATUS: DONE** (branch `chore/uv-audit-migration`, commit `3e9f5e1`).

- [x] Pinned uv at **0.11.29** (confirmed via an isolated pip install this is the version where `uv audit` exists — local system uv was 0.9.13 and lacks it) as a top-level `UV_VERSION` CI variable, referenced by every `pip install "uv==${UV_VERSION}"` line in `.gitlab-ci.yml`, not just the audit job — one source of truth for the whole pipeline's uv version, not just the job that strictly needed it.
- [ ] Bump **local** `uv` to 0.11.29+ — this is Johnny's own machine, not something a commit can do; CLAUDE.md now documents the requirement and how to check/upgrade.
- [x] `pip_audit` job → `uv_audit`: `uv audit --frozen --output-format json --preview-features audit-command,json-output`, JSON artifact at `.agents/reports/security/uv-audit.json`. Two undocumented preview-flag warnings on stderr required `--preview-features audit-command,json-output` (comma-separated, both needed) to suppress — found by running it, not by assuming the `--help` text was complete.
  - **Blocking from day one** (`allow_failure: false`), per the decision above.
- [x] Report artifact wired as a GitLab CI `artifacts:` entry (`when: always`), so `dependency-update` has a findings file to consume — same role `.agents/reports/*/pip-audit.json` used to serve.
- [x] pip-audit removed everywhere: the `.gitlab-ci.yml` job rewritten (not just the `uv pip install pip-audit` line); `requirements.txt` deleted (grep-confirmed nothing else read it); `security-audit/SKILL.md`, `dependency-update/SKILL.md`, `ci-gate/SKILL.md`, `entrypoint/skill-index.md`, `.agents/autonomy.md` updated to name `uv audit`/`uv_audit`. **`.agents/ci-gate-setup.md` deliberately left alone** — it's a dated (2026-07-12) historical record of that setup pass; rewriting "pip_audit was added" after the fact would misrepresent what actually happened. `.claude/takeaway/` mirrors also left alone (skill-smith-owned export snapshots, not hand-maintained sources).
- [x] Memory note update: flagged for a follow-up outside this session (memory lives across conversations, not in this repo's diff) — the note should now say `uv_audit`, not `pip_audit`.
- [x] Verified: `uv audit --frozen` against the real `uv.lock` (82 packages, 0 vulnerabilities, exit 0) using the pinned 0.11.29; separately confirmed exit 1 + correct JSON shape against a deliberately vulnerable throwaway project (`requests==2.6.0`, 10 known CVEs) before trusting the job design.

> Note: pip-audit uses the PyPA Advisory DB (+OSV); `uv audit` is OSV-only today. Coverage is *close* but not identical — worth re-checking once `uv audit` leaves preview.

---

## 2. Socket — supply-chain behaviour analysis (zero-day / proactive layer)

**Goal:** catch malicious *behaviour* (install-time network calls, obfuscation, telemetry, exfil) that CVE scanners miss, at PR time. This is additive to §1, not a replacement — different threat model.

**Cost path (decided: start Free):** Free tier = 1K scans/mo + all 70+ behavioural risk
types — this *is* the zero-day/behavioural gate we want, $0. Team ($25/seat/mo, ~$20 annual)
adds reachability analysis + Slack. **Business ($50/seat/mo, ~$40 annual) adds SBOM generation
+ SSO/SAML** — the two things a paying-customer compliance ask (SBOM request, enterprise SSO)
will eventually force. Plan: ship on Free now; upgrade to Business only when a customer/compliance
requirement demands SBOM or SSO. No blocker to starting.

**STATUS: prepped as far as possible without credentials** (branch `chore/socket-supply-chain-scanning`, commit `30f2787`). **Blocked on you** for the two items only a human/account-owner can do (see below) — everything else is done.

- [ ] Create socket.dev org (Free tier) + API token; add `SOCKET_SECURITY_API_KEY` as a **masked, protected** GitLab CI/CD variable (never in the repo). **← your action, not automatable.**
- [x] Added `socket_security` job to the `security` stage. Real CLI entrypoint confirmed to be `socketcli` (not the `socketsecurity` package name itself — checked via an isolated install rather than assumed). Diff-based scan using GitLab's own predefined variables (`CI_PROJECT_PATH`, `CI_COMMIT_REF_NAME`, `CI_COMMIT_SHA`, `CI_MERGE_REQUEST_IID` guarded with `${VAR:+...}` since it's unset outside MR pipelines), JSON report as a build artifact.
  - `allow_failure: true` for the soak period, as decided.
- [x] Block policy documented in the job comment: soak first, decide per-alert-tier once real findings exist — can't meaningfully pre-decide severity tiers without having seen this repo's actual alert mix yet.
- [x] `docs/supply-chain-security.md` written: uv_audit (reactive, CVE database) vs Socket (proactive, behaviour) division of labour, plus the pricing tier breakdown.
- [ ] Verify against a known-bad fixture — **cannot do without the API token**; this is the one verification step genuinely blocked on your sign-off, not something more digging would unblock.

---

## 3. Renovate — automated dependency management

**Recommendation: Renovate, self-hosted as a scheduled GitLab CI pipeline. Not Dependabot.**

Why: Dependabot only runs on GitHub — you're on GitLab, so it's out. Renovate is the
GitLab-native answer, natively understands **uv** (updates both `pyproject.toml` and
`uv.lock`), and you already run scheduled pipelines, so the operational model is one you
have. Run it as a **CI job on a schedule** (not the Mend hosted app) to keep everything
inside your own runner and secrets — no third-party app with repo write access.

**STATUS: DONE** (branch `chore/renovate-setup`, commit `7c3519d`).

- [x] Added `renovate.json` at repo root (`extends: ["config:recommended", ":enablePreCommit"]`). The `:enablePreCommit` addition wasn't in the original plan — Renovate's pre-commit manager turns out to be **opt-in, disabled by default even under `config:recommended`** (the maintainers disabled it indefinitely over a design disagreement with the pre-commit project). Found this by dry-running and seeing 0 pre-commit deps detected despite a working `.pre-commit-config.yaml`, not by reading docs first.
  - Grouping done: non-major bumps grouped together (still gated by the full pipeline); majors stay separate; Docker base image and pre-commit hooks get their own groups.
  - `dependencyDashboard: true` set.
- [x] Added a `renovate` scheduled job (`only: schedules`, `allow_failure: true` since it never gates an MR). **Needs `RENOVATE_TOKEN` (masked CI variable) and a GitLab pipeline schedule targeting this job — both account-level, called out explicitly in the job's comment rather than silently assumed done.**
- [x] `check_dependency_updates` kept, not renamed in this branch (the `lockfile_consistency` rename lives on the `chore/uv-audit-migration` branch/commit `3e9f5e1`, since it's really part of the uv_audit workstream's cleanup — the two branches will need reconciling at merge time, noted below).
- [x] Renovate's own MRs will run the full pipeline automatically (no special config needed — GitLab treats them as ordinary MRs).
- [x] Verified via `renovate-config-validator` (config validates cleanly) **and** a local dry-run (`--platform=local --dry-run=extract`, with `RENOVATE_CONFIG_FILE` pointed explicitly at `renovate.json` since `--platform=local` doesn't auto-discover repo config — a real gotcha that produced a false "it just works with defaults" result on the first attempt): confirmed `pep621` manager picks up `pyproject.toml`/`uv.lock` (27 deps), `dockerfile` manager picks up `Dockerfile.multi`, and `pre-commit` manager picks up `.pre-commit-config.yaml` (2 pinned hooks) once `:enablePreCommit` was added.

**Merge-order note:** this branch and `chore/uv-audit-migration` both touch `.gitlab-ci.yml`'s `check_dependency_updates`/`lockfile_consistency` job — expect a small conflict there when both land; resolve by taking the rename plus this branch's `renovate` job addition.

---

## 4. `datetime.utcnow()` → timezone-aware (`datetime.now(UTC)`)

**This is a correctness fix, not just warning cleanup.** Columns are `DateTime(timezone=True)`
(TIMESTAMPTZ) and containers run `Pacific/Auckland`. A **naive** `utcnow()` written into a
TIMESTAMPTZ column is interpreted by psycopg2 as *session-local* (NZ) time, not UTC — so the
stored instant is currently wrong by the NZ↔UTC offset for any code path relying on the DB to
localise. Moving to aware `now(UTC)` fixes that. The trap: mixing aware and naive datetimes in
a comparison raises `TypeError`, so call sites must be converted *coherently*, not piecemeal.

**STATUS: DONE** (branch `chore/datetime-utcnow-migration`, commits `c6c306d` + `dc2a4cf`).

Scope corrected during execution: the original 41/15 estimate only counted *called*
`datetime.utcnow()` sites; it missed the bare `default=datetime.utcnow` / `onupdate=…`
callable references used in SQLAlchemy `Column(...)` defaults, which don't match a
`utcnow()` grep (no parens). True scope: **85 call sites / 40 files.**

- [x] Inventoried every call site into three buckets:
  - **A — Column defaults** (45 sites, ~25 models): moved to a shared `utc_now()` helper (`app/core/utils/time.py`) used as the bare callable — a lambda repeated 45 times across 25 files was worse than one function; no Alembic migration needed since `default=`/`onupdate=` are Python-side, not server defaults.
  - **B — Comparisons / arithmetic** (`session_security.py`, `auth_routes.py` — `last_activity_at`, `pending_2fa_created_at`): write and read/compare sides are self-contained (round-trip through the same Flask session-cookie keys, not the DB), converted together to `datetime.now(UTC)`. Existing `except (ValueError, TypeError)` handling in both files already degrades a stale naive cookie gracefully (timer reset, not a 500) — no separate migration handling needed.
  - **C — Plain writes to aware columns** (~30 sites: `wastage_repo`, `crm_task_repo`, `xero_*_repo`, `crm_service`): swapped to `utc_now()`.
  - Plus a format-string edge case: `api_helpers.py` manually appended `+ "Z"` to a naive `isoformat()`; an aware `isoformat()` already appends `+00:00`, so this now reads `.isoformat().replace("+00:00", "Z")` to avoid double-suffixing.
- [x] Confirmed nothing reads these values back assuming naive UTC — `backend.py`/`inventory_upload_routes.py`'s `strftime("...Z")` calls are unaffected by tz-awareness (literal `Z`, not `%Z`); `auth_service.py`'s session `created_at` is informational only, not compared.
- [x] Converted and verified as two commits (code, then plan doc) rather than per-bucket — full suite run was cheap enough (170s) to run once at the end rather than per bucket.
- [x] Added `.semgrep/rules/correctness.yml` (`no-naive-utcnow`, blocking) — verified it fires on a known-bad fixture and is silent on the migrated `app/`. (Went with semgrep over the ruff `DTZ` family — enabling all of `DTZ` risked flagging unrelated pre-existing naive-datetime call sites repo-wide, out of scope for this fix.)
- [x] Verified: 426 passed, 30 skipped, **0 DeprecationWarnings** (was ~11k); ruff clean; semgrep clean.

Process note for next time: a plain `grep -rn "utcnow()"` (with parens) undercounts — always also grep the bare form (`datetime\.utcnow\b`) to catch `default=`/`onupdate=` references. Also: two files (`two_factor_backup_code.py`, `auth_service.py`) hit a real gotcha — their CRLF line endings meant a `sed 's/^from datetime import datetime$/.../'` anchor silently failed to match (the line actually ends `datetime\r`), so `ruff --fix` later removed the now-unused old import without adding the new one, producing `F821`s that had to be hand-fixed. `git diff`'s "CRLF will be replaced by LF" warning is not decorative — check for it before trusting a `sed` anchor-match count in a file it fires on. Similarly, a "does `datetime` appear anywhere else in this file" check must include bare type-hint usage (`recorded_at: datetime | None`), not just `datetime.xxx` — a case-sensitive/dot-suffixed grep alone will miss it.

---

## 5. Deploy stage — publish to GitLab registry + decoupled CD with Playwright gate & rollback

**Goal:** CI proves the code; CD ships an **immutable, pre-tested image** to test, proves it
works in a real browser (Playwright) against the deployed env, and can **roll back to the last
known-good image** — never deploying a failing artifact.

**STATUS: DONE** (branch `chore/registry-cd-pipeline`, commits `c4b9958` + `74856d4`). Full design writeup lives in `docs/deploy-registry-cd.md` — this section records what changed and what got found along the way.

### 5a. Build & publish (end of CI)
- [x] Added a `build` stage after `migrations`. `docker_build_publish` job pushes to **one repository** `$CI_REGISTRY_IMAGE/app`, environment-prefixed immutable tags (`test-<sha>`, `prod-<sha>`) rather than a bare `:$SHA` — needed since the Dockerfile has two meaningfully different targets (see the scope-limit note below), not one.
  - `docker login` via `$CI_REGISTRY_USER`/`$CI_REGISTRY_PASSWORD` — both auto-populated by GitLab once the Container Registry is enabled, no manual token needed for this part (unlike Renovate/Socket).
  - `only: main` — no registry pushes from MR branches.
  - Used `docker:27` + `docker:27-dind` service rather than assuming host docker-socket access, since this file can't know the runner's actual privileges — flagged as possibly-unnecessary overhead if the runner turns out to already have host socket access.
- [ ] Confirming the project's Container Registry is actually enabled and the runner can reach it needs a real pipeline run — **can't verify from here.**

### 5b. Decouple CI from CD
- [x] New `deploy` stage, auto on every green `main`, as decided. `deploy_test` pulls `$CI_REGISTRY_IMAGE/app:test-$CI_COMMIT_SHORT_SHA` — never rebuilds.
- [x] `scripts/deploy_test_simple.sh` rewritten to accept an image ref as `$1` and pull it when given one; called with **no arguments** (existing local-dev usage), it still builds locally exactly as before — local dev workflow is unaffected.
- [x] `environment: {name: test, url: https://test-workflow-engine.whistlebird.co.nz}` added for GitLab environment tracking.

### 5c. Playwright on CD (the real-browser gate)
- [x] **Found and fixed a real gap first:** the plan assumed "the suite already parametrises `base_url`" — it didn't. `tests/e2e/conftest.py`'s `app_url` fixture unconditionally booted its own in-process Flask app via werkzeug; `deploy-runner/SKILL.md` already referenced an `E2E_BASE_URL` env var in its documented smoke-test command, but that env var didn't exist anywhere in the actual fixture code. The documented step had never worked. Fixed `app_url` to short-circuit to `E2E_BASE_URL` when set, and adjusted `_e2e_skip_reason`'s `ENVIRONMENT=test`/TLS-cert checks to not apply in that mode.
- [x] `cd_e2e` job: installs chromium, runs `tests/e2e/test_smoke.py` with `E2E_BASE_URL=https://localhost:8001` against the just-deployed container.
- [x] **Verified end-to-end, not just by reading the diff:** built the `test` target locally, ran it standalone on an isolated port, confirmed real TLS-served pages, then ran an actual Playwright test against it via `E2E_BASE_URL` — passed. (Hit an unrelated local DB-auth quirk against the container from inside Docker Desktop/WSL2 networking during this exercise; didn't chase it since it's orthogonal to what needed proving and unlikely to reproduce on the actual Linux CI runner.)
- [x] Rollback: `rollback_test_on_failure` (`when: on_failure`, needs `cd_e2e`) redeploys whatever `:test-stable` currently points at.
- [x] Promotion: `promote_test_stable` moves the `:test-stable` tag **only** after `cd_e2e` passes — nothing else in the pipeline ever writes that tag, which is what makes rollback trustworthy (a broken candidate was simply never promoted, so "roll back" is just "redeploy the tag that didn't move").
- [ ] The actual "push to main → watch it deploy → break something → watch it roll back" live-fire verification needs a real pipeline run against real infrastructure — **can't do from here**, same reason as 5a.

### 5d. Reconcile the deploy docs/skills
- [x] `DEPLOYMENT.md`: didn't attempt the full rewrite (that's genuinely a `docs-truth` job — verifying every documented command against reality is a different kind of pass than this workstream). Added a prominent stale-content warning at the top pointing to `docs/deploy-registry-cd.md` instead of leaving it silently wrong.
- [x] `deploy-runner/SKILL.md` updated: its smoke-test section now notes that `E2E_BASE_URL` actually works now, and that `cd_e2e` automates exactly that pattern for test — the skill's manual command stays correct guidance for prod (still not automated, deliberately) and ad-hoc checks.
- [x] **Scope boundary, not an oversight:** `docker_build_publish` also builds and pushes `:prod-<sha>` every merge, but nothing auto-deploys it — production still goes through the existing `scripts/git_workflow.sh prod` (manual, tag-based). Auto-deploying test was an explicit decision; auto-deploying *production* the same way is a materially bigger call that needs its own sign-off, not a side effect of this change.
- [ ] **Known scope limit, flagged not fixed:** true single-artifact promotion (the *same* image moving from test to prod, not a parallel build) would need unifying `Dockerfile.multi`'s `test`/`production` targets into one image driven entirely by `-e ENVIRONMENT=...` at `docker run` time, including a dynamic `HEALTHCHECK`. Real, behavior-affecting Dockerfile change — deliberately not done as a side effect here. Full reasoning in `docs/deploy-registry-cd.md`.

---

## 6. Recommended sequencing

1. **§4 datetime** — pure code, no infra, fixes a real bug, and clears the deprecation debt before a Python bump forces it. Smallest blast radius to start.
2. **§1 uv audit / drop pip-audit** — self-contained CI + skill-reference change; do before Renovate so Renovate's bump PRs are gated by the *new* scanner.
3. **§3 Renovate** — now every future bump flows through the modern gate.
4. **§2 Socket** — additive security layer; independent, needs your account/cost sign-off.
5. **§5 Deploy/CD** — the biggest change; do last, on solid CI foundations. Registry publish (5a) → decouple + pull-based test deploy (5b) → Playwright gate (5c) → rollback (5d), each shippable on its own.

Each numbered item = one MR through the normal gate (`merge-request` skill). §5 is 3–4 MRs.

---

## 7. Decisions — RESOLVED (2026-07-19)
1. **`uv audit` gating:** ✅ **Block immediately** (`allow_failure: false`). `/git-commit-chain` handles the red. Protection against the preview command = **pinned uv version**, and local uv gets upgraded to match.
2. **Socket:** ✅ **Adopt on Free tier** ($0, full behavioural scanning). Upgrade to Business (~$40–50/seat/mo) only when a customer/compliance need forces SBOM or SSO.
3. **CD deploy trigger:** ✅ **Auto-deploy to test on every green `main` merge.** Playwright gate + rollback (5c) is the safety net.
4. **`check_dependency_updates` job:** ✅ **Keep — it's not redundant with Renovate** (consistency guard vs upgrade proposer). Rename to `lockfile_consistency`.
5. **`requirements.txt`:** ✅ **Delete.** Nothing reads it; stale and misleading.
