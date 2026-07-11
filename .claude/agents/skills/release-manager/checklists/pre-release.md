# Pre-Release Checklist (Release Manager)

Every item must pass (or be consciously waived with a reason) before GO.

## Code & tests
- [ ] All merged MRs for this release accounted for (`glab`).
- [ ] Tests green on the release path (pytest integration).
- [ ] No known red/flaky test masking a real failure.

## Data & migrations
- [ ] Alembic migration reviewed and **reversible**.
- [ ] Rollback plan written (revert path / flag-off).
- [ ] No destructive change without backup.

## Config & flags
- [ ] Feature flags set to intended state.
- [ ] Env/config changes documented (e.g. `XERO_CLIENT_ID/SECRET/REDIRECT_URI`).
- [ ] Secrets handled correctly (encrypted at rest, not in session).

## Safety gates (from CTO)
- [ ] Tenant isolation (`g.org_id`) preserved.
- [ ] Authz on new routes; no secret leakage.

## Observability
- [ ] Monitoring/logging can detect the main failure mode.
- [ ] Post-release watch items listed.

## Docs & customers
- [ ] Docs / help updated.
- [ ] Customer changelog drafted (plain language).

## Decision
- [ ] **GO / NO-GO** recorded with blockers.
- [ ] Customer-visible? → issue marketing brief + sales enablement + CS update.
