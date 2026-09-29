# Production demand

Open **Planner** in the sidebar to record an order reference, workflow output,
quantity, due date and priority. Demand is shown by due date, then priority. Cancelling
keeps the record; it does not delete stock, cancel an execution or change an invoice.

This is the explicit demand foundation for roadmap 7.3a. Sales/contract adapters,
stock targets, planning forecasts, material/capacity checks, batch scheduling and
the week/month board remain subsequent slices. A due date is the requested date;
it is not a calculated delivery promise.

## Data and access

- `planning_demands` inherits tenant scope. Every repository operation also requires
  the authenticated organisation ID explicitly.
- Workflow output IDs are stable JSONB UUIDs. The server resolves them in the same
  organisation and snapshots their unit; clients cannot supply tenant, unit or status.
- Quantities use `NUMERIC(18,4)`; counted units require whole numbers. Invalid workflow
  units are excluded from the selection rather than causing a database error.
- Reading requires `production.view`; creation/cancellation requires
  `production.record`. A read-only auditor cannot mutate demand.
- Mutations require Flask-WTF CSRF. The JSON form bypasses HTMX form boosting; the
  sidebar entry performs a full navigation to load the slice's assets.
- Demand changes and their staff audit entry commit in the same transaction.
- Migration `planner_demands_001` creates an empty demand table. Existing stock,
  executions, sales and quantities are unchanged.

## Validation

Run the slice tests against a migrated test PostgreSQL database:

```sh
ENVIRONMENT=test uv run --extra dev pytest tests/features/planning/test_demand.py tests/test_access_policy.py -q
```

The browser test proxies an authenticated Flask client into Chromium, exercising
the real template, shared shell, assets and API. It creates/cancels a demand at
390px and checks injection-safe text and horizontal width. A separate test enables
real Flask-WTF validation and proves missing-token refusal and valid-token success.
