# E2E-PLAYWRIGHT: compliant-platform
date: 2026-08-22
stage: e2e-playwright (access: write; gap-fill mode). Report written by the orchestrator on
the stage's behalf — its launched session hit the usage-limit boundary right after producing
the second full test run (`_run2.txt`, since deleted as scratch) and before writing its own
report, per verification-chain.md §5's "orchestrator captures the verbatim outcome" fallback.

## What was built
No `tests/e2e/compliant-platform/` directory existed before this stage. It authored:

- `conftest.py` — fixtures seeded through the real APIs (`page.request`, real session
  cookies), not direct DB writes: `admin_page`/`member_page` (single-org), `admin_and_member_pages`
  (same org, both roles — needed because plain `fresh_user` always mints a new org),
  `two_tenants`, `enable_profile`, `create_alcohol_product`, `create_record`,
  `create_core_execution` (a real Core execution for `source_refs` probes), `create_report`.
- `test_dashboard_page.py` — auth-required 302, full render (hero copy, profile/record/product
  forms visible, `assert_clean_page` — no console errors/failed requests).
- `test_static_asset_security.py` — auth-required, real `.js`/`.css` byte-for-byte match,
  path-traversal rejection (`..secret.js`/`.css`), disallowed-extension rejection.
- `test_profile_and_capture_context.py` — capture-context false-before/true-after-enable/
  false-after-disable, ADMIN gate on `PUT /profile`, body-shape validation (non-object,
  non-boolean `enabled`, non-object `settings`), upsert-and-refresh, overview auth + null
  profile for a fresh org.
- `test_alcohol_products_flow.py` — happy path, duplicate-name 409 (not 500), ADMIN gate,
  unknown product type, invalid ABV (parametrised), missing inventory_name.
- `test_records_flow.py` — 409 without an enabled profile, happy path (no ADMIN required,
  per spec), same-org member-without-admin can attest, unknown framework/control 400,
  `?framework=` filter + newest-first ordering, auth required.
- `test_reports_flow.py` — 409 without enabled profile, unknown-framework 400, happy path
  (checksum + `view_url`), malformed report-id 400, default JSON shape, `?format=html`
  render, `?format=csv` attachment headers, auth required.
- `test_tenant_isolation.py` — the mandatory cross-tenant probe, seven cases: profile,
  alcohol-products, records, and reports (`GET` returns 404 not 200/403 "for every format" —
  json/html/csv) all invisible across orgs; duplicate-name uniqueness is per-org not global;
  a `source_ref` UUID belonging to another org's real Execution is rejected, not silently
  accepted; report creation only ever sees the requesting org's own records.

50 tests total, all currently green (see Verification below).

## A real defect found live, root-caused and fixed (not by this stage — by the orchestrator, after resuming)

The stage's own run (`_run2.txt`, captured before it was cut off) showed 6 failures, all
clustered in `test_dashboard_page.py::test_dashboard_page_renders_for_logged_in_user` and
every `admin_page`-driven case in `test_static_asset_security.py`. The stage never got to
diagnose them. Root-caused by the orchestrator:

**`GET /compliant/static/<filename>` (`app/features/compliant/compliant_bp.py`) was
completely broken for every caller, authenticated or not.** The view function was named
`static`, giving it the Flask endpoint `compliant.static` — which collides with a
codebase-wide convention in `app/api/middleware/tenant_context.py:71` and
`app/api/middleware/session_security.py:42`: any endpoint whose name ends in `.static` is
treated as Flask's own built-in (intentionally public) static-file route and is skipped when
populating `g.current_user`/`g.org_id`. Because this route is a *custom* view that happens to
share that name, `g.current_user` was never set for it, so `@requires_auth` always saw an
unauthenticated request and the app's global 401 handler redirected every GET (302 to `/`) —
never actually serving `compliant.js`/`compliant.css` to anyone. In a real browser this meant
the entire `/compliant` dashboard rendered with no styling and no interactivity (its own JS
never ran). Confirmed live via a Flask test-client probe (both before and after the fix) and
matches an identical, already-documented bug and fix in
`app/features/process_templates/process_templates_bp.py` (that blueprint's comment cites the
exact same failure mode, found the same way — by e2e-playwright — in the process_templates
review that merged just before this one).

**Fix**: renamed the view function to `serve_compliant_static` (endpoint
`compliant.serve_compliant_static`), matching the pattern already established by
`crm_bp.py` (`serve_crm_js`/`serve_crm_css`) and `process_templates_bp.py`
(`serve_process_templates_static`). No template/JS reference used `url_for()` for this route
(both call sites in `dashboard.html` are literal `/compliant/static/...` paths), so the URL
itself is unchanged — only the internal routing name. Recorded in the finding history
(`scripts/finding_history.py`, sig `771d29ea8634`, kind `auth-bypass-static-endpoint-naming`,
verdict `fixed`).

## Verification
```
uv run pytest tests/e2e/compliant-platform -q
50 passed, 1 warning in 122.42s (0:02:02)
```
All 50 tests green after the fix, including the 6 that exposed the defect.

## Not covered (documented, not a gap)
- `app/features/compliant/modules/nz_alcohol/` — explicitly out of scope per task (separate
  `compliant-nz-alcohol` slug).
- Live-browser Playwright screenshot/visual assertions beyond `assert_clean_page` — the spec
  has no visual ACs; DOM-locator presence checks (`data-*` attributes) were judged sufficient
  for the dashboard render AC.

VERDICT: patched
