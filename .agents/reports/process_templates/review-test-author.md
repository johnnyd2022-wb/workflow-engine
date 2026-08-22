# TEST AUTHORING — 2026-08-22 (review-feature: process_templates unit coverage gaps)

mode: gap-fill (three named coverage gaps from a `pytest --cov` audit against the
already-merged process_templates feature)

preflight: test_db=up, live_server_tests=skip (per stage preflight, not re-probed)

flows_touched: row 29 — Industry process template catalogue (`.agents/test-map.md`)

## Gaps closed

1. **`app/features/process_templates/process_templates_bp.py:31-33`** — static-asset
   route's path-traversal/extension guard (`"/" in filename or ".." in filename or not
   filename.endswith((".js", ".css"))` → `abort(400)`) had zero test coverage.
   `TestStaticAssetRoute` hits the real mounted route
   `GET /process-templates/static/<path:filename>` (requires auth, via `app_client`):
   - a traversal attempt (`../../../etc/passwd`) → 400
   - a disallowed extension (`evil.py`) → 400
   - the real `.js` asset (`template-catalog.js`) → 200
   - the real `.css` asset (`template-catalog.css`) → 200

   Verified with a throwaway probe (deleted before this report) that Werkzeug's test
   client does **not** collapse `..` segments before Flask's routing sees them — the
   traversal path reaches the route handler as literal text and is caught by the
   guard, not silently normalized away by the HTTP layer beneath it.

2. **`app/features/process_templates/services/process_templates_service.py:104-113`**
   (`_build_description`, AC6) — two branches had no direct test:
   - no description → returns the bare `"Created from: <name> v<version>"` suffix
     alone (line 105's branch).
   - combined `"<description>\n\nCreated from: ..."` would exceed the 1000-char
     `Process.description` column → the template's own description text is truncated
     first so the `"Created from: ..."` suffix survives byte-for-byte.

   `TestBuildDescription` calls `_build_description` directly against synthetic
   `ProcessTemplate` objects (no route/service indirection) and asserts the exact
   output string in each case — not a "doesn't crash" check:
   - `test_no_description_returns_provenance_suffix_alone`: description `""`
     → `result == "Created from: Bare Template v3"`.
   - `test_short_description_returns_combined_string`: a real (non-truncating)
     description → exact combined string.
   - `test_long_description_is_truncated_so_suffix_survives_intact`: description
     `"x" * 990` (combined length 1023 > 1000, forcing the truncation branch)
     → asserts `len(result) == 1000`, the result ends with `"\n\n" + suffix`, the
     truncated description is exactly `990 - 23` chars (computed independently from
     `_DESCRIPTION_MAX_LEN`/suffix length, not copy-pasted from the implementation),
     and the suffix appears exactly once.

3. **`app/features/process_templates/catalog/registry.py:118`**
   (`get_template_by_id`) — returning `None` for a template id absent from the
   catalogue entirely (distinct from AC3's existing wrong-family case,
   `test_ac3_detail_404_for_org_without_permitted_family`, which uses a real
   catalogue id in an unpermitted family). `TestMissingTemplateId` asserts
   `registry.get_template_by_id("not-a-real-template-id") is None` directly, and
   that `GET /api/core/process-templates/not-a-real-template-id` 404s through
   `get_template_detail`'s `registry.get_permitted_template` → `get_template_by_id`
   → `None` path, for any authenticated org (used `compliant_app_client`, which has
   permitted families — proving the 404 here is about the id, not the family gate).

## Out of scope (per task instructions)

`app/features/process_templates/catalog/registry.py:110-111` (`all_templates()`) is
unused dead code, not a coverage gap. No test written for it, not removed — noted here
as a low-priority cleanup candidate for a future pass.

## Test run

```
uv run pytest tests/test_process_templates.py -v
```
37 passed, 0 skipped, 0 failed (0 live-server-marked tests in this file).

```
uv run pytest tests/test_process_templates.py --cov=app/features/process_templates --cov-report=term-missing -q
```
```
Name                                                                   Stmts   Miss  Cover   Missing
----------------------------------------------------------------------------------------------------
app/features/process_templates/__init__.py                                 0      0   100%
app/features/process_templates/catalog/__init__.py                         0      0   100%
app/features/process_templates/catalog/registry.py                        91      1    99%   111
app/features/process_templates/process_templates_bp.py                    17      0   100%
app/features/process_templates/routes/__init__.py                          0      0   100%
app/features/process_templates/routes/api_routes.py                       34      0   100%
app/features/process_templates/routes/page_routes.py                       7      0   100%
app/features/process_templates/services/__init__.py                        0      0   100%
app/features/process_templates/services/process_templates_service.py      66      1    98%   112
----------------------------------------------------------------------------------------------------
TOTAL                                                                    215      2    99%
```
Remaining misses: `registry.py:111` is `all_templates()`'s body — the explicitly
out-of-scope dead code above. `process_templates_service.py:112` is the
`if room_for_description <= 0:` defensive guard inside the now-tested truncation
branch (the suffix itself would need to be >998 chars to trigger it — no catalogue
template name/version combination gets remotely close); not named in this stage's
three gaps and left uncovered.

`uv run pytest tests/ -q` (full suite) was not re-run for this stage — the task scope
is the single file's unit coverage and the full-suite run belongs to the parent
review-feature orchestration, not duplicated per stage.

tests_added: `tests/test_process_templates.py::TestStaticAssetRoute::test_path_traversal_attempt_returns_400`,
`::test_disallowed_extension_returns_400`, `::test_real_js_asset_returns_200`,
`::test_real_css_asset_returns_200`,
`TestBuildDescription::test_no_description_returns_provenance_suffix_alone`,
`::test_short_description_returns_combined_string`,
`::test_long_description_is_truncated_so_suffix_survives_intact`,
`TestMissingTemplateId::test_detail_404_for_template_id_not_in_catalog_at_all`

tests_updated: none

map_rows_changed: row 29 (Industry process template catalogue) — `covered → covered`
(status unchanged; appended a note documenting the three newly-closed gaps and the
99% line-coverage figure with its two named, justified misses)

suite_result: 37 passed, 0 skipped (this file only; no live_server-marked tests here)

evaluator_verdict: valid. All 8 tests assert real, falsifiable claims with exact-match
assertions; mutation spot-checks on all three guarded paths (static-asset guard,
`_build_description` truncation arithmetic, missing-id 404 path) went red when the
guarded behaviour was broken and were restored cleanly (`git status --porcelain -- app/`
verified empty before/during/after). One non-blocking design note: the truncation
test independently hardcodes the same `1000 - len(suffix) - 2` arithmetic as the
production code — confirmed not gamed, since it's an independent computation (not a
call into the function under test) and the mutation probe showed it does catch a
broken formula. Report: `.agents/reports/process_templates/review-test-author-eval.md`

verdict: covered
