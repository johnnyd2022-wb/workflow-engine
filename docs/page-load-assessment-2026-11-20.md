# Page load assessment

Measured 91 pages and page states in Chromium against the HTTPS test app on 20 November 2026. The baseline revision was `f3140bf1`. Each row records three paired navigations on a 1440 × 900 viewport. Core, Live Inventory, Live Executions and the landing diagram use five pairs from a final controlled rerun. The cold navigation restored session state into a fresh browser context with an empty browser cache. The warm navigation left the page and revisited the URL in the same context. The Flask process and PostgreSQL stayed running throughout each run.

Transfer size comes from the document and same-origin resource timing entries. Requests count those entries, including browser cache hits. Server query counts cover the HTML document request only. Load measurements wait for initial network activity to settle, but data-dependent readiness varies by page. The audit used a synthetic organisation with a small data set and fixtures for gated detail pages, workflow drafts, OAuth, transfer dockets and portal sessions. Local timings varied while other tests ran and are suitable for triage. The principal before-and-after measurements are transfer size and request count.

## Changes, in priority order

1. **Cold signed-in loads.** Source Map, Inventory view and Workflow detail sheets accounted for about 67, 42 and 35 KB respectively on pages that did not use them. Move those and four smaller sheets into their owning pages' head blocks. The existing boosted response carries the same head assets into the page swap. Pages without any of those seven styles eliminated seven entries and about 195 KB. Each owning page kept its own stylesheet.
2. **Warm Core, Live Inventory and Live Executions.** Those routes rendered the same approximately 143 KB inline script in every document. Serve that script as a versioned Core asset, keeping the boot sequence and the boosted route behavior. Warm transfer fell from 279 to 135 KB on Core, 260 to 116 KB on Live Inventory, and 258 to 115 KB on Live Executions. This adds one cacheable resource to the first visit.
3. **Landing diagram.** The standalone diagram transferred 229 KB in both passes. Serve the static file with negotiated gzip and a browser-private cache policy. The browser measured 159 KB on both passes. The explicit revisit still transferred the document. Gzip saved about 70 KB in both runs.

The largest remaining cold bundles are on Live Executions, Workflow detail, Live Inventory, Core and the Process wizard. For the first four, separate execution modal and page bootstrap work by initial tab before tuning smaller resources. For the wizard, the 167 KB create-process script is the largest observed resource and gives the next target. On the rest of the signed-in pages, verify usage and navigation behavior before removing the remaining globally included Core and CRM assets. Public pages carry substantially less transfer. A production-shaped seed with deep stock and batch history is needed to rank back-end API costs.

## Dashboard API follow-up

The existing budget suite showed the Dashboard summary issuing 52 SQL statements on a fresh test organisation. The daily and weekly operation counters made nine independent calls, including a duplicate active-execution count. They now share one SQL statement. Each count keeps its own tenant, status and time filters, so PostgreSQL can still choose separate index scans.

The controlled rerun measured 44 statements for `/api/core/dashboard/summary`. Its local median was 197 ms before and 199 ms after, so the measured result is eight fewer database round trips. A PostgreSQL regression test asserts that both summaries use one statement per tenant and verifies the daily and weekly counts across two tenants.

## Per-page measurements

Transfer is decimal KB. LCP and TTFB are median milliseconds. Queries report the after-run document count on a cold navigation. An em dash means Chromium did not emit an LCP entry.

| Page | Cold KB | Warm KB | Cold requests | Cold LCP | Warm LCP | Cold TTFB | Queries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `/` | 182.5 → 182.5 | 71.2 → 71.2 | 8 → 8 | 152 → 244 | 48 → 64 | 10 → 26 | 0 |
| `/auth/google/challenge` | 2.8 → 2.8 | 2.8 → 2.8 | 1 → 1 | 52 → 52 | 40 → 36 | 14 → 12 | 0 |
| `/compliant` | 1298.1 → 1103.2 | 74.2 → 73.7 | 69 → 62 | 280 → 344 | 124 → 180 | 19 → 30 | 6 |
| `/compliant/nz-alcohol` | 1355.2 → 1160.3 | 103.6 → 103.0 | 72 → 65 | 376 → 544 | 244 → 340 | 20 → 23 | 7 |
| `/compliant/nz-alcohol/configuration` | 1368.1 → 1173.2 | 113.9 → 113.3 | 73 → 66 | 424 → 644 | 260 → 416 | 19 → 34 | 7 |
| `/compliant/nz-alcohol/customs` | 1402.8 → 1207.9 | 106.1 → 105.5 | 76 → 69 | 516 → 856 | 352 → 544 | 20 → 35 | 7 |
| `/compliant/nz-alcohol/customs/records` | 1390.4 → 1195.5 | 101.4 → 100.9 | 74 → 67 | 312 → 464 | 148 → 284 | 19 → 28 | 7 |
| `/compliant/nz-alcohol/customs/records/<control_id>` | 1389.9 → 1195.3 | 100.9 → 100.6 | 74 → 67 | 580 → 428 | 504 → 560 | 29 → 35 | 7 |
| `/compliant/nz-alcohol/customs/settings` | 1370.6 → 1175.7 | 87.2 → 86.6 | 77 → 70 | 328 → 404 | 164 → 216 | 19 → 32 | 7 |
| `/compliant/nz-alcohol/customs/stock` | 1363.4 → 1168.5 | 79.2 → 78.6 | 76 → 69 | 344 → 432 | 172 → 256 | 21 → 30 | 7 |
| `/compliant/nz-alcohol/customs/transfers` | 1367.7 → 1172.8 | 76.3 → 75.7 | 74 → 67 | 328 → 328 | 172 → 264 | 21 → 32 | 7 |
| `/compliant/nz-alcohol/food-registrations` | 1305.9 → 1111.0 | 76.1 → 75.5 | 72 → 65 | 332 → 424 | 116 → 236 | 22 → 24 | 7 |
| `/compliant/nz-alcohol/food-safety` | 1513.0 → 1318.1 | 237.0 → 236.4 | 75 → 68 | 484 → 640 | 296 → 428 | 20 → 26 | 7 |
| `/compliant/nz-alcohol/food-safety/checks` | 1491.9 → 1297.0 | 230.5 → 229.9 | 72 → 65 | 408 → 736 | 284 → 416 | 23 → 37 | 7 |
| `/compliant/nz-alcohol/licensing` | 1345.1 → 1150.2 | 84.7 → 84.1 | 72 → 65 | 500 → 784 | 308 → 452 | 23 → 28 | 7 |
| `/compliant/nz-alcohol/np3-audit/check/<control_id>` | 1354.3 → 1159.7 | 78.3 → 78.0 | 72 → 65 | 648 → 664 | 428 → 448 | 32 → 35 | 7 |
| `/compliant/nz-alcohol/premises` | 1318.9 → 1124.0 | 77.5 → 76.9 | 72 → 65 | 332 → 380 | 228 → 208 | 24 → 38 | 7 |
| `/compliant/nz-alcohol/wine` | 1347.5 → 1152.8 | 87.1 → 86.8 | 72 → 65 | 416 → 452 | 208 → 288 | 28 → 40 | 7 |
| `/compliant/tools` | 1299.1 → 1104.2 | 103.1 → 102.5 | 71 → 64 | 520 → 460 | 264 → 276 | 42 → 43 | 6 |
| `/core` | 1746.7 → 1551.3 | 278.8 → 135.3 | 88 → 82 | 716 → 688 | 324 → 380 | 33 → 36 | 6 |
| `/core/ai-assistants` | 1283.2 → 1088.3 | 79.0 → 78.4 | 72 → 65 | 412 → 392 | 164 → 212 | 34 → 30 | 6 |
| `/core/cases` | 1268.0 → 1073.1 | 74.1 → 73.5 | 71 → 64 | 336 → 448 | 168 → 164 | 21 → 28 | 6 |
| `/core/cases/<case_id>` | 1306.3 → 1111.3 | 75.5 → 74.9 | 73 → 66 | 728 → 664 | 372 → 372 | 32 → 40 | 7 |
| `/core/cases/new` | 1266.0 → 1071.0 | 73.6 → 73.0 | 70 → 63 | 408 → 492 | 220 → 272 | 23 → 39 | 6 |
| `/core/contracts` | 1276.1 → 1081.2 | 77.9 → 77.4 | 70 → 63 | 332 → 440 | 172 → 188 | 39 → 45 | 11 |
| `/core/contracts/<order_id>` | 1280.1 → 1085.2 | 74.7 → 74.2 | 71 → 64 | 488 → 440 | 244 → 280 | 65 → 49 | 14 |
| `/core/contracts/<order_id>/portal-sharing` | 1269.6 → 1074.7 | 75.2 → 74.6 | 70 → 63 | 496 → 468 | 188 → 208 | 72 → 75 | 17 |
| `/core/contracts/materials` | 1267.4 → 1072.5 | 73.0 → 72.4 | 70 → 63 | 352 → 324 | 132 → 200 | 24 → 26 | 8 |
| `/core/costing/costs` | 1366.0 → 1169.8 | 86.1 → 84.2 | 78 → 71 | 460 → 516 | 208 → 356 | 22 → 25 | 6 |
| `/core/costing/margins` | 1273.5 → 1078.9 | 73.7 → 73.4 | 71 → 64 | 348 → 452 | 248 → 356 | 19 → 26 | 6 |
| `/core/costing/purchases` | 1296.1 → 1101.4 | 76.9 → 76.6 | 70 → 63 | 436 → 468 | 188 → 236 | 28 → 35 | 8 |
| `/core/costing/rules` | 1292.3 → 1097.6 | 76.0 → 75.7 | 71 → 64 | 524 → 560 | 276 → 292 | 28 → 35 | 6 |
| `/core/dashboard` | 1296.3 → 1125.3 | 86.4 → 87.0 | 71 → 65 | 328 → 448 | 152 → 220 | 25 → 37 | 6 |
| `/core/executions/<execution_id>/steps/<step_id>/record` | 1254.7 → 1059.8 | 72.9 → 72.3 | 69 → 62 | 576 → 320 | 148 → 188 | 37 → 54 | 8 |
| `/core/executions/live` | 1812.1 → 1616.7 | 258.2 → 114.7 | 94 → 88 | 692 → 676 | 360 → 364 | 34 → 38 | 6 |
| `/core/flows` | 1794.1 → 1634.7 | 110.5 → 110.0 | 93 → 87 | 408 → 568 | 140 → 200 | 24 → 37 | 6 |
| `/core/flows/batches/start` | 1582.9 → 1382.0 | 105.1 → 98.5 | 100 → 93 | 1092 → 1052 | 668 → 720 | 36 → 42 | 7 |
| `/core/flows/create/evidence-and-prompts` | 1662.7 → 1468.0 | 113.8 → 113.5 | 106 → 99 | 712 → 636 | 264 → 272 | 47 → 37 | 8 |
| `/core/flows/create/inputs` | 1661.0 → 1465.7 | 112.1 → 111.2 | 107 → 100 | 428 → 380 | 232 → 268 | 49 → 42 | 8 |
| `/core/flows/create/next-steps` | 1684.3 → 1489.7 | 114.3 → 114.0 | 106 → 99 | 620 → 592 | 236 → 260 | 37 → 52 | 8 |
| `/core/flows/create/outputs` | 1657.7 → 1463.1 | 108.8 → 108.5 | 105 → 98 | 664 → 724 | 224 → 156 | 41 → 48 | 8 |
| `/core/flows/create/process-overview` | 1651.7 → 1456.8 | 102.8 → 102.2 | 104 → 97 | 764 → 616 | 232 → 204 | 131 → 70 | 3 |
| `/core/flows/create/start` | 1251.6 → 1056.7 | 72.8 → 72.3 | 68 → 61 | 396 → 408 | 124 → 176 | 27 → 34 | 6 |
| `/core/flows/create/step-name` | 1658.6 → 1463.9 | 109.7 → 109.4 | 105 → 98 | 680 → 820 | 308 → 344 | 41 → 43 | 8 |
| `/core/flows/create/summary` | 1653.7 → 1459.1 | 104.9 → 104.5 | 106 → 99 | 656 → 740 | 236 → 316 | 35 → 43 | 8 |
| `/core/flows/create/template-catalog` | 1284.0 → 1089.0 | 91.3 → 90.7 | 72 → 65 | 512 → 412 | 224 → 176 | 27 → 25 | 6 |
| `/core/getting-started` | 1262.7 → 1067.8 | 74.2 → 73.6 | 71 → 64 | 312 → 556 | 196 → 304 | 19 → 34 | 6 |
| `/core/go-live` | 1271.0 → 1076.1 | 81.0 → 80.4 | 71 → 64 | 380 → 496 | 168 → 212 | 31 → 36 | 6 |
| `/core/integrations` | 1260.2 → 1065.3 | 76.0 → 75.4 | 70 → 63 | 420 → 360 | 124 → 196 | 32 → 40 | 6 |
| `/core/inventory/add` | 1252.5 → 1057.6 | 73.7 → 73.2 | 68 → 61 | 372 → 424 | 168 → 140 | 24 → 26 | 6 |
| `/core/inventory/add/barcode` | 1353.0 → 1158.1 | 82.2 → 81.6 | 73 → 66 | 448 → 392 | 168 → 216 | 41 → 28 | 6 |
| `/core/inventory/add/csv` | 1343.5 → 1148.7 | 109.2 → 108.7 | 72 → 65 | 472 → 400 | 192 → 204 | 33 → 32 | 6 |
| `/core/inventory/add/manual` | 1326.4 → 1131.5 | 92.1 → 91.6 | 72 → 65 | 436 → 364 | 204 → 196 | 29 → 27 | 6 |
| `/core/inventory/dispose` | 1264.2 → 1069.3 | 85.4 → 84.9 | 69 → 62 | 396 → 420 | 156 → 152 | 37 → 28 | 6 |
| `/core/inventory/dispose/confirm` | 1255.7 → 1060.8 | 77.0 → 76.4 | 68 → 61 | 528 → 408 | 136 → 192 | 58 → 47 | 8 |
| `/core/inventory/live` | 1727.8 → 1532.4 | 259.9 → 116.4 | 89 → 83 | 520 → 540 | 212 → 144 | 34 → 28 | 6 |
| `/core/inventory/view` | 1396.6 → 1244.6 | 79.7 → 79.5 | 76 → 70 | 372 → 368 | 196 → 180 | 26 → 29 | 6 |
| `/core/notifications` | 1280.0 → 1085.0 | 74.2 → 73.7 | 71 → 64 | 480 → 340 | 176 → 200 | 42 → 32 | 6 |
| `/core/people` | 1298.6 → 1103.7 | 84.9 → 84.3 | 73 → 66 | 448 → 324 | 192 → 208 | 33 → 30 | 6 |
| `/core/planner` | 1287.7 → 1092.8 | 78.9 → 78.3 | 74 → 67 | 784 → 732 | 452 → 472 | 32 → 45 | 6 |
| `/core/planner/board` | 1312.8 → 1117.9 | 81.9 → 81.3 | 77 → 70 | 400 → 420 | 460 → 436 | 29 → 29 | 6 |
| `/core/processes` | 1279.2 → 1094.2 | 91.7 → 91.9 | 70 → 64 | 584 → 356 | 284 → 192 | 29 → 20 | 6 |
| `/core/record` | 1268.9 → 1074.3 | 73.8 → 73.6 | 71 → 64 | 424 → 300 | 196 → 188 | 26 → 38 | 6 |
| `/core/settings` | 1354.5 → 1166.5 | 98.8 → 98.3 | 74 → 68 | 420 → 432 | 168 → 140 | 32 → 46 | 7 |
| `/core/site-transfers` | 1273.0 → 1078.0 | 76.4 → 75.8 | 72 → 65 | 372 → 324 | 152 → 148 | 24 → 28 | 6 |
| `/core/site-transfers/<transfer_id>/docket` | 8.2 → 8.2 | 3.0 → 3.0 | 2 → 2 | 100 → 92 | 64 → 60 | 52 → 53 | 7 |
| `/core/sites` | 1278.5 → 1083.5 | 76.2 → 75.6 | 71 → 64 | 540 → 604 | 272 → 324 | 22 → 26 | 6 |
| `/core/sourcemap` | 1399.3 → 1273.9 | 84.2 → 85.8 | 78 → 72 | 372 → 344 | 164 → 144 | 24 → 38 | 6 |
| `/core/stocktake` | 1297.3 → 1102.4 | 79.8 → 79.2 | 72 → 65 | 304 → 344 | 140 → 160 | 23 → 25 | 6 |
| `/core/suppliers` | 1280.2 → 1096.0 | 74.4 → 74.4 | 72 → 66 | 456 → 532 | 232 → 300 | 24 → 33 | 6 |
| `/core/tasks/configuration` | 1265.4 → 1070.5 | 76.0 → 75.4 | 70 → 63 | 468 → 604 | 240 → 376 | 22 → 26 | 6 |
| `/crm` | 1305.3 → 1110.5 | 116.7 → 116.2 | 75 → 68 | 540 → 584 | 276 → 360 | 25 → 26 | 6 |
| `/crm/analytics` | 1328.1 → 1133.3 | 104.7 → 104.3 | 74 → 67 | 312 → 328 | 140 → 160 | 20 → 23 | 6 |
| `/crm/configuration` | 1282.6 → 1088.3 | 92.7 → 92.8 | 75 → 68 | 312 → 392 | 136 → 140 | 23 → 36 | 6 |
| `/crm/customers` | 1276.6 → 1081.7 | 88.9 → 88.3 | 71 → 64 | 460 → 448 | 276 → 308 | 22 → 25 | 6 |
| `/crm/customers/<contact_id>` | 1354.4 → 1159.4 | 124.4 → 123.8 | 75 → 68 | 856 → 796 | 584 → 504 | 35 → 36 | 6 |
| `/crm/excise` | 1305.1 → 1110.4 | 81.7 → 81.3 | 70 → 63 | 292 → 404 | 128 → 224 | 19 → 34 | 7 |
| `/crm/matching` | 1303.3 → 1108.7 | 79.9 → 79.6 | 70 → 63 | 300 → 320 | 112 → 124 | 20 → 31 | 6 |
| `/crm/tasks` | 1382.5 → 1187.6 | 98.7 → 98.1 | 77 → 70 | 464 → 508 | 276 → 304 | 22 → 24 | 7 |
| `/crm/xero/select-tenant` | 1299.2 → 1104.3 | 75.8 → 75.3 | 69 → 62 | 416 → 504 | 160 → 196 | 36 → 45 | 6 |
| `/invite/<token>` | 7.9 → 7.9 | 7.9 → 7.9 | 1 → 1 | 48 → 60 | 40 → 44 | 14 → 21 | 2 |
| `/landing-diagram` | 228.7 → 158.8 | 228.7 → 158.8 | 1 → 1 | 96 → 124 | 64 → 68 | 11 → 13 | 0 |
| `/oauth/authorize` | 7.4 → 7.4 | 7.4 → 7.4 | 1 → 1 | 96 → 88 | 68 → 76 | 53 → 34 | 9 |
| `/portal` | 5.0 → 5.0 | 5.0 → 5.0 | 3 → 3 | 112 → 132 | 80 → 104 | 44 → 63 | 5 |
| `/portal/invite` | 4.9 → 4.9 | 4.9 → 4.9 | 3 → 3 | 68 → 64 | 64 → 56 | 14 → 11 | 0 |
| `/portal/invite (valid invitation)` | 4.9 → 4.9 | 4.9 → 4.9 | 3 → 3 | 68 → 80 | 64 → 80 | 10 → 15 | 0 |
| `/portal/login` | 4.7 → 4.7 | 4.7 → 4.7 | 3 → 3 | 60 → 60 | 56 → 56 | 15 → 11 | 0 |
| `/portal/orders/<order_id>` | 7.3 → 7.3 | 7.3 → 7.3 | 3 → 3 | 108 → 140 | 104 → 100 | 41 → 64 | 9 |
| `/pricing` | 108.3 → 108.3 | 6.6 → 6.6 | 5 → 5 | 60 → 80 | 36 → 40 | 7 → 10 | 0 |
| `/privacy` | 109.2 → 109.2 | 7.5 → 7.5 | 5 → 5 | 72 → 84 | 44 → 36 | 9 → 14 | 0 |
| `/terms` | 109.3 → 109.3 | 7.6 → 7.6 | 5 → 5 | 72 → 84 | 44 → 36 | 9 → 13 | 0 |

## Repeat the assessment

Run against an isolated, migrated test database. Use a fresh output path for each run because the runner appends one row per navigation.

```bash
export PAGE_LOAD_REPORT=/tmp/page-load-audit.jsonl PAGE_LOAD_SAMPLES=3 E2E_ALLOW_TEST_INPROCESS=1
uv run pytest tests/e2e/test_page_load_audit.py -q

uv run pytest tests/e2e/test_mobile_page_audit.py tests/e2e/test_contract_portal.py \
  tests/e2e/test_site_transfers.py tests/e2e/test_mcp_oauth_consent.py -q \
  -k 'xero_tenant_picker or google_second_factor or (publish_invite_and_customer_readonly_portal and 390) or (dispatch_approval_partial_receipt_and_docket and 1440) or consent_page_has_no_sideways_scroll'
```

The audit covers distinct HTML pages and seeded entry states. Redirect aliases such as `/dashboard` and `/crm/tastings`, JSON APIs, downloads, static assets and HTMX fragments are represented by their owning destination or page. The first baseline sweep used the original mobile audit's access fixture. Costing and the seeded states were measured in a follow-up with the audit's Costing entitlement. This changes signed-in chrome slightly between some baseline and follow-up rows. The cold transfer reductions primarily reflect the omitted resource entries.

CI tests cover page stylesheet ownership, the cacheable Core script and the diagram's caching, negotiated encoding and validators. Existing API query budgets and Semgrep performance rules still run on their established CI paths.
