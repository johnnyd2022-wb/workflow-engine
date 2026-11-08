# REVIEW: crm
date: 2026-10-18
baseline: tests green (295 CRM unit tests + tests/js; see baseline.md)
verdict: patched
previous review: 2026-08-15 (in git history; its open finding 4 is carried below as O5)

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration audit | not re-run | 0 | no model/migration change in this review (baseline.md) |
| security-audit (semgrep, repo rules) | clean | 0 | `semgrep --config .semgrep/rules/ app/features/crm` exit 0 |
| security-tenant-audit (Codex, read-only) | findings-open | 3 (none exploitable cross-tenant) | security-tenant-audit.md |
| orchestrator code review | patched | 9 fixed | this report |
| e2e-playwright | clean, no gap-fill | 0 | 38 passed: test_crm_contact_sync_ui, test_crm_flow, test_sales_design |
| unit coverage | 77% of app/features/crm (unit only) | — | below |
| test-evaluator (Codex, read-only) | valid (round 2) | round 1: 3 invalid, all fixed | test-evaluator.md |
| perf-guardrails | not run | — | no new queries on a page path; route shapes unchanged |
| observability | patched | 2 events added | `crm_xero_call_refused`, `crm_xero_call_failed` |
| ci-gate | clean, already wired | 0 | new tests live in collected files; tests/js/*.test.js is globbed by tests/test_execution_shared_utils_js.py |

## Scope
The `crm` slice: `/crm/*` pages, `/api/crm/*`, `app/features/crm/`. Asked for by the founder
("review all of CRM for bugs") after customers became creatable in Biz-E and synced to Xero,
postal/street address editing (!527), and invoicing/Xero sync changes. `depended on by:
dashboard` (flag check only). MR !538 (customers list `newCustomer.form.address.line1`) is
open and unmerged; this review does not touch that fix. Its `customers.js` change and this
one touch different hunks of the file.

## Every CRM route: auth and org scoping
All 69 `/crm/*` and `/api/crm/*` route+method pairs carry `@requires_auth`, resolve to a
named permission in `app/core/security/access_policy.py` (none falls to `DENY`), and are
CSRF-protected by the app-wide hook (no exemption). Every DB read and write they reach is
filtered by the caller's `org_id`, explicitly or, where noted in security-tenant-audit.md
(O3), by the global tenant filter. No response returns another organisation's data. The
table was generated from the app's URL map and `requirement_for()`, and independently
re-derived by the Codex tenant audit, which agreed with it on every row.

| route | method | endpoint | permission (`requirement_for`) | org scoping |
|---|---|---|---|---|
| `/api/crm/analytics/churn-risk` | GET | `churn_risk` | sales.view | yes |
| `/api/crm/analytics/customer-breakdown` | GET | `customer_breakdown` | sales.view | yes |
| `/api/crm/analytics/customer-contact` | GET | `customer_contact` | sales.view | yes |
| `/api/crm/analytics/monthly-sales` | GET | `monthly_sales` | sales.view | yes |
| `/api/crm/analytics/rankings` | GET | `rankings` | sales.view | yes |
| `/api/crm/contact-sync-settings` | GET | `get_contact_sync_settings` | sales.view | yes |
| `/api/crm/contact-sync-settings` | PUT | `update_contact_sync_settings` | sales.manage | yes |
| `/api/crm/customers` | GET | `list_customers` | sales.view | yes |
| `/api/crm/customers` | POST | `create_customer` | sales.record | yes |
| `/api/crm/customers/<contact_id>` | GET | `get_customer` | sales.view | yes — foreign id 404s |
| `/api/crm/customers/<contact_id>` | PATCH | `update_customer` | sales.record | yes — foreign id 404s (`ContactSyncService._get`) |
| `/api/crm/customers/<contact_id>/analytics` | GET | `get_customer_analytics` | sales.view | yes |
| `/api/crm/customers/<contact_id>/invoice-defaults` | GET | `get_customer_invoice_defaults` | sales.view | yes — contact ownership checked |
| `/api/crm/customers/<contact_id>/invoices` | GET | `get_customer_invoices` | sales.view | yes — foreign contact gives an empty list |
| `/api/crm/customers/<contact_id>/invoices` | POST | `create_customer_invoice` | sales.record | yes — contact ownership checked before Xero is called |
| `/api/crm/customers/<contact_id>/line-item-descriptions` | GET | `get_customer_line_item_descriptions` | sales.view | yes |
| `/api/crm/customers/<contact_id>/line-item-pricing` | GET | `get_customer_line_item_pricing` | sales.view | yes |
| `/api/crm/customers/<contact_id>/notes` | POST | `create_note` | sales.record | yes — contact ownership checked (2026-08-15 fix) |
| `/api/crm/customers/<contact_id>/xero-sync` | PUT | `set_customer_xero_sync` | sales.record | yes — foreign id 404s |
| `/api/crm/customers/<contact_id>/xero-sync/retry` | POST | `retry_customer_xero_sync` | sales.record | yes — foreign id 404s |
| `/api/crm/final-products` | GET | `list_final_products` | sales.view | yes |
| `/api/crm/invoices` | GET | `get_org_invoices` | sales.view | yes |
| `/api/crm/invoices/<invoice_id>/authorise` | POST | `authorise_invoice` | sales.record | yes — local invoice looked up by (id, org) |
| `/api/crm/invoices/<invoice_id>/pdf` | GET | `get_invoice_pdf` | sales.view | yes — (id, org) |
| `/api/crm/invoices/<invoice_id>/trace-items` | GET | `get_invoice_trace_items` | sales.view | yes — invoice and allocations both filtered by org |
| `/api/crm/invoices/<invoice_id>/view-url` | GET | `get_invoice_view_url` | sales.view | yes — (id, org) |
| `/api/crm/line-item-descriptions` | GET | `get_org_line_item_descriptions` | sales.view | yes |
| `/api/crm/matching` | GET | `get_matching_queue` | sales.view | yes |
| `/api/crm/matching/assign` | POST | `assign_matching_line` | sales.record + inventory.adjust (route check) | yes — invoice, site, inventory item scoped; see open O1 (permission) |
| `/api/crm/matching/candidates` | GET | `get_matching_candidates` | sales.view | yes — `site_id` resolved against the org |
| `/api/crm/matching/confirm` | POST | `confirm_matching_line` | sales.record | yes — allocation filtered by org |
| `/api/crm/matching/run` | POST | `run_matching` | sales.record + inventory.adjust (route check) | yes; see open O1 (permission) |
| `/api/crm/notes/<note_id>` | DELETE | `delete_note` | sales.record | yes |
| `/api/crm/notes/<note_id>` | PUT | `update_note` | sales.record | yes |
| `/api/crm/overview` | GET | `crm_overview` | sales.view | yes |
| `/api/crm/product-mappings` | GET | `list_mappings` | sales.view | yes |
| `/api/crm/product-mappings` | POST | `create_mapping` | sales.manage | row scoped; see open O2 (`biz_e_source_output_id` unchecked) |
| `/api/crm/product-mappings/<mapping_id>` | DELETE | `delete_mapping` | sales.manage | yes — foreign id 404s |
| `/api/crm/product-mappings/<mapping_id>` | PUT | `update_mapping` | sales.manage | (id, org); see open O2 |
| `/api/crm/product-mappings/bulk` | POST | `create_mappings_bulk` | sales.manage | rows scoped; see open O2 |
| `/api/crm/tasks` | GET | `list_tasks` | sales.view | yes |
| `/api/crm/tasks` | POST | `create_task` | sales.record | yes — contact checked; **assignee now checked (fixed here, F5)** |
| `/api/crm/tasks/<task_id>` | DELETE | `delete_task` | sales.record | yes |
| `/api/crm/tasks/<task_id>` | PUT | `update_task` | sales.record | yes — task, contact; **assignee now checked (fixed here, F5)** |
| `/api/crm/tasks/<task_id>/lane` | PUT | `assign_task_lane` | sales.record | yes — task and lane both (org, board) |
| `/api/crm/tasks/lanes` | GET | `list_task_lanes` | sales.view | yes |
| `/api/crm/tasks/lanes` | POST | `create_task_lane` | sales.record | yes |
| `/api/crm/tasks/lanes/<lane_id>` | DELETE | `delete_task_lane` | sales.record | yes |
| `/api/crm/tasks/lanes/<lane_id>` | PUT | `update_task_lane` | sales.record | yes |
| `/api/crm/tasks/lanes/order` | PUT | `reorder_task_lanes` | sales.record | yes — rejects ids not exactly the org's board |
| `/api/crm/traceability-config` | GET | `get_traceability_config` | sales.view | yes |
| `/api/crm/traceability-config` | PUT | `update_traceability_config` | sales.manage | yes |
| `/api/crm/xero/auth-url` | GET | `xero_auth_url` | sales.manage | n/a (session state only) |
| `/api/crm/xero/disconnect` | POST | `xero_disconnect` | sales.manage | yes |
| `/api/crm/xero/status` | GET | `xero_status` | sales.view | yes |
| `/api/crm/xero/sync` | POST | `xero_sync` | sales.manage | yes |
| `/crm` | GET | `crm_index` | sales.view | n/a (page shell; data comes from the scoped APIs) |
| `/crm/analytics` | GET | `crm_analytics` | sales.view | n/a (page shell; data comes from the scoped APIs) |
| `/crm/configuration` | GET | `crm_configuration` | sales.manage | n/a (page shell; data comes from the scoped APIs) |
| `/crm/customers` | GET | `crm_customers` | sales.view | n/a (page shell; data comes from the scoped APIs) |
| `/crm/customers/<contact_id>` | GET | `crm_customer_detail` | sales.view | n/a (page shell; data comes from the scoped APIs) |
| `/crm/matching` | GET | `crm_matching` | sales.view | n/a (page shell; data comes from the scoped APIs) |
| `/crm/static/css/<path:filename>` | GET | `serve_crm_css` | public | n/a (static file; `@requires_auth`, fixed dir and extension) |
| `/crm/static/js/<path:filename>` | GET | `serve_crm_js` | public | n/a (static file; `@requires_auth`, fixed dir and extension) |
| `/crm/tasks` | GET | `crm_tasks` | sales.view | n/a (page shell; data comes from the scoped APIs) |
| `/crm/xero/auth` | GET | `xero_auth` | sales.manage | n/a (session state only) |
| `/crm/xero/callback` | GET | `xero_callback` | sales.manage | yes — OAuth `state` checked against the session; token/tenant writes scoped |
| `/crm/xero/select-tenant` | GET | `xero_select_tenant_page` | sales.manage | n/a (session state only) |
| `/crm/xero/select-tenant` | POST | `xero_select_tenant_submit` | sales.manage | yes — tenant must be in the session's pending list |

## Findings fixed (each reproduced by a test that failed before the fix)

All bug tests below were run against `origin/main`'s versions of the changed app files
(`git checkout origin/main -- <files>`) and failed there, while the `[CONTROL]` tests passed.

### F1 [FIXED] An invoice Xero refused was reported as created
`XeroAPIClient.create_invoice` sends `summarize_errors=False`, which makes Xero answer **200**
for a refused invoice, carrying its `ValidationErrors` (and an all-zero InvoiceID). The
client returned that as the created invoice; the route answered 201, emitted
`crm_invoice.created`, and the modal closed. Nothing existed in Xero (e.g. an invalid
account code).
**Fix**: `xero_api_client.py` raises `ValueError` with Xero's messages; the route already
turns that into a 400 the modal shows.
**Test**: `tests/test_xero_api_client.py::TestCreateInvoice::test_an_invoice_xero_refused_is_an_error_in_xeros_words_not_a_created_invoice`

### F2 [FIXED] A retried invoice create could make a second invoice
`_call_with_retry` retries on 500/503, and a 5xx can arrive after Xero made the invoice.
Contacts already sent an idempotency key; invoices did not.
**Fix**: one `bize-invoice-<uuid4>` key per `create_invoice` call, sent on every attempt.
**Tests**: `…::test_a_create_retried_after_a_server_error_sends_the_same_idempotency_key`,
`…::test_two_separate_creates_do_not_share_an_idempotency_key`

### F3 [FIXED] Xero refusals and an expired connection were a bare 500 on the invoice routes
Create, authorise, PDF and view-link caught only `XeroInsufficientScopeError` and
`ValueError`. A Xero 400 (`ApiException`, e.g. "Invoice not of valid status for
modification"), `XeroTokenExpiredError`, or a network error raised out of the view, and
the page showed "HTTP 500".
**Fix**: `api_routes._xero_failure`: expired → 401 `action: reconnect_xero`; Xero refusal
→ 400 with Xero's message; unreachable → 502 with a message; logged as
`crm_xero_call_refused` / `crm_xero_call_failed`. Exceptions that are not Xero or network
errors still raise (a Biz-E bug stays a 500).
**Tests**: `tests/test_crm.py::TestXeroFailuresOnInvoiceRoutes` (3)

### F4 [FIXED] An edit after a failed send left Xero without the earlier edit, then the pull undid it
`ContactSyncService.update_contact` sent only the fields of the current edit. After a failed
send (Xero down, not connected), the next successful edit sent its own field and marked the
contact `synced`. The pull then overwrote the earlier edit with Xero's old value. A Biz-E
contact never yet in Xero was created there from that one edit: name plus one field, no
email or address.
**Fix**: when Xero is behind (no Xero id yet, or `xero_push_status` pending/failed), the edit
sends every field.
**Tests**: `tests/test_crm_contact_sync.py::test_after_a_failed_send_the_next_edit_also_sends_what_xero_missed`,
`…::test_a_contact_xero_never_got_is_created_with_all_its_details_on_its_next_edit`

### F5 [FIXED] CRM tasks accepted another organisation's user as assignee
`create_task`/`update_task` stored any UUID as `assigned_to_user_id`. Core tasks only accept
an active user of the caller's org (`app/core/backend/tasks.py::_parse_optional_user`). A
foreign user id was stored, which is a cross-tenant reference and tells the caller that
user id exists. An unknown id hit the foreign key and answered 500.
**Fix**: CRM tasks use the same check (400, `access_denied` logged).
**Tests**: `tests/test_crm.py::TestCRMTaskAssignee` (3 + control)

### F6 [FIXED] "Active" on the customers list hid every customer made in Biz-E
Biz-E contacts have no Xero `contact_status` until Xero sends one, and the filter compared
the column directly, so NULL never matched. `list_customers_for_org` already treated NULL
as ACTIVE.
**Fix**: the filter does the same (`coalesce(contact_status, 'ACTIVE')`).
**Tests**: `tests/test_crm.py::TestCustomerStatusFilter` (1 + control)

### F7 [FIXED] Manual "Sync" said it worked when it failed
`POST /api/crm/xero/sync` answered 200 `ok: true` whatever happened, and the three pages that
call it (customers, configuration, integrations card) only checked the status. A sync that
failed outright looked like one that worked.
**Fix**: `ok` follows the result. A sync that brought nothing in is a 502 with an `error`.
A partial one is a 200 with `ok: false` and an `error`, and each page now shows that error.
**Tests**: `tests/test_crm.py::TestManualSyncFailures` (2 + control),
`tests/js/crm-configuration.test.js` "a sync that only partly finished shows why on the page" (+ control)

### F8 [FIXED] Every customer page threw on load (same fault as !538, on the detail page)
The Edit details form is in the page from the start (hidden), so Alpine evaluates
`editForm.addresses[kind].line1` for both address types on load. The initial `editForm` was
`{}`, so every `/crm/customers/<id>` logged "Cannot read properties of undefined (reading
'POBOX')". !538 fixes only the list page's New customer form.
**Fix**: `blankEditForm()` gives the hidden form every field it binds to.
**Test**: `tests/js/crm-customer-detail.test.js`. It reads the form's `x-model` bindings
from the template, so a field added there is checked too.

### F9 [FIXED] Sales users were offered Xero buttons and links that refuse them
`/crm/customers` showed **Sync** and **Connect Xero** to everyone who can see Sales, but both
need `sales.manage` (`crm.crm_oauth.*`). For the built-in Sales role, Sync answered "You
don't have permission to do this." and Connect Xero bounced to the dashboard. The same
happened with Overview's "Map" / "Review product mappings" and Batch matching's "Change mode"
(all `/crm/configuration`, a `sales.manage` page).
**Fix**: those controls render only for `can('sales.manage')`.
**Tests**: `tests/test_crm.py::TestCustomersPageXeroButtons` (2 + control). These were
written after the main-swap run above; each was seen failing before its template change.

## Findings left open (with why)

- **O1 — Medium, needs a product decision: Sales permissions change stock.** (Codex F1)
  `POST /api/crm/matching/assign` and `/matching/run` need only `sales.record`, but consume
  or restore `InventoryItem.quantity`. So do creating an AUTHORISED invoice and authorising
  one, through the follow-up sync. The built-in Sales role has `sales.record` and not
  `inventory.adjust`. Either sales-driven stock depletion is part of `sales.record` (then
  the permission text should say so), or these routes need `inventory.adjust` too, which
  would stop Sales users matching batches. That is the founder's call, not a patch.
  Since findings-sweep 2026-10-24 (an unattended proposal for the founder to confirm or reverse):
  `/matching/assign` and `/matching/run` also require `inventory.adjust`, and Sales keeps review and
  confirm. Still the founder's call: creating or authorising an invoice and the Xero sync reach the
  same whole-org `reconcile_org`, so `sales.record` can still cause `/run`'s stock effect that way.
- **O2 — Low: `biz_e_source_output_id` on product mappings is not checked against the
  org's outputs.** (Codex F2) Rows are written under the caller's org and every downstream
  inventory query is org-filtered, so nothing crosses tenants. A foreign or unknown id only
  makes that org's own mapping go stale. The fix needs the canonical "output" lookup agreed
  first: mappings may name products not yet in stock, so the final-products list is not it.
- **O3 — Low hardening: some queries rely only on the global tenant filter.** (Codex F3)
  Line-item replace/read, sync-job updates by id, the task's contact lookup in
  `_serialise_task`, and `Session.get()` in sales traceability. Safe on every audited HTTP
  path (tenant context active, ids from scoped parents). Worth an explicit `org_id`
  predicate when that code is next touched. No behaviour change to test.
- **O4 — Needs a product decision: edits to a Biz-E contact with Xero sync turned off are
  overwritten by the next pull once it has been in Xero.** Turning sync off stops Biz-E
  sending edits, but the pull still writes Xero's copy over the contact, because its push
  status stays `synced`. Should "sync off" also stop the pull from changing that contact's
  details, or should the toggle not be offered once a contact is in Xero?
- **O5 — accepted-risk (carried from 2026-08-15): one Xero token encryption key for every
  tenant.** It now comes from a dedicated `xero_token_secret` (2c004a25), still not
  per-tenant. Unchanged decision.
- **O6 — Low, needs a product decision: Batch matching's per-line fix links go to pages a
  Sales user cannot open** ("Map product" → `/crm/configuration`, missing stock →
  `/core/inventory/add`, which needs `inventory.adjust`). What should a Sales user be told
  to do instead: ask an admin, or nothing?

Suppressed (prior verdict): none. `finding_history.py decide` returned `new` for all 13.

## Coverage
`pytest --cov=app/features/crm` over the CRM unit suites: **77%** (3801 statements, 892
missed). The 2026-08-15 figure was 55% combined unit+e2e. The largest remaining gaps are
`routes/oauth_routes.py` (32%) and `services/xero_oauth_service.py` (41%), the live OAuth
exchange paths. Not closed here; they need a stubbed Xero OAuth server.

## Tests added
- Python: 20 (16 bug tests, 4 controls) in `tests/test_xero_api_client.py`,
  `tests/test_crm.py`, `tests/test_crm_contact_sync.py`.
- JS: 4 (2 bug tests, 2 controls) in `tests/js/crm-customer-detail.test.js` and `tests/js/crm-configuration.test.js`.

## Full-suite regression check
- Full non-e2e suite (`env -u ENVIRONMENT uv run pytest tests/ --ignore=tests/e2e -n 4`):
  **3245 passed, 31 skipped, 0 failed**.
- CRM browser tests (in-process app, Playwright): `tests/e2e/test_crm_contact_sync_ui.py`,
  `test_crm_flow.py`, `test_sales_design.py`: **38 passed**.
- `node --test tests/js/*.test.js`: all green. `ruff check app/ tests/` and
  `ruff format --check` on the changed files: clean.

## Test-evaluator rounds
Round 1 (Codex) graded 24 tests: 21 valid, 3 invalid. All three were fair calls and are fixed:
- the partial-sync test synced nothing, so it went down the 502 path and never checked the
  status. It now syncs one contact and asserts 200, `ok: false`, `contacts_synced == 1` and
  the error text;
- the assignee control assigned the caller to themselves. It now uses a second user in the
  same org;
- the configuration-link test now asserts each page rendered (200 plus a page marker)
  before asserting the link is absent.
Round 1's prompt also overstated the red-on-main evidence: one of the three
`TestCustomersPageXeroButtons` tests is a control and passes on main. Corrected in round 2.
After the changes, the bug tests in those classes were re-run against main's app files: 7
red, 3 controls green.
Round 2 (Codex) re-graded the three: **valid**, no findings. It confirmed the other 21 were unchanged.

## Follow-up review, 2026-10-19 (of MR !539)

!539 was a sound review: nine real bugs, each fixed red-first, a route-by-route auth and
org-scoping matrix confirmed by an independent tenant audit, and tests graded valid. This
follow-up looked where it was thin: `xero_sync_service.py` (the pull), the FIFO matching in
`sales_traceability_service.py`, and the OAuth refresh path (32-41% covered). It also
re-scanned every CRM template for bindings into empty initial state (!538 and F8 were the
same bug twice). No other template has one.

Fixed (tests in `tests/test_xero_sync_service.py`, each failing on `main`):

- **S1: incremental syncs lost Xero edits made while a sync ran.** The resume point was the
  sync's finish time, so a record edited in Xero after it was fetched, but before the sync
  finished, was never pulled by a later incremental sync. Only a full sync recovered it, and
  day-to-day syncs (manual, and after each invoice create or authorise) are incremental. The
  resume point is now the sync's start, less a 5-minute margin for clock skew. Re-pulling is
  idempotent.
- **S2: a partial sync skipped the records that failed.** It still moved the resume point
  past them. It now leaves the resume point alone, so failed records are retried.
- **S3: one record the database rejected sank the whole sync.** A NUL byte in a contact's
  text, for example. With no savepoint, the session was poisoned: every later contact
  failed, and so did the entire invoice sync. Each contact, and each invoice with its line
  items, now saves in its own savepoint.

Checked and sound: FIFO allocation is reversible and all-or-nothing. `assign_line` consumes
before checking the batch's product, but the route rolls back on that error. Voids and
pre-go-live sales are reversed.

Left open:

- **S4 (Low): token-refresh race.** Two requests refreshing at once are handled when the
  winner has already saved its rotated token. If the loser is rejected first, it marks the
  connection invalid even though the winner succeeds. Fix with a row lock (`SELECT … FOR
  UPDATE`) on the token during refresh. Rare: it needs two Xero calls within the same
  refresh window.
- **S5 (Product decision): credit notes (`ACCRECCREDIT`) aren't matched**, so returned
  goods never go back into stock.
