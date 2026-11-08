# Prerequisite guards for additional-site operations

This is a partial 7.1f slice on the site-register foundation (!427). It does not
activate cross-site transfers, licence coverage, channel mapping or site-restricted roles.

## Generic invariants

- Production validates every selected input and output-reconciliation lot against the
  **persisted execution site**, before changing the step, quantity or audit events.
  The readiness override does not override site scope. A step cannot be completed
  through another execution's URL.
- Produced inventory inherits its producing execution's site. New same-org, active
  site tags are validated; existing physical site tags remain immutable.
- FIFO and manual lot consumption take optional `site_id` (shipping site). With
  multiple sites on, omission uses the default site. Automatic Xero allocation and
  manual candidate lists therefore use the default until channel mapping is delivered.
  Existing sale reversals restore their original recorded lot.
- Stock, location and execution creation routes pass validated site IDs to their
  repositories. Barcode additions cannot add to a different site's barcode lot.
- Reconciliation addition retains the reconciled lot's site; mapping creates a batch
  there; production reconciliation cannot reduce another site's stock.
- Switching off multiple sites is rejected while additional-site operational rows
  exist, including empty stock history. Configuration-only extra sites can still be
  hidden. Closing sites with retained history needs a later explicit design.

## Gates (GL-P07, `multi_site_gates_001`)

Work at an additional site needs three gates, all off by default
(`app/core/db/site_entitlement.py`):

1. the deployment: `[features] multi_site_enabled` (on in `local.ini` and `test.ini`, off in
   `prod.ini`);
2. the organisation's plan: an active `multi_site` feature subscription;
3. the organisation's own switch, `multiple_sites_enabled` (Settings, Sites).

The first two are the *entitlement*: without them the Sites tab is hidden and the switch
refuses to turn on. With all three, work can be recorded at any active site, and the default
site may change (only records made without a site follow it). The internal
`multiple_site_operations_enabled` flag is gone; the migration gave any organisation that had
it on the subscription. Tests grant `multi_site` with `tests.factories.grant_multi_site`.

New trusted callers use `ExecutionRepository.create_execution(org_id, process_id,
commit=False, site_id=UUID)` and `resolve_site(session, org_id, site_id=None)`.
Planner code must not activate the release gate. The initial migration is
`site_operations_001`, following `multiple_sites_001`; integration must keep one chain.

Transfer receipt must preserve original producing-execution lineage when a fragment
physically arrives at another site. That requires a narrowly validated recorded-receipt
path, not unrestricted retagging or a general exception to production-site agreement.

## Validation

Focused PostgreSQL tests cover real HTTP consumption and output inheritance, denied
other-site/foreign inputs and reconciliation, shipping-site FIFO/manual selection,
automatic Xero default shipping, candidate lists, barcode additions and opt-out safety.
The original foundation tests run with the internal gate closed.

136 selected regressions pass, plus the focused HTTP shipping/manual assignment
checks. Database migrations and tests use the dedicated site-test database. Ruff and
Semgrep checks pass; `backend.py` has no net line growth and no new routes.
