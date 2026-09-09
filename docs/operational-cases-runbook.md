# Operational cases (A1) — operator runbook

Scope: A1 only (`untracked_items` source, single-tenant flag). See
`.agents/specs/operational_cases.md` for the full contract this runbook operationalises.

## Enabling the capability

One deployment-wide switch enables the capability for every organisation:

**Deployment kill switch** — `operational_cases_enabled` under `[features]` in
`app/config/<environment>.ini`. Flipping it requires a deploy because configuration is
read at process start. When it is off, normal `/api/core/cases/*` and `/core/cases*`
routes return 404. The read-only history routes (`/api/core/cases/history/<id>[/events]`)
remain available to same-org ADMINs for recovery.

## Disabling after a defect (rollback while retaining data)

1. Set `operational_cases_enabled = false` for the affected environment and redeploy.
   The blueprint's request gate and transactional command boundary fail closed, while
   already-committed cases, links, and events remain untouched.
2. Confirm normal routes now return 404 (`GET /api/core/cases` → 404) while Core
   generally keeps working.
3. Same-org ADMIN can still read case history:

   ```bash
   curl -H "Cookie: <session>" https://<host>/api/core/cases/history/<CASE_ID>
   curl -H "Cookie: <session>" https://<host>/api/core/cases/history/<CASE_ID>/events
   ```

   These routes check `@requires_role(ADMIN)` only, so a deployment-wide disable does not
   lock an organisation out of its own audit trail.
4. For a full tenant snapshot instead of one case at a time, use the export CLI (below).

## Application rollback with additive schema retained

A normal code rollback (redeploy an older application version) does **not** need the
migration to run in reverse — `operational_cases_001` is purely additive (three new
tables; no existing table is touched). An older application build that predates this
feature simply never queries the new tables. If that older build also predates the
history routes, operators fall back to the export CLI for a read-only tenant snapshot.

**Never run `alembic downgrade` for `operational_cases_001` against a database holding
real case data** — its `downgrade()` drops all three tables and is destructive. It exists
only for disposable/CI fixtures (see the migration's own docstring and
`tests/test_operational_cases.py`'s upgrade/downgrade/upgrade cycle, which runs against
the disposable test database, never production).

## Tenant-scoped export / disposable restore rehearsal

Read-only, streams in batches of 500 rows, no production connection required in agent
verification — point `--out-dir` at wherever you're running it:

```bash
uv run workflow operational-cases-export --org-id <ORG_ID> --out-dir /tmp/oc-export-<ORG_ID>
```

Produces:

- `operational_cases.jsonl`, `operational_case_links.jsonl`, `operational_case_events.jsonl`
  — one JSON object per line, every column of that table, values as their JSON-serialisable
  form (UUIDs/timestamps as strings).
- `manifest.json` — `schema_version`, `org_id`, `exported_at`, and per-file
  `row_count` + `sha256` checksum.

### Restore rehearsal (disposable data only)

1. Run the export against a **disposable** org (never production) that has representative
   case data — e.g. a test-DB org seeded by `tests/factories.py`'s case factory.
2. Record the manifest's row counts and checksums.
3. Point a local environment, or the disposable CI test environment, at a second, empty
   database named `oc_verify_<suffix>`, then run
   `uv run workflow operational-cases-rehearse --export-dir <EXPORT_DIR>`.
   It verifies every exported checksum, exercises the schema constraints, compares the
   restored rows to the original export, and rolls all writes back.
4. There is no general production restore API by design (spec: "no general production
   restore API"). A real incident restore is a separate, explicitly authorised operation
   using this same rehearsed procedure, not a CLI flag.

## Source-deleted / owner-unavailable recovery

- **Source (inventory item) deleted**: the case keeps its immutable snapshot from
  creation time. The detail page shows a "source not found" freshness label instead of a
  live observation. Recovery options: restore the inventory item in the owning workspace
  (Core inventory), or have an ADMIN dismiss the case with a reason documenting the
  deletion. Neither path silently closes the case — dismissal is always an explicit,
  reasoned action (see the lifecycle table in the spec).
- **Owner deactivated while a case is active**: the case keeps its `owner_id` and full
  history (no cascade rewrite), but the detail page and dashboard's needs-owner count
  both treat it as needing an owner. An ADMIN reassigns via `PATCH /api/core/cases/<id>`
  with a new `owner_id` — this is the only path that changes ownership after creation.

## Verifying the migration is reversible (disposable fixtures only)

```bash
docker-compose -f docker-compose.test.yml up -d   # disposable test DB
uv run alembic upgrade head
uv run alembic downgrade -1   # drops the three operational_cases tables
uv run alembic upgrade head   # recreate them
```

This exact cycle is exercised in CI-equivalent form by
`tests/test_operational_cases.py`'s migration test — see AC8 there for the automated
assertion (`fixtures`/`AC8` docstring markers in that file).
