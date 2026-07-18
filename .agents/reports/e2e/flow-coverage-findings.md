# Flow-coverage build — findings & changes

Building real click-through / session-driven flow coverage for every core area (beyond
the render-only smoke layer). Coverage status lives in `coverage-index.md`; this file
records the bugs found and fixed while building it. Same rule as before: a test that fails
on app behaviour means the app is fixed, never the test weakened.

## F3. Process deletion was completely broken (500 for every user) — FIXED

**Found by:** `test_workflow_flow.py::test_delete_process_removes_it`.

Deleting *any* process returned **500 "Failed to delete process"**. Root cause in the ORM:
`process_versions.process_id` is `NOT NULL` with a DB-level `ON DELETE CASCADE`, but the
`Process.versions` relationship (a `backref` on `ProcessVersion.process`) had **no
cascade**. So on `db.delete(process)`, SQLAlchemy tried to *disassociate* the version rows
by setting `process_versions.process_id = NULL` — which violates the NOT NULL constraint
and raises `NotNullViolation` before the DB's cascade ever runs.

Every process a user tried to delete 500'd. Invisible to the unit suite (no test deleted a
process that had an auto-created version row), and invisible to render-only E2E.

**Fix** (`app/core/db/models/process_version.py`): give the backref
`cascade="all, delete-orphan", passive_deletes=True`, so the ORM defers to the DB's
existing `ON DELETE CASCADE` and deletes the version rows instead of nulling them.
ORM-only change — the DB FK already had the cascade, so no migration. Verified: process
delete now returns 200 and the versions are gone; full unit suite still **252 passed**.

## F4. Changing an inventory item's quantity 500'd (edit + adjust) — FIXED

**Found by:** `test_inventory_flow.py::test_edit_inventory_item_persists` and
`::test_adjust_inventory_quantity`.

Editing or adjusting an item to a *different* quantity returned 500. The domain guards
`inventory_items.quantity` with a `before_flush` hook that requires an active
`allow_inventory_quantity_write(...)` reason **at flush time**. Both the update endpoint
(`backend.py`) and the repo's `set_inventory_item_quantity` set the quantity *inside* the
reason context but did not flush there — the first flush happened later, inside
`EventWriter.emit()`, *after* the context had exited, so the guard saw an unauthorized
pending change and raised. (The tenant-isolation owner-PUT passed earlier only because it
re-used the same quantity, so nothing was dirty — the bug only bites when the value
actually changes, i.e. every real edit.)

**Fix:** flush the quantity write while the reason is still active, in both places
(`app/core/backend/backend.py` update endpoint; `inventory_repo.set_inventory_item_quantity`).

## F5. `InventoryItem.display_label` model/DB drift — FIXED

**Found by:** the same adjust test, once F4 was past the guard.

`_item_snapshot` (used by adjust's event emission) reads `item.display_label`. The column
exists in the database (migration `event_sourcing_process_versions_001`) and the repository
reads and writes it, but the `InventoryItem` **model class never declared it** — so loading
an item and reading the attribute raised `AttributeError`, 500ing every adjust and any path
that snapshots an item. **Fix:** declared `display_label = Column(String(255), nullable=True)`
on the model to match the DB. No migration (column already exists). Full unit suite still
**252 passed** after F3–F5.

## Harness fixes made while building flows

- **Chromium detection made CI-proof.** The collection-time guard resolved the browser via
  `sync_playwright()`, which throws "Sync API inside the asyncio loop" once
  pytest-playwright's loop is live (true at collection too, not just in fixtures — the
  assumption in the earlier fix was wrong). Now resolved in a **clean subprocess**, which
  has no event loop, so the executable-path check is reliable regardless of the browser's
  directory naming. This is what actually makes the "skip cleanly when chromium absent"
  guarantee hold in CI.
- **Teardown now handles transitively-scoped children.** `purge_org` only deleted tables
  with a direct `org_id`/`user_id`; `execution_steps` is scoped only through its parent
  execution, so it was left behind and the parent delete hit a foreign-key violation. It
  now also deletes rows whose foreign key points at an org-scoped parent row (generic —
  walks each table's FKs), so any future child table is covered without hand-listing.
- **Shared `csrf_headers`** promoted to conftest (was in test_tenant_isolation) so every
  flow test reads the CSRF token the way core-api.js does.
