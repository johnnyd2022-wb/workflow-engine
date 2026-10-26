# Tastings CI gate verification

Verify mode; no CI YAML change. Existing config maps app/Alembic to `ENVIRONMENT=test` INI database parts; `ci/setup_database.sh` patches host/port to its disposable PostgreSQL16 service. Local verification used an isolated scratch suffix, never the shared DB's incompatible revision.

- GATE lint: pass — `ruff check app/`, `ruff format --check app/`;385 files formatted. Both changed JS syntax checks pass.
- GATE unit/integration: pass —146 related real-PostgreSQL tests, including29 dedicated Tastings cases.
- GATE feature browser: pass —20 cases ×3 consecutive UTC runs. Subscribed performance ceilings pass; page advisory query budget remains visible.
- GATE security rules: pass —31 repository rules,641 files,0 findings. Fresh `semgrep --config=auto` reports227 repository findings; changed paths match prior reviewed screenshot-CLI/test-only audit warnings, no new shipping feature finding. Frozen dependency audit94 packages,0 vulnerabilities.
- GATE migrations: pass locally — additive `tastings_001`, one head, scratch up/down/up, immutable-basis behavior exercised. Blocking CI `migration_reversibility` includes head and full base/head cycles.
- GATE secrets: pass for implementation commit — gitleaks scanned1 commit/~157KB, zero findings. Final full commit range also checked before push.
- GATE routing: pass — `scripts/agent_launch.py --check`.

Blocking CI jobs for Ruff, custom Semgrep/observability/learned rules, gitleaks, uv audit, migration reversibility and relevant test selection already exist. The touched E2E module is selected explicitly by the existing selector; its subscribed measure fixtures make performance executable instead of a read-only promise. Exact-head selector output and terminal GitLab pipeline are recorded in the MR.

Page-design intentionally remains draft awaiting layout choice, per its explicit ship-three-then-one workflow. It is not a waiver of functional gates. Shared browser baseline comparison is in `e2e.md`; no blanket all-suite-green claim is made.
