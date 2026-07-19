# Repo Modernisation Plan

Owner: Johnny · Created: 2026-07-19 · Target repo: `gitlab.com/whistlebird/workflow-engine`

Five workstreams. Each is independently shippable as its own MR — do them in the
recommended order (§6) so the dependency-scanning churn settles before we bolt on
Renovate and CD. Checkboxes are the working list.

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

- [ ] Pin the uv version CI installs (e.g. `pip install "uv==<X>"` or the astral install script pinned) so `uv audit` is guaranteed present and reproducible — do **not** leave it on floating `pip install uv` given the command is preview-stage.
- [ ] Bump local `uv` (currently 0.9.13, lacks the subcommand) to the same pinned version; note it in CLAUDE.md's command list.
- [ ] Rewrite the `.gitlab-ci.yml` `pip_audit` job → `uv_audit`:
  - `uv sync --extra dev` then `uv audit` (against the lockfile). Confirm the exact flag set (`--strict` equivalent, JSON output) against `uv audit --help` on the pinned version.
  - **DECIDED: block immediately** (`allow_failure: false`). A CVE fails the pipeline; `/git-commit-chain` sees the red job and routes remediation. The real protection against the preview command misbehaving is the **pinned uv version** above — not `allow_failure` — so pinning is non-negotiable here.
- [ ] Keep a machine-readable report artifact (`uv audit --format json > .agents/reports/…`) so the `dependency-update` skill still has a findings file to consume.
- [ ] Remove pip-audit everywhere it's now dead:
  - [ ] `.gitlab-ci.yml` — the `uv pip install pip-audit` line.
  - [ ] `requirements.txt` — **delete it (decided).** Grep confirmed nothing reads it except the `ci-gate` skill doc's old `pip-audit -r requirements.txt` line (rewritten below). Dockerfile uses `uv sync --frozen`; no deploy path touches it; it's stale (`Flask==2.3.3` vs real `3.1.3`) and misleading.
  - [ ] Update skills that call pip-audit: `security-audit/SKILL.md`, `dependency-update/SKILL.md`, `ci-gate/SKILL.md` (+ `.claude/takeaway/` mirrors), and `.agents/ci-gate-setup.md` / `.agents/autonomy.md` → point at `uv audit` and the new job name.
- [ ] Update the memory note about the blocking `pip_audit` job to name the new `uv_audit` job.
- [ ] Verify: run the pipeline on a branch; confirm `uv_audit` runs, reports, and (once flipped) blocks on a seeded vulnerable pin.

> Note: pip-audit uses the PyPA Advisory DB (+OSV); `uv audit` is OSV-only today. Coverage is *close* but not identical — the one-pipeline `allow_failure` soak is partly to confirm we're not losing signal.

---

## 2. Socket — supply-chain behaviour analysis (zero-day / proactive layer)

**Goal:** catch malicious *behaviour* (install-time network calls, obfuscation, telemetry, exfil) that CVE scanners miss, at PR time. This is additive to §1, not a replacement — different threat model.

**Cost path (decided: start Free):** Free tier = 1K scans/mo + all 70+ behavioural risk
types — this *is* the zero-day/behavioural gate we want, $0. Team ($25/seat/mo, ~$20 annual)
adds reachability analysis + Slack. **Business ($50/seat/mo, ~$40 annual) adds SBOM generation
+ SSO/SAML** — the two things a paying-customer compliance ask (SBOM request, enterprise SSO)
will eventually force. Plan: ship on Free now; upgrade to Business only when a customer/compliance
requirement demands SBOM or SSO. No blocker to starting.

- [ ] Create socket.dev org (Free tier) + API token; add `SOCKET_SECURITY_API_KEY` as a **masked, protected** GitLab CI/CD variable (never in the repo).
- [ ] Add a `socket` job to the `security` stage:
  - Image with the `socketsecurity` CLI (pip `socketsecurity`), or the official container.
  - Runs on `merge_requests` (diff-scoped: the CLI auto-detects changed manifests from the commit). Uses the built-in `CI_JOB_TOKEN`/`GITLAB_TOKEN` for MR comment posting.
  - Start `allow_failure: true` — behavioural scoring produces judgement-call alerts (a legitimate package can trip a heuristic); soak before it blocks merges, then decide per-alert-tier whether to gate.
- [ ] Decide the block policy: hard-fail only on high-severity behavioural flags (malware, install scripts, telemetry), warn on the rest. Document it next to the job.
- [ ] Add a short `docs/supply-chain-security.md`: what uv audit covers (known CVEs, reactive) vs what Socket covers (behaviour, proactive), so the two jobs' roles are unambiguous.
- [ ] Verify against a known-bad fixture (Socket publishes test packages) that the job flags it.

---

## 3. Renovate — automated dependency management

**Recommendation: Renovate, self-hosted as a scheduled GitLab CI pipeline. Not Dependabot.**

Why: Dependabot only runs on GitHub — you're on GitLab, so it's out. Renovate is the
GitLab-native answer, natively understands **uv** (updates both `pyproject.toml` and
`uv.lock`), and you already run scheduled pipelines, so the operational model is one you
have. Run it as a **CI job on a schedule** (not the Mend hosted app) to keep everything
inside your own runner and secrets — no third-party app with repo write access.

- [ ] Add `renovate.json` (or `.gitlab/renovate.json5`) at repo root:
  - `extends: ["config:recommended"]`.
  - Enable the uv manager; confirm it picks up `pyproject.toml` + `uv.lock`.
  - **Grouping/scheduling to avoid PR spam:** group patch/minor; separate majors; limit concurrent PRs; weekend/off-hours schedule.
  - `dependencyDashboard: true` (single issue tracking everything pending).
  - Also let Renovate manage the **Docker base image** (`python:3.14-bookworm`) and **pre-commit hook revs** (ruff, gitleaks pins are currently hand-maintained and stale — e.g. `ruff-pre-commit v0.1.15`).
- [ ] Add a `renovate` scheduled pipeline job:
  - Runs `renovate/renovate` image, `only: schedules`.
  - Needs a `RENOVATE_TOKEN` (project/group access token with `api` + write) as a masked CI variable.
  - Create a GitLab pipeline **schedule** (e.g. daily 6am NZT) targeting it.
- [ ] **Keep `check_dependency_updates` — Renovate does NOT replace it (decided).** `uv lock --check` is a *lockfile-consistency* guard ("does `uv.lock` still match `pyproject.toml`?", catches an edited-pyproject-without-relock), run per-MR including on Renovate's own PRs. Renovate *proposes upgrades* on a schedule — different job, different stage, complementary. The only fix: the name lies. **Rename the job `lockfile_consistency`** so it describes what it does; update the `.gitlab-ci.yml` comment accordingly.
- [ ] Ensure Renovate PRs run the **full pipeline** (they will, as MRs) so `uv_audit` + tests gate every bump — this is the safety net that lets you auto-merge low-risk updates later.
- [ ] Verify: dry-run (`LOG_LEVEL=debug renovate --dry-run`) against the repo; confirm it detects uv + docker + pre-commit and proposes sane PRs.

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

### 5a. Build & publish (end of CI)
- [ ] Add a `build` stage after `migrations`. Job builds `Dockerfile.multi` and pushes to the **GitLab Container Registry**, one image repository per logical image (Docker convention — a repo per image, tags for versions):
  - Path: `$CI_REGISTRY_IMAGE/app` (room for `$CI_REGISTRY_IMAGE/<other-image>` later — do **not** dump multiple images as tags of one repo).
  - Tag **immutably** by commit: `:$CI_COMMIT_SHORT_SHA`, plus a moving `:latest` / `:main` pointer for humans. The SHA tag is what CD deploys — that's what makes "don't deploy failing artifacts" enforceable.
  - Build the `production` target (and/or `test` target) via `--target`.
  - `docker login` with the built-in `$CI_REGISTRY_USER` / `$CI_JOB_TOKEN`.
  - `only: main` (and tags) — don't push registry images for every MR branch.
- [ ] Confirm the project's Container Registry is enabled and the runner can reach it.

### 5b. Decouple CI from CD
- [ ] New `deploy` stage, **auto on every green `main`** (decided — no manual button; a merge to main that passes CI deploys to test), gated on the build job's artifact (the SHA-tagged image). CD does **not** rebuild — it pulls `$CI_REGISTRY_IMAGE/app:$CI_COMMIT_SHORT_SHA`. This is the CI/CD decoupling: the thing that ships is exactly the thing that was tested, addressed by digest/SHA. (Because it's fully automatic, the Playwright gate + rollback in 5c is what keeps a bad merge from sitting live — that safety net is load-bearing here, not optional.)
- [ ] Rewrite the test-deploy path to **pull, not build**:
  - Update `scripts/deploy_test_simple.sh` (and the `git_workflow.sh` `deploy_test` path) to `docker login` + `docker pull …/app:<sha|latest>` + `docker run`, replacing the local `docker build --target test`.
  - Keep the healthcheck wait.
- [ ] Use a GitLab **environment** (`environment: name: test, url: https://test-workflow-engine.whistlebird.co.nz`) so deploys are tracked and rollback has a UI.

### 5c. Playwright on CD (the real-browser gate)
- [ ] Add a `cd_e2e` job **after** the test deploy, in the CD flow:
  - Installs chromium (`uv run playwright install chromium`) and runs `tests/e2e/` against the **deployed test URL** (the suite already parametrises `base_url`).
  - This is ground-truth verification of the *deployed artifact*, not the source — which is why it belongs on CD, not CI.
- [ ] **Rollback rule — don't leave a failing artifact live:** if `cd_e2e` (or the post-deploy healthcheck) fails, CD re-deploys the previous known-good SHA tag. Record the last-good SHA (GitLab environment history already tracks the last successful deploy; the deploy script can also stash the previously-running image tag before swapping). Implement rollback as: pull previous-good SHA → run → healthcheck → confirm.
- [ ] Promotion: only a green `cd_e2e` + healthcheck marks the SHA as "known good" (e.g. move the `:test-stable` tag). Prod deploy later consumes only `:test-stable`.
- [ ] Verify: push to main → image published → auto-deploy to test → Playwright runs against the live test env → deliberately break a page and confirm CD refuses/rolls back.

### 5d. Reconcile the deploy docs/skills
- [ ] `DEPLOYMENT.md` is stale (bashrc-era, wrong ports 5000/5001/5401 vs real 8000/8001/8401). Update it for the registry/CD flow — route through **docs-truth** so every documented command is verified.
- [ ] `deploy-runner` skill owns "cut tag, deploy, smoke test, rollback" — align its steps with the new registry+rollback mechanics so the skill and the pipeline agree.

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
