---
name: ci-gate
description: "Build and verify the deterministic GitLab CI pipeline that stops unverified code reaching main: jobs for ruff, pytest, semgrep, gitleaks, uv audit, Alembic migration reversibility, and Playwright E2E, plus pre-commit hooks and protected-branch merge checks. Use this skill when setting up or modifying CI, when new-feature or review-feature calls it as the final gate, when a new test suite must become a blocking job, or whenever the user mentions CI, .gitlab-ci.yml, pipelines, pre-commit, protected branches, or 'make sure this can't ship broken'."
---

# CI Gate (GitLab)

Agents forget, drift, and can be argued out of things. Pipelines cannot. Every guarantee the other skills produce (tests, semgrep rules, migration checks, E2E flows) only counts once it runs deterministically in GitLab CI and blocks merge on failure. An agent-run check is a suggestion; a blocking pipeline job on a protected branch is a guardrail.

## 0. Self-discovery (mandatory before writing a single line)

The YAML in section 1 is a shape, not a script. Discover the repo's real configuration first and substitute what you find; a pipeline written against guessed env var names fails in the worst way, green locally and broken on the runner.

**Database config.** Read every file in `app/config/` (all of it: `.py`, `.toml`, `.yaml`, `.env.example`). From it, extract:

- how the DB URL is assembled: a single `DATABASE_URL`, or parts (`DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_PORT`) composed into `SQLALCHEMY_DATABASE_URI`
- which config class or name is the test one (`TestingConfig`, `config["testing"]`, an `APP_ENV`/`FLASK_ENV` switch) and what it expects to be set
- every other env var the app refuses to boot without (`SECRET_KEY` and friends); CI needs dummy values for all of them
- any defaults that would silently point CI at the wrong place (a hardcoded localhost URL, a dev DSN)

Cross-check three places that must agree: `app/config/`, `alembic.ini`/`migrations/env.py` (how Alembic gets its URL, often different from the app), and `tests/conftest.py` (how the test app and DB are actually built). If they disagree, that is finding number one; report it before building CI on top of the inconsistency.

**Then write the jobs from what you found**, not from the template: the `variables:` blocks in the `migrations` and `e2e` jobs use the discovered names (e.g. `DB_HOST: postgres` if the app composes parts, rather than the template's `DATABASE_URL`), the service hostname is `postgres` inside GitLab CI, and the test config name goes wherever the app expects it. Record the discovered mapping in a comment at the top of `.gitlab-ci.yml` so the next agent does not re-derive it:

```yaml
# discovered from app/config/ (<date>):
#   app url:      SQLALCHEMY_DATABASE_URI <- DATABASE_URL
#   alembic url:  alembic.ini sqlalchemy.url <- env DATABASE_URL (migrations/env.py:14)
#   test config:  create_app("testing"), requires SECRET_KEY, DATABASE_URL
```

**Existing tooling.** biz-e already has ruff, semgrep, pytest unit tests, Alembic, and Postgres. Read the existing `.gitlab-ci.yml`, `pyproject.toml`/ruff config, and `.semgrep/` before touching anything. Extend what exists; never paste the template over a working pipeline. Anything below that duplicates an existing job gets merged into it instead. Re-run this discovery whenever config files change; the mapping comment's date tells you when it went stale.

## 1. Baseline pipeline (create or extend `.gitlab-ci.yml`)

```yaml
stages: [lint, test, security, migrations, e2e]

default:
  image: python:3.14-slim
  cache:
    key:
      files: [requirements.txt, requirements-dev.txt]
    paths: [.cache/pip]

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

lint:
  stage: lint
  script:
    - pip install ruff
    - ruff check .
    - ruff format --check .

unit:
  stage: test
  script:
    - pip install -r requirements.txt -r requirements-dev.txt
    - pytest tests/unit tests/integration -q --cov=app --cov-fail-under=80
      --junitxml=report.xml
  coverage: '/TOTAL.*?(\d+%)/'
  artifacts:
    when: always
    reports:
      junit: report.xml

semgrep:
  stage: security
  image: semgrep/semgrep
  script:
    - semgrep scan --config p/python --config p/flask --config p/owasp-top-ten
      --config .semgrep/ --error
  # --error makes findings fail the job; that is the point

gitleaks:
  stage: security
  image:
    name: zricethezav/gitleaks:latest
    entrypoint: [""]
  script:
    - gitleaks detect --source . --no-banner

uv_audit:
  stage: security
  script:
    - pip install "uv==${UV_VERSION}"  # UV_VERSION pinned in top-level `variables:` -- uv audit is preview-stage
    - uv sync --extra dev
    - uv audit --frozen --output-format json --preview-features audit-command,json-output
      > .agents/reports/security/uv-audit.json || (cat .agents/reports/security/uv-audit.json; exit 1)

migrations:
  stage: migrations
  services:
    - postgres:16
  variables:
    POSTGRES_PASSWORD: test
    DATABASE_URL: "postgresql://postgres:test@postgres:5432/postgres"
  script:
    - pip install -r requirements.txt
    # up, down, up: proves reversibility, not just applicability
    - alembic upgrade head
    - alembic downgrade -1
    - alembic upgrade head

e2e:
  stage: e2e
  image: mcr.microsoft.com/playwright/python:v1.49.0-noble
  services:
    - postgres:16
  variables:
    POSTGRES_PASSWORD: test
    DATABASE_URL: "postgresql://postgres:test@postgres:5432/postgres"
  script:
    - pip install -r requirements.txt -r requirements-dev.txt
    - pytest tests/e2e -q --tracing=retain-on-failure
  artifacts:
    when: on_failure
    paths: [test-results/]
    expire_in: 1 week
```

Substitute the env var names, DB bootstrap, and paths with the mapping from step 0; do not ship the template values. The Playwright image pins browsers to the library version; keep the two in sync when upgrading.

## 2. Pre-commit hooks (fast local layer)

`.pre-commit-config.yaml` with ruff, gitleaks, and semgrep on changed files; install with `pre-commit install`. Hooks are the cheap first line; CI is the one that cannot be skipped with `--no-verify`, which is exactly why both exist.

## 3. Protected branch (the part that makes it a gate)

Without this, everything above is decorative; say so plainly if the user skips it. In GitLab:

- **Settings > Repository > Protected branches**: protect `main`, allowed to push: no one, allowed to merge: Maintainers.
- **Settings > Merge requests > Merge checks**: enable "Pipelines must succeed" and "All threads must be resolved".

Or via API if `glab` is authenticated with Maintainer rights:

```bash
glab api projects/:id -X PUT -f only_allow_merge_if_pipeline_succeeds=true
glab api projects/:id/protected_branches -X POST \
  -f name=main -f push_access_level=0 -f merge_access_level=40
```

## 4. Verify mode (when called by new-feature / review-feature)

When invoked as the final gate for feature `<slug>`, do not rebuild the pipeline. Verify coverage:

1. `pytest --collect-only -q tests/ | grep <slug>` confirms the feature's unit and E2E tests are actually collected. A test file that never runs is worse than no test; it manufactures false confidence.
2. `semgrep --validate --config .semgrep/` confirms custom rules added for this feature parse.
3. If the feature added migrations, confirm the new revision is on the chain (`alembic history`) and `alembic heads` shows exactly one head.
4. Run the full local equivalent once: ruff, pytest, semgrep, migration up/down/up, e2e. Report one line per gate in this exact format so orchestrators can parse it:

```
GATE lint: pass
GATE unit: pass (coverage 84%)
GATE semgrep: fail (2 findings, see .agents/reports/<slug>/security.md)
GATE migrations: pass
GATE e2e: pass
```

5. After pushing, check the real pipeline: `glab ci status` or `glab mr view --web`, or report that pipeline status is pending human confirmation. Local green never substitutes for the pipeline that actually guards merge.
6. Never weaken a gate to make it pass. Removing `--error` from semgrep, lowering `--cov-fail-under`, `allow_failure: true`, skipped tests, or `# nosemgrep` comments to get green are prohibited unless the user explicitly approves each one with the reason recorded in the MR description.

## Rules

- The pipeline is append-only from a safety perspective: adding jobs is routine, removing or weakening one requires explicit user approval.
- If pipeline infrastructure is absent (no runner configured), say clearly that the guardrails are advisory-only until it exists. Do not imply protection that is not enforced.
