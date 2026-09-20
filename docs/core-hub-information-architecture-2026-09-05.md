# Core hub information architecture — 5 September 2026

## Decision

Keep `/core` as the operational landing page with three views: **Overview**,
**Inventory**, and **Product workflows**. Keep detailed stock work and active-batch work
on their existing dedicated routes. Do not turn the three hub views into separate page
navigations.

The initial Core request is intentionally compact (`/api/core/hub/overview`), while the
Inventory and Product-workflows tabs fetch their full, potentially unbounded lists only on
first use. That is the right performance boundary for an organisation with real production
history. Separate routes remain appropriate for a task that needs a dense working surface:
live inventory (`/core/inventory/live`) and active batches (`/core/executions/live`).

## Evidence reviewed

- The rebuilt `Whistlebird Ltd` tenant has 12 imported workflows, 138 historical
  executions, 948 production links, 67 receipt records, and 38 curated sheet records.
- The initial hub is already protected by Playwright request-waterfall tests: it makes one
  compact overview call and defers inventory and execution history until a tab is selected.
- The Playwright fixture creates a new organisation for each run, so the Core behaviour is
  exercised without relying on the Whistlebird fixture or a particular organisation name.
- The initial view currently gives three analytical cards the same visual priority. Batch
  dwell and inventory alerts can require an operator response now; traceability coverage is
  valuable, but is primarily explanatory when the health strip has not raised an issue.
- A plain `/core` navigation can reopen the last local-storage tab. That means two people
  opening the same URL can see different first content, and a user returning from a detailed
  task may not receive the operational overview they expected.

## Changes selected

1. Make `/core` deterministic: Overview is the default. An explicitly shared or bookmarked
   `?tab=inventory` or `?tab=workflows` still opens that view, as do Back/Forward events.
2. Preserve Overview's immediate signals (batch dwell and inventory alerts) above the fold.
   Move traceability coverage into a collapsed disclosure with a concise coverage summary.
   The existing health strip remains the prominent route for actual traceability problems.
3. Complete the tab interaction contract: IDs, `aria-controls`, roving `tabindex`, and
   Arrow/Home/End keyboard navigation. Tab selection remains URL-addressable and does not
   trigger duplicate heavy-list requests.
4. Scope every standalone tenant-aware migration ORM operation to the organisation supplied
   to it explicitly. The pre-scope target lookup is an auditable `unscoped()` exception;
   all tenant work runs in `tenant_scope(org.id)`. This preserves the global tenant filter
   and removes misleading `tenant_filter.no_context` warnings. `Whistlebird Ltd` is the
   disposable real-data validation fixture, not a product-specific frontend behaviour.
5. Resolve the Dashboard mobile follow-up without concealing a signal. Biz-E currently
   distinguishes only `ADMIN` and `MEMBER`, not named operating roles, and both roles need
   to see urgent system findings. Keep Dashboard metrics shared until a tenant-configured
   role/view model exists; use the Core landing page as the action-first workspace for
   production operators. This delivery makes that operational hierarchy clearer rather
   than applying a brittle mobile-only hide rule.

## Explicit non-changes

- Do not hide or remove compliance/traceability signals. A problem remains prominent in the
  Core health strip and Notifications.
- Do not add a fourth page or duplicate the existing live inventory/active-batch screens.
- Do not make the default overview fetch full inventory or execution history.
- Do not make dashboard or Core content tenant-specific: the information architecture and
  accessibility contract apply uniformly to every Biz-E organisation. The Whistlebird
  fixture is used only to exercise a realistically populated organisation.
- Keep the Whistlebird importer locked to its explicitly named disposable target. Its legacy
  source data must never be replayed into another customer organisation; its reusable
  tenant-scope helper still establishes the correct target context for any approved caller.

## Verification

- Extend Core Playwright coverage for deterministic `/core`, keyboard tabs, disclosure
  behaviour, Back/Forward, and the original lazy-load request contract.
- Add migration scope regression coverage and run the deterministic bootstrap against the
  disposable `Whistlebird Ltd` tenant before hand-off.

## Dashboard control-tower implementation

The follow-up role decision is now embodied in the Dashboard rather than left as a
copy-only distinction. It starts with a single **Needs attention** queue tagged by its
destination workspace (Core, Compliant, or CRM), followed by a three-workspace map and
then trend cards as supporting context. This makes Dashboard the place to understand the
business across products, while Core, Compliant, and CRM remain the places to complete
production/inventory, evidence, and customer work respectively.

The Dashboard response includes a deliberately lightweight Compliant workspace state:
subscription availability, setup state, and open/failed evidence-record count. It does
not call Compliant's full evidence-plan calculation or its Core movement scan, preserving
the single dashboard request and leaving detailed compliance evaluation to Compliant.

### Performance contract check

- The Dashboard browser still makes one `GET /api/core/dashboard/summary` request at
  landing and makes no `GET /api/compliant/*` request. The workspace cards render from
  that existing response.
- The added Compliant summary has a bounded server-side query shape: one entitlement
  lookup, one profile lookup, and one grouped count of open/failed records. It never
  walks records or relationships in Python, so it cannot introduce an N+1 query.
- The earlier Core change remains separate: `/core` first paints from its compact hub
  overview and only fetches Inventory or Product-workflow lists when their tabs are
  opened. Dashboard does not invoke that hub data on its landing path.
