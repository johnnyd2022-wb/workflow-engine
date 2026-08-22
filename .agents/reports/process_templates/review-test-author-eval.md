# TEST EVALUATION — 2026-08-22

batch: `tests/test_process_templates.py` (uncommitted local diff, `git diff -- tests/test_process_templates.py`), three new classes:
- `TestStaticAssetRoute` (4 tests) — `app/features/process_templates/process_templates_bp.py:31-33`'s path-traversal/extension guard on `GET /process-templates/static/<path:filename>`
- `TestBuildDescription` (3 tests) — `app/features/process_templates/services/process_templates_service.py:104-113`'s `_build_description`, called directly with synthetic `ProcessTemplate` objects
- `TestMissingTemplateId` (1 test) — `app/features/process_templates/catalog/registry.py:118`'s `get_template_by_id` returning `None` for a catalogue-wide-missing id, via `GET /api/core/process-templates/<template_id>` → 404

All 8 tests are net-new (no prior versions to diff against for widening/deletion).

## static

| test | asserts real claim | diff-widened | tautology | sense check |
|---|---|---|---|---|
| `test_path_traversal_attempt_returns_400` | yes, exact `== 400` | n/a (new) | no | name matches: hits the `..` branch of the guard |
| `test_disallowed_extension_returns_400` | yes, exact `== 400` | n/a (new) | no | name matches: hits the extension branch |
| `test_real_js_asset_returns_200` | yes, exact `== 200` | n/a (new) | no | proves the guard doesn't false-positive on a real `.js`; `template-catalog.js` exists on disk (confirmed) |
| `test_real_css_asset_returns_200` | yes, exact `== 200` | n/a (new) | no | same, `.css`, file confirmed to exist |
| `test_no_description_returns_provenance_suffix_alone` | yes, exact string `==` | n/a (new) | no | matches `if not template.description` branch |
| `test_short_description_returns_combined_string` | yes, exact string `==` | n/a (new) | no | matches the `combined <= 1000` branch |
| `test_long_description_is_truncated_so_suffix_survives_intact` | yes, exact string `==`, plus length/count checks | n/a (new) | borderline — see note below | matches the truncation branch; description length (990) plus suffix forces `combined` past 1000 |
| `test_detail_404_for_template_id_not_in_catalog_at_all` | yes, direct registry call + HTTP `== 404` | n/a (new) | no | docstring correctly distinguishes this from the existing wrong-family 404 test, and the assertion path matches the claim |

**Tautology note (`test_long_description_is_truncated...`)**: the test independently recomputes `room_for_description = 1000 - len(suffix) - 2`, which mirrors the production formula at `process_templates_service.py:110` (`_DESCRIPTION_MAX_LEN - len(suffix) - 2`). This is the "recomputes the expected value" pattern the skill flags — but it's a hardcoded independent computation in the test (magic `1000`, not an import of `_DESCRIPTION_MAX_LEN`, and no call into `_build_description`'s internals), not a call into the function under test. The mutation probe below settles it empirically: when I broke the production formula, this test's independently-hardcoded expectation caught it. Recorded as a design note, not a finding — falsifiability was verified directly, not just inferred from the pattern.

All new imports (`ProcessTemplate`, `TemplateOutput`, `ProcessCategory`, `service`, `registry`) resolve correctly against the module surface; `ProcessTemplate`/`TemplateOutput` field names in the synthetic template match the real dataclasses in `registry.py`. `app_client`/`compliant_app_client` fixtures are authenticated (log in via `/auth/login` in fixture setup), so `@requires_auth` on the static route is genuinely exercised, not bypassed.

## mutations

Risk ranking: the static-asset guard is a security control (path traversal / arbitrary-extension serving) → always probe. The missing-template-id 404 sits next to tenant-boundary logic (though this specific test is the "doesn't exist anywhere" case, not a cross-org case) → probed. `_build_description` is cosmetic/presentational → sampled (truncation branch, the most complex one).

| test | mutation | expected | observed |
|---|---|---|---|
| `test_path_traversal_attempt_returns_400` + `test_disallowed_extension_returns_400` | `process_templates_bp.py`: replaced the guard condition with `if False:` (neuters path-traversal + extension check entirely) | both red | **both FAILED** (red) — confirmed, then restored via `git checkout --` |
| `test_real_js_asset_returns_200` + `test_real_css_asset_returns_200` | same mutation (guard disabled) | stay green (guard being open doesn't break the legit-asset path) | **both PASSED** (green), as expected — these two only guard against false positives, not the security property, so this run doesn't falsify them; they're covered by the extension-branch logic itself, which the other two tests do probe |
| `test_long_description_is_truncated_so_suffix_survives_intact` | `process_templates_service.py:110`: `room_for_description = _DESCRIPTION_MAX_LEN - len(suffix)` (dropped the `- 2` for `"\n\n"`) | red | **FAILED** (red) — confirmed, then restored |
| `test_detail_404_for_template_id_not_in_catalog_at_all` | `registry.py:118`: `get_template_by_id` returns `_CATALOG[0]` instead of `None` on a miss | red (both the direct-call assertion and the HTTP 404 assertion) | **FAILED** (red) — confirmed, then restored |

Tree verified clean after every restore (`git status --porcelain -- app/` empty each time); `git diff -- app/` empty at end of session. No mutation left behind.

Full batch re-run after all restores: `tests/test_process_templates.py::TestStaticAssetRoute tests/test_process_templates.py::TestBuildDescription tests/test_process_templates.py::TestMissingTemplateId` → `8 passed`.

## findings

None.

## verdict

valid
