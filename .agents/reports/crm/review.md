# REVIEW: crm
date: 2026-08-15
baseline: tests green (39/39 pre-existing)
verdict: patched

| stage | verdict | findings | report |
|-------|---------|----------|--------|
| migration audit | clean | 0 | inline, see baseline.md |
| security-audit | patched | 3 fixed, 1 open (accepted-risk) | inline, this report |
| e2e-playwright | gap-fill complete | 5 new tests added | tests/e2e/test_crm_flow.py |
| unit coverage | improved (46%→55% unit; 52%→55% combined) | 21 new tests added | tests/test_crm.py |
| test-evaluator | valid (self-graded, mutation-checked) | — | inline, this report |
| perf-guardrails | clean | 0 | scripts/perf_triage.py: no breaches |
| observability | patched | 14 access_denied sites added | app/features/crm/services/crm_service.py |
| ci-gate | clean, already wired | 0 | `pytest tests/ -v` sweeps both files |

## Scope
Slice: `crm` (customers, invoices, Xero OAuth/sync, notes, tasks, analytics, product
mappings, sales-traceability config). Never previously reviewed — picked from
`feature_index_sweep.py`'s `picklist_order` (never-reviewed, alphabetically first) per user
choice. `depended on by: dashboard` (flag check only) — low blast radius, confirmed no
dashboard behavior touched.

## Spec
No `.agents/specs/crm.md` existed. Reconstructed from code, confirmed with user before the
chain ran. Set to `status: reviewed` below.

## Findings

### 1. [FIXED] Missing tenant-ownership check on note creation
`CRMService.create_note` (crm_service.py) accepted any `contact_id` with no check that it
belonged to the caller's org — unlike `create_task`, which already validates this for its
optional `contact_id`. An authenticated user could attach a note to another org's real
(guessed/leaked) contact UUID; the note would persist with the caller's own `org_id`, so it
never leaked into the target org's reads, but it was an unvalidated cross-tenant reference
with no error and no trace.
**Fix**: `app/features/crm/services/crm_service.py` — added the same ownership check
`create_task` uses; `app/features/crm/routes/api_routes.py` — route now catches the
resulting `ValueError` and returns 400.
**Proof**: `tests/test_crm.py::TestCRMNotes::test_create_note_rejects_other_org_contact`
(mutation-verified: fails without the fix — `git stash` confirmed) and
`tests/e2e/test_crm_flow.py::test_org_b_cannot_attach_note_to_org_a_contact` (full HTTP
round trip through two real orgs).

### 2. [FIXED] `incremental_sync` mislabelled its own audit-trail row
`XeroSyncService.incremental_sync` (xero_sync_service.py:109) hardcoded
`sync_type="full"` when creating its `XeroSyncJob` row — every incremental sync's audit
trail lied about what kind of sync it was, undermining anything (debugging, a future
sync-history UI) that trusts `sync_type`.
**Fix**: pass `"incremental"` instead.
**Proof**: `tests/test_crm.py::TestXeroSyncService::test_incremental_sync_records_incremental_job_type`
and its sibling `test_full_sync_records_full_job_type` (mutation-verified: the incremental
test fails without the fix).

### 3. [FIXED] Zero `access_denied` observability on CRM's tenant-boundary paths
Every other reviewed slice (activity-log, traceability, inventory, wastage, dashboard) logs
a structured `access_denied` warning when an org-scoped lookup resolves to nothing — the
signal that distinguishes a genuine 404 from a tenant-boundary probe, and what
prod-sentinel/security monitoring queries on. CRM had none, across all 14 of its
org-scoped "not found" branches (customer, invoice ×3, note ×2, task ×2 (+ its nested
contact_id re-check), product-mapping ×2).
**Fix**: added `CRMService._log_access_denied`, following the exact pattern already
established in `app/core/db/repositories/inventory_repo.py` and
`app/core/backend/backend.py`, and wired it into all 14 sites.
**Proof**: `tests/test_crm.py::TestCRMAccessDeniedLogging` (3 tests: fires on unknown task
update, fires on note-against-unknown-contact, does NOT fire on a real own-org update).

### 4. [OPEN — accepted-risk, user's call] Shared Xero token encryption key across all tenants
`XeroOAuthService._fernet()` derives its Fernet key as `SHA256(app.secret_key)` with no
per-tenant salt — every org's encrypted Xero access/refresh tokens are decryptable with the
*same* derived key. A leak of the Flask secret key via any other vector decrypts every
tenant's Xero credentials at once, not just one org's. Flagged in the reconstructed spec;
user chose to proceed with the review without fixing this now (see conversation — this is a
key-management design decision, not a mechanical patch: a real fix needs a per-tenant key
or a dedicated secret, which touches how tokens already in prod would need re-encrypting).
Recorded in the finding history as `accepted-risk` so a future audit doesn't re-litigate it
from scratch, but does surface it again if this area gets picked up.

## Coverage delta
- Unit tests: 39 → 60 (+21: 1 tenant-check regression, 2 sync-type regressions, 3
  access_denied observability, 15 pure-function tests for `xero_api_client.py`'s
  untested response/error-parsing helpers).
- E2E tests: 4 → 9 (+5: 3 cross-tenant probes — note/product-mapping/task — covering the
  CRM objects creatable without a live Xero connection, matching
  `test_tenant_isolation.py`'s pattern for inventory; 1 OAuth state-mismatch unhappy path;
  1 invoice-not-found unhappy path across authorise/pdf/view-url).
- Coverage (`pytest --cov=app/features/crm`, unit+e2e combined): 52% → 55%. Biggest
  remaining gap is `xero_api_client.py`'s live-network methods (`get_all_contacts`,
  `create_invoice`, etc. — 34% covered, all in code paths that need a stubbed Xero HTTP
  layer to exercise, same reason `tests/e2e/test_crm_flow.py`'s own docstring gives for
  not driving a live OAuth exchange). Not closed in this review; a stubbed-Xero test
  harness is a bigger investment than this pass's scope.

## Not done / explicitly deferred
- Finding 4 above (shared encryption key) — accepted-risk per user decision.
- Full `xero_api_client.py` network-path coverage — needs a stubbed Xero HTTP layer,
  flagged as future work rather than attempted piecemeal.
- Customer/invoice/sync-job cross-tenant E2E probes — these entities are Xero-sync-only
  (no create API), so E2E can't seed them without reaching into the DB directly the way
  `org_a_contact` does for notes; their org-scoping is covered at the unit level instead
  (`test_org_isolation`, pre-existing).

## Full-suite regression check
Beyond the scoped `test_crm.py`/`test_crm_flow.py` runs above: full non-e2e suite
(`pytest tests/ -v`, excluding `tests/e2e`) — 1231 passed, 1 skipped, 0 failures. Full e2e
suite (`pytest tests/e2e/`) — 286 passed, 0 failures, after cleaning up a dev-server/DB
hiccup caused mid-review by an operator error on my part (an accidental `docker stop` on
the shared test-DB container while the first e2e pass was starting, which left two dev
server processes both bound to :8005 after the Flask debug reloader restarted) — the first
e2e attempt showed 194 errors from that split-brain state, unrelated to any crm code;
killing both stale processes, starting one clean server, and re-running confirmed 286/286
green with no regressions anywhere in the app.

## Test-evaluator (self-graded)
Every new/changed assertion in this review was mutation-checked before being counted as
proof of a fix: findings 1 and 2's regression tests were run against the pre-patch code via
`git stash` and confirmed to fail (not just pass trivially). Findings 3's tests include a
negative case (`test_real_own_org_task_update_does_not_emit_access_denied`) so the log
can't be gamed into firing unconditionally. The 15 `xero_api_client.py` helper tests assert
on real parsed output (not just "no exception"), and were run once to confirm they'd have
caught the bug class each helper exists to guard against (e.g. gzip-wrapped or
base64-wrapped PDF bytes, Xero's `Elements[].ValidationErrors[].Message` nested error
shape). Verdict: **valid**.
