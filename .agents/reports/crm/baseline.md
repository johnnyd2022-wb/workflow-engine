# BASELINE: crm
date: 2026-08-15
branch: feat-review

## Preflight
Blockers found and repaired before starting: no `.venv` (`uv sync --extra dev`), test DB
container present but stopped (`docker start workflow-engine-test-db`). Re-ran preflight
after repair: `ok: true`, no blockers. `verification_mode: herdr-tabs`,
`grader_engine: codex`, `live_server_tests: skip` (no dev server running — not needed for
this slice's unit/repo-level tests).

## git status
Clean at start (`feat-review`, no uncommitted changes).

## Migration audit
7 CRM-touching revisions: `add_crm_xero_tables_001`, `crm_contact_terms_001`,
`crm_product_mapping_output_id_001`, `crm_sales_trace_cfg_001`,
`crm_xero_connection_id_001`, `crm_task_done_archive_001`,
`crm_revenue_baseline_target_001`. Every one has a real `downgrade()` (drops exactly what
its `upgrade()` added — tables, columns, indexes). Single alembic head
(`tenant_org_id_notnull_001`), no branch conflicts. Exercised
`alembic downgrade -8` → `alembic upgrade head` against the real test DB: clean round trip,
no errors, ends back at head. Migration audit: **clean**, no patch needed.

## Unit test baseline
```
uv run pytest tests/test_crm.py -v
```
Result: **39 passed, 0 failed**, 18 warnings (all the same pre-existing flask-limiter
in-memory-storage warning that fires across the whole suite, not crm-specific).

## Spec
No `.agents/specs/crm.md` existed. Reconstructed from code, confirmed with user
2026-08-15. Two real bugs surfaced during reconstruction (not yet patched, tracked as
findings): `XeroSyncService.incremental_sync` mislabels its sync-job row's `sync_type` as
`"full"`; `XeroOAuthService._fernet()` derives one Fernet key shared by every tenant's
stored Xero tokens instead of a per-tenant key.
