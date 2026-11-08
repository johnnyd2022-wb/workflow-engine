# Tastings CI integration review

Date: 2026-10-27. Scope: fixes for pipeline2991085848's workspace-destination and standalone-model-import failures. Read-only review; no app/test/script edits or schema operations.

## Navigation fix

Grouping `("tasks", "tastings")` restores the established four primary Sales destinations without removing the feature. `section_tabs()` chooses Tasks as the group's primary; `_workspace_links()` exposes Tastings as a related action from Tasks and from the Sales overview. The existing `when="nz_alcohol"` condition and `sales.view` permission remain attached to the Tastings registry entry. `_primary_key()` correctly selects Tasks while viewing Tastings, and the secondary breadcrumb resolves through Tasks.

Independent executable checks, using the actual navigation functions: every `UserRole` has at most four Sales primary destinations; the Tastings action exists at `/crm` and `/crm/tasks` with NZ Alcohol enabled and is absent with it disabled; the active Tastings primary resolves to Tasks. All checks passed. The browser test changing `get_by_role("tab")` to `get_by_role("link")` matches this deliberate semantic change and retains the click, visible loaded page and subsequent history/filter behavior assertions; it does not remove the behavior under test.

## Model registration fix

Core now registers the CRM task **module** before the Tastings module. The Tasting model no longer imports the concrete CRMTask class while its defining module may be partially initialized; the existing string relationship target is resolved after normal module loading. No model/table/FK or lifecycle guard is removed.

Independent fresh-process checks passed for both import orders:

- Import CRMTask first, then Tasting, and run `configure_mappers()`.
- Import Tasting first, then CRMTask, run `configure_mappers()` and inspect `Base.metadata.sorted_tables`.

The latter still emits the previously existing warning about the contract-material/inventory/site-receipt FK cycle; it completes successfully. No new Tastings cycle or missing referenced table was reported. Checks were configured to the isolated scratch DB suffix and required no schema/data writes.

No open finding in these integration fixes. This review does not replace root's rerun of the full standalone-import/navigation suites, dedicated29 tests, updated browser checks or the next exact-head CI pipeline.

VERDICT: clean
