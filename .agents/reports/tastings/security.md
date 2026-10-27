# SECURITY: tastings

date: 2026-10-27
verdict: clean
scope: new Tastings code, changed access/task/excise integration, and their dependencies
execution: inherited-model read-only subagent fallback; combined scanner and manual tenant/auth/accounting stage
manual_checklist: 7/7 completed

The separate security-tenant-audit skill is unavailable. Its intended tenant/auth scrutiny was performed explicitly in this stage, without pretending that a second engine or separate specialist skill ran. No app/test/script/schema changes were made. Only the isolated `workflow-engine-test_tastings_build` database was used.

## Scanner evidence and triage

- Fresh `uv run semgrep scan --config p/python --config p/flask --config p/owasp-top-ten --config .semgrep/ --json app/features/tastings app/features/crm/frontend/js/tastings.js tests/test_tastings.py`: **0 findings**, with one Jinja partial-parsing warning covering template extension/block tags. The template was manually read; the warning is a scanner coverage limitation, not a clean full-template parse claim. User values are rendered with Jinja autoescaping or JS `textContent`/created nodes, with no dynamic HTML insertion.
- Earlier supplied scoped security scan had two `sqlalchemy-query-in-for-loop` findings in planning validation. Root replaced those source lookups with bounded batched same-org item/pool queries. Fresh scan no longer reports either.
- Supplied repository-wide `semgrep-auto.json`: **227 findings and 90 parser warnings/errors**. Three results intersect the feature's changed/new file set: pre-existing local screenshot CLI dynamic-import and dynamic-urllib sites, and the dedicated test's `TESTING=True` setup. Read the actual paths: the CLI import intentionally executes the locally supplied screenshot scenario module; its urllib code calls the locally configured screenshot/server workflow, not an app route accepting tenant URLs. The test flag configures only a newly created test application. None is a new shipping vulnerability from Tastings; no production config suppression or accepted-risk grant was introduced. The other repository results were outside this feature audit, not individually cleared. No dependency/lockfile change is present.
- Frozen dependency audit: `uv audit --frozen --output-format json --preview-features audit-command,json-output` audited **94 packages**, reporting **0 vulnerabilities and 0 adverse statuses**.
- The supplied original gitleaks log scanned **0 commits / 0 bytes** and was not counted as a meaningful scan. Fresh redacted worktree scans covered the feature directory (~153KB), tracked diff via stdin (~25KB), dedicated backend tests (~26KB), new JS (~33KB), CSS (~14KB), E2E (~9KB), and migration (~9KB): **no leaks found**. These are current worktree checks, not a fresh full-history certification. No credential values were printed or copied into this report.

## Manual boundary checks

1. **Auth/roles/subscription:** all ten routes carry `requires_auth`; global policy assigns read to `sales.view`, writes to `sales.record`, and dispatch additionally checks `inventory.adjust`. The blueprint subscription gate denies unavailable orgs and unauthenticated requests without records. The blueprint is mounted only within enabled/successfully loaded CRM. Selected-site staff endpoints are explicitly blocked in the registry. Expired authenticated access remains subject to the existing global access policy.
2. **Tenant isolation:** event/allocation/pool repositories require org ID explicitly. Item, pool, user, contact, site/location, profile/rate, ownership-provenance and prior-removal queries were inspected for same-org predicates. Event-task/source/pool edges have composite same-org FKs. Mutations first retrieve the event by authenticated org plus UUID, not bare ID. Generic CRM edit/delete/lane paths cannot bypass the tasting lifecycle through the linked task.
3. **Mass assignment:** planning, allocation, dispatch and finalisation accept explicit allowed fields; status, actors, task ID, snapshot/removal identity and balances are server-owned. No direct JSON-to-model mass assignment found.
4. **Injection/output:** escaped literal SQL LIKE searches and SQLAlchemy expressions; migration SQL is static. No user-controlled subprocess/filesystem SQL, unsafe template output or JS HTML insertion in the feature.
5. **SSRF/uploads:** no feature upload, external URL fetch, webhook, email or third-party API surface exists. Venue licence reference is text and does not invoke remote lookup.
6. **Secrets/config:** feature introduces no secrets, cookie changes, debug enablement or authentication config. Dedicated `TESTING=True` belongs to tests, not application startup. Existing production session/config implementation was read in context, not re-certified for the whole app.
7. **CSRF/CORS:** Tastings has no exemption. JS sends the shared CSRF token on mutations; the API test enables CSRF and proves a missing-token mutation fails400. No wildcard credentialed CORS configuration is introduced.

## Stock and excise accounting checks

- Planning does not debit stock; dispatch requires nonempty allocations, positive bounded decimal quantities, whole counted packs and same-org eligible producer ownership. Library/raw/customer/receipt stock is rejected. Source authority and dated CCA coverage are rechecked at dispatch.
- Event and stable-order stock/pool row locks protect replay, overselling and reservation conservation. Dispatch key uniqueness and canonical hashes reject changed replays. Finalisation requires exactly every allocation and bounds used mL by reserved mL. Cancellation releases reservations rather than crediting warehouse/bonded stock.
- One immutable pool-lot removal supplies legacy and source-CCA observations; pool reuse does not add a warehouse debit/removal. Frozen classification/rate/ABV evidence cannot silently reprice after profile edits. Missing facts remain problems and prevent false complete/nil returns. Modern CCA observations continue to disclaim complete lodgement.
- Full dedicated suite independently passed **29/29**, covering concurrency, all-lines rollback, replay, signed stock movements, same-org references, CSRF/roles, frozen basis/late adjustments, Library separation and the three build-review regressions.

## Additional live HTTP boundary probes

Using two newly created isolated scratch orgs and real login/test-client requests: foreign event GET, PUT, dispatch, finalise and cancel all returned404; foreign events/pool/stock were absent from list endpoints; foreign warehouse and pool references were rejected400; forged status mass assignment was rejected400. All created probe orgs were purged in `finally`.

The probe initially asserted that an anonymous JSON read must return401, and failed because the subscription `before_request` gate deliberately returns404 before the route decorator. Inspection confirmed no record disclosure; the request is denied. This is recorded as an incorrect probe expectation, not silently reported as a passing401 check. The hostile-tenant assertions preceding it passed. Persistent tests were not added by this read-only grader; test-author/evaluator remain later gates.

## Findings / limits

No new feature-scoped security finding remained open. No learned rule was added because this manual pass found no new vulnerability class; the two earlier planning-loop scanner findings were already covered by an existing rule and corrected by root. This does not assert full repository security or full-history secret cleanliness. Final browser history/UI changes and exact-head CI remain the root's later verification stages.

VERDICT: clean
