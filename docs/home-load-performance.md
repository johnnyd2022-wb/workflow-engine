# Home initial data load

Measured 26 October 2026 against main `d38b066a`, using the existing local test database
and a populated NZ Alcohol tenant. No production database or deployment was used.

## Cause

Boosted navigation avoids replacing the shared shell on an in-app visit. The first login
still loads that shell, and Home previously waited for DOMContentLoaded, including the
unrelated shared scripts and deferred Sales components, before starting its summary fetch.

The summary then called the full Sales overview: product rankings, customer breakdowns,
contact completeness, six-month sales analysis and task history were calculated and thrown
away. Each task's customer was looked up separately, including a second serialisation of
many tasks for the unused overview list.

The live output-expiry check also loaded completed execution history and its inventory
before discovering which step definitions actually had expiry rules. Ready-date checking
already filtered the relevant definitions in SQL; expiry now does the same.

## Change

- Load CoreAPI before page content and start Home's request when its root exists. Other
  shared scripts can download while the request runs. Keep one initial summary request.
- Home reads only the live Sales totals it uses and a narrow projection of open tasks.
  Customer names use a tenant-scoped outer join; completed/cancelled history and contact
  PII such as phone/email/addresses are not loaded for the Home calculation.
- Filter output-expiry steps by the presence of an expiry configuration in Postgres,
  retaining Python's existing validity/enabled checks and all eligible findings.
- Refresh Home after htmx history restoration and persisted browser pageshow: loading
  markers from an aborted/frozen request must not prevent live data from loading on Back.

No response cache, dependency, schema or runtime configuration changes. Sales' own full
analysis and the Home response contract remain available as before. Compliance checks
still run live according to their existing cache policy.

## Measurement

An alternating before/after comparison used the same app, tenant and tenant filter. Each
sample had a new request/session, with one warm-up pair followed by five measured pairs.
Only `generated_at` was excluded from the response equivalence check.

| Summary handler | Before | After |
|---|---:|---:|
| Database queries | 132 | 98 |
| Median time, local machine | 381 ms | 277 ms |

This is a 26% query reduction and a 27% handler-time reduction in that sample. It excludes
network, HTML, static downloads and authentication; it is not a staging latency claim.
The browser regression holds the Settings script response pending and requires Home's
data to render while document.readyState is still loading, proving the removed dependency.

The full production-lineage observation still walks the DAG in the live NZ Alcohol check.
It is the largest remaining summary component on this tenant. This MR does not hide that
cost by caching potentially stale compliance findings or dropping a check.

## Verification notes

The baseline browser run also reproduced Home stuck loading after Back and an unrelated
Monday-only trend test failure. The trend fixture now supplies two distinct points rather
than assuming week-to-date always has multiple days; its visible moving-line assertions
are unchanged. The new Sales test covers January rollover, live updates, status/date/type
filters, 40 open tasks and archived history with a four-query budget, and hostile cross-org
contact references.
