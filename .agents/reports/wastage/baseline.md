# BASELINE: wastage
date: 2026-08-11
branch: feat/global-org-scoping

## git status
Not fully clean, but pre-existing and unrelated to this slice (present before this review started):
- `M .agents/reports/perf/last-run.json` — perf tracking file from an unrelated prior run
- `?? app/core/process_docs_storage/*` (4 dirs) — process-design upload artifacts, unrelated to wastage

No file under wastage's surface (`app/core/backend/backend.py` wastage section,
`app/core/utils/inventory_wastage_quantity.py`, `app/core/db/models/inventory_wastage.py`,
`app/core/db/repositories/wastage_repo.py`, `frontend/inventory/dispose*`) is dirty.

## test run
```
uv run pytest tests/test_wastage.py -v
25 passed, 25 warnings in 13.12s
```
All pass, including `test_wastage_records_are_org_scoped`.

`tests/test_multi_tenant_isolation.py` has no wastage-specific cases (file comment at line 14
says wastage isolation is covered in test_wastage.py's Batch 3 instead — confirmed present:
`test_wastage_records_are_org_scoped`).

## tenant-scoping context
This branch (`feat/global-org-scoping`) is mid-flight on a global `TenantScoped` mixin +
denormalized `org_id` scoping effort (see commits 35e4ec9, 43a221f, 6cc1337, 84dc45d, 4bc7482).
`InventoryWastage` (`app/core/db/models/inventory_wastage.py:14`) already inherits `TenantScoped`,
introduced in 35e4ec9 — so wastage is on the current org-scoping mechanism, not the old
per-query-filter pattern. This is directly relevant to the security-audit stage (Step 3.2).

## verdict
Baseline green. Proceeding to spec reconstruction.
