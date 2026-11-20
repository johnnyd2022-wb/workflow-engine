# Page load assessment

The browser audit covers 91 distinct HTML pages and seeded entry states, including portal orders, OAuth consent, workflow drafts and transfer dockets. The measurements live in the `bize_dev` metrics database. The audit stores individual cold and warm samples with the commit, branch and available CI identifiers.

| Comparison | Baseline run | Follow-up run |
| --- | ---: | ---: |
| Full 20 November browser audit | 1 | 2 |
| Controlled Core and landing diagram rerun | 3 | 4 |
| Dashboard API query count in the existing budget suite | 469 | 468 |

## Findings and fixes

1. The shared SPA loaded seven page-owned stylesheets on routes that did not use them. Each stylesheet now travels with its owning page on direct and boosted visits.
2. Core, Live Inventory and Live Executions sent the same large script in every HTML response. Those pages now share a versioned, cacheable asset.
3. The landing diagram sent an uncompressed document on cold and warm navigation. Its static response now negotiates gzip and keeps separate validators for each representation.
4. The Dashboard API fetched daily and weekly execution counters in separate queries. The follow-up combines them in one database round trip while preserving the tenant and time filters.
5. Workflow detail loaded the execution editor and rendered its hidden modal eagerly. Start Batch and batch card actions open a dedicated screen that loads the editor there. A browser regression test checks the asset boundary and opens a seeded batch step.

6. Core, Live Inventory, and Live Executions defer the shared execution editor until the inventory action needs it. Browser tests check both direct and boosted entry, and a second open reuses the loaded editor.

The remaining largest cold bundles are on Live Executions, Workflow detail, Live Inventory, Core and the Process wizard. The audit identifies the largest resources for each navigation. Representative stock and batch history is needed to rank the remaining API costs.

## Repeat or inspect the assessment

Use an isolated, migrated test application database and the separate metrics database connection described in `scripts/metrics_db.py`. The dedicated browser audit and the transient-state journeys each write a run ID at pytest session teardown.

```bash
export PAGE_LOAD_AUDIT=1 PAGE_LOAD_SAMPLES=3 E2E_ALLOW_TEST_INPROCESS=1
uv run pytest tests/e2e/test_page_load_audit.py -q

uv run pytest tests/e2e/test_mobile_page_audit.py tests/e2e/test_contract_portal.py \
  tests/e2e/test_site_transfers.py tests/e2e/test_mcp_oauth_consent.py -q \
  -k 'xero_tenant_picker or google_second_factor or (publish_invite_and_customer_readonly_portal and 390) or (dispatch_approval_partial_receipt_and_docket and 1440) or consent_page_has_no_sideways_scroll'

uv run python scripts/metrics_db.py page-load-runs
uv run python scripts/metrics_db.py page-load-compare 1 2
uv run python scripts/metrics_db.py page-load-samples 4
uv run python scripts/perf_triage.py --markdown
```

A cold load restores session state into a fresh Chromium context. A warm load revisits the route in the same context. The tests use a 1440 × 900 viewport with a running Flask process and PostgreSQL. Transfer covers same-origin resources and the document. Request counts include cache hits. Query counts cover the HTML document request. The original baseline established Costing access in a separate measurement pass, so some signed-in chrome differed slightly between runs. Local wall time varied with runner load.

Redirect aliases, JSON APIs, downloads, static assets and HTMX fragments are represented by their owning page or destination. CI covers page stylesheet ownership, the cacheable Core script, request waterfalls, and the landing diagram's encoding and validators. API and page budgets continue to use their existing results and baseline tables.
