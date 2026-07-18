---
name: dependency-update
description: "Consumes pip-audit CVE findings and routine version bumps: upgrades the dependency, reads its changelog for breaking changes, runs the affected chain subset, and hands off to merge-request. Use this skill when the CI pip_audit job reports a finding, when check_dependency_updates flags a stale lockfile, when the user asks to upgrade/bump a package, or on a routine dependency review."
---

# Dependency Update

Two triggers, same flow: a **CVE** (from the `pip_audit` CI job / `.agents/reports/*/pip-audit.json`,
see `ci-gate`'s setup notes at `.agents/ci-gate-setup.md`) or a **routine bump** (from
`check_dependency_updates`, the existing `uv lock --check` job, or a manual ask). Either
way: upgrade, read what changed, verify, hand off. Never bump blind.

## 1. Identify the target and why

- CVE-driven: read the finding (`pip-audit`'s JSON has the package, installed version,
  fix version, advisory ID). Priority is severity, not alphabetical — a critical CVE in
  an internet-facing dependency (`flask`, `authlib`, `xero-python`, anything touching
  the OAuth/auth path) jumps the queue over a dev-only tool.
- Routine: `uv lock --check` failing, or a package the user names.

## 2. Upgrade

```bash
uv add "<package>>=<fix-version>"   # or uv sync --upgrade-package <package>
```

This repo pins some dependencies exactly (`==`) and range-pins others (`>=`) in
`pyproject.toml` — check which style the target already uses and preserve it unless the
upgrade reason (e.g. a CVE fix needs a minimum, not an exact pin) argues for changing it;
note that reasoning in the PR if you do.

## 3. Read the changelog for breaking changes

Before running anything, read the release notes/changelog between the installed and
target version (PyPI project page, GitHub releases, or `CHANGELOG.md` in the package).
Specifically look for: removed/renamed APIs this codebase imports, changed defaults
(especially security-relevant ones — cookie flags, TLS verification, serialization),
and Python version floor changes. Grep the codebase for the package's imports
(`grep -rn "^from <pkg>\|^import <pkg>" app/`) and check each usage against what changed.

Dependencies worth extra care given what they touch here: `flask`/`flask-wtf` (CSRF,
session security), `authlib`/`xero-python` (OAuth flows in `app/features/crm/`),
`bcrypt`/`cryptography`/`pyotp` (password hashing, 2FA), `sqlalchemy`/`alembic`
(migration behavior), `psycopg2-binary` (DB driver — check Postgres version compat
against the `postgres:16` used in CI and `docker-compose.test.yml`).

## 4. Run the affected chain subset

Not the full new-feature chain — a dependency bump isn't a feature. Run **preflight**
first (`python3 scripts/preflight.py --json`, or inherit the caller's report) — a bump
that appears to break the suite when the test DB is simply down is the most expensive
possible way to read a connection error. Then:

```bash
uv run pytest tests/ -v      # full suite; a bump can break anything
uv run ruff check app/                         # catches API signature drift ruff's
                                                # rules happen to cover, not a substitute
                                                # for reading the changelog
```

Expect `252 passed, 30 skipped` with no dev server up. Failures that never reached an
assertion belong to **suite-warden**; failures that assert wrongly are the bump's, and
they are the ones you own.

If the package is security-relevant (the list in step 3) or touches request handling,
also run **security-audit** bare (whole-app scope, not a slug) rather than skipping it —
routine bumps to auth-adjacent packages are exactly where an unnoticed default change
turns into a real finding.

If the package has migrations of its own (rare) or the bump changes SQLAlchemy/Alembic
behavior, run **migration-safety**.

If the bump changes observable behaviour the suite pins (a serialization format, a
validation rule, a date/locale default), a green suite may mean the *tests* silently
drifted to match the new behaviour rather than the behaviour being intended — hand the
changed tests to **test-author** to update deliberately (with the changelog change named
as justification) and to **test-evaluator** to confirm they still assert the real
contract. Don't let a dependency quietly rewrite what the suite considers correct.

## 5. Report and hand off

```markdown
# DEPENDENCY UPDATE: <package> <old> -> <new>
date: <date>
trigger: CVE <advisory-id> (severity) | routine bump | user request
changelog_reviewed: yes — breaking changes: <none | list>
usages_checked: <n> call sites in app/, all compatible | <what changed>
tests: pass (<n> tests)
security_audit: pass | not applicable (not security-relevant package)
```

Call **merge-request** to open the MR — title `chore: bump <package> to <version>` (or
`fix: bump <package> to <version> (CVE-<id>)` for a CVE-driven update so the security fix
is visible in the git history, not just the changelog).

## Rules

- Never bulk-upgrade unrelated packages in the same PR as a CVE fix — a security fix
  should be reviewable and revertable on its own. Routine bumps can batch together if
  none of them are individually risky (patch-version, no changelog concerns).
- A CVE finding that can't be fixed by upgrading (no fix released yet, or the fix breaks
  something this app depends on) is `accepted-risk` territory — report it, don't silently
  leave `pip_audit` red or add a blanket suppression. Flag to the user for sign-off,
  same rule `security-audit` follows for its own findings.
- Never skip reading the changelog because "it's just a patch version" — patch versions
  have shipped security-relevant default changes before; the read is cheap, the miss
  isn't.

## Handoffs

- ← CI `pip_audit` job / `.agents/reports/*/pip-audit.json`: CVE findings to triage.
- ← `check_dependency_updates` (existing lockfile-freshness job): routine staleness.
- → **security-audit**: bare run for security-relevant package bumps.
- → **migration-safety**: if the bump touches SQLAlchemy/Alembic behavior.
- → **merge-request**: always the final step.
