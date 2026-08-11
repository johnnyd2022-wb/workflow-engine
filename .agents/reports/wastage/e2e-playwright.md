# E2E: wastage
date: 2026-08-11
mode: chain stage, gap-fill

## Coverage map (before)
`scripts/e2e_coverage.py`: `/core/inventory/dispose` [GET] — covered (hit by
`test_pages_render.py`'s generic smoke test, no content assertions).
`/core/inventory/dispose/confirm` [GET] — listed gap, no coverage at all.

## New file: tests/e2e/test_inventory_dispose_pages.py

| AC | test | result |
|---|---|---|
| AC-D1 (item_ids preselect) | `test_dispose_page_preselects_only_the_requested_item_ids` | pass |
| AC-D2 (happy path remainder) | `test_dispose_confirm_computes_remaining_quantity` | pass |
| AC-D2 (NaN quantity) | `test_dispose_confirm_rejects_non_finite_quantity` | pass |
| AC-D2 (negative quantity) | `test_dispose_confirm_rejects_negative_quantity` | pass |
| AC-D2 (missing item id) | `test_dispose_confirm_missing_item_id_shows_error` | pass |
| AC-D2 (nonexistent item id) | `test_dispose_confirm_nonexistent_item_shows_error` | pass |
| AC-D3/AC33 (cross-tenant, security-audit F1) | `test_org_b_cannot_preview_dispose_org_a_item` | pass |

7/7 new tests pass. Flake check: 3/3 full-file runs green (14.2s/14.3s/14.5s).

## One self-caught false positive during authoring
The cross-tenant test's first draft asserted `"42" not in page_b.content()` (42 was org
A's seeded quantity) — it failed, but on inspection `"42"` matched incidental content in
the page's `<head>` script bundle, not the disclosed item data. Rewritten to scope the
assertion to `page.locator("#dispose-inventory-page").inner_text()` — the actual template
region the item name/unit/quantity render into (`backend.py:784-793`) — which is both a
stronger assertion (proves the *disclosure surface*, not "the string appears somewhere on
a 60KB page") and passes correctly. No app-code finding here; recorded for the report
since a same-shaped mistake would otherwise look like a false "clean" or a false "leak" to
whoever reads this later.

## Full wastage-relevant e2e slice (regression check)
```
pytest tests/e2e/test_inventory_flow.py tests/e2e/test_tenant_isolation.py \
       tests/e2e/test_inventory_dispose_pages.py tests/e2e/test_pages_render.py \
       -k "dispose or wastage or tenant"
22 passed, 30 deselected in 65.45s
```
No regressions in the pre-existing wastage/tenant-isolation coverage.

## ACs with no E2E coverage, and why
- AC12/AC13/AC14/AC16/AC17/AC18 — API-only, already covered by
  `tests/test_wastage.py` (unit/integration level, 25/25 pass) and don't need a browser;
  `test_dispose_inventory_records_wastage` (existing) covers the happy path end to end
  through a real page anyway.
- AC-D1 covers only the preselect case; the tab-filter/type-switch UI in `dispose.html`
  (raw_material/WIP/final_product tabs) has no AC in the spec and is out of this review's
  scope (pure UI state, no security/data implication).

## Follow-up for perf-guardrails
Two new page routes now have real E2E traffic
(`/core/inventory/dispose`, `/core/inventory/dispose/confirm`) — flagging for the
perf-guardrails stage to add them to the measure lists if not already present.

VERDICT: patched
