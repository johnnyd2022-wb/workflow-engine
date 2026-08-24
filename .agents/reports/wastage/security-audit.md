# SECURITY: wastage
date: 2026-08-11
verdict: findings-open
scanned: semgrep(0 findings), gitleaks(0), uv-audit(0 vulnerabilities)
manual_checklist: 7/7 completed
invoked_as: chain stage (read-only) — findings reported here, not patched. review-feature patches in its Step 4.

## Scan pass
- `semgrep --config p/python --config p/flask --config p/owasp-top-ten --config .semgrep/` over the 6 wastage files (backend.py wastage section scoped by target list, inventory_wastage_quantity.py, inventory_wastage.py model, wastage_repo.py, dispose.html, dispose_confirm.html): 177 rules run, **0 findings**.
- `gitleaks detect` (repo-wide, 997 commits): **0 leaks**.
- `uv audit --frozen`: **0 vulnerabilities**.

## Manual checklist (7/7)
1. **Auth on every route** — all 4 routes (`record_wastage`, `list_wastage`,
   `inventory_dispose`, `inventory_dispose_confirm`) carry `@requires_auth`. No bare
   route. Consistent with the rest of `backend.py` (0 uses of `@requires_org_scope`
   anywhere in the file — not wastage-specific, org scoping is via `g.org_id` set by
   tenant-context middleware).
2. **Tenant isolation** — every wastage query is org-filtered:
   `InventoryRepository.get_inventory_item_by_id_for_update` filters
   `(InventoryItem.id == item_id, InventoryItem.org_id == org_id)` under `FOR UPDATE`
   (`inventory_repo.py:368-375`); `WastageRepository.list_wastage_records` filters
   `InventoryWastage.org_id == org_id`; `list_wastage`'s item-name resolution filters
   `InventoryItem.id.in_(item_ids), InventoryItem.org_id == org_id`; `dispose_confirm`
   filters the same way (`backend.py:759-761`). All four confirmed correct by reading
   the code. **F1 below is the coverage gap this correctness has no test for.**
3. **Mass assignment** — `InventoryWastage(...)` and `InventoryMovement(...)` are built
   with explicit named kwargs from parsed/validated fields, never `Model(**request.json)`.
   Clean.
4. **Injection** — no raw SQL string interpolation; the one raw SQL call
   (`_pg_advisory_lock_wastage_idempotency`) uses `text("SELECT pg_advisory_xact_lock(:k1, :k2)")`
   with bound params. No `shell=True`. Jinja2 templates use plain `{{ }}` (auto-escaped),
   no `| safe`/`Markup()`. The JS-rendered rows in `dispose.html` (`renderCards`, line
   91-118) build DOM via `innerHTML` but run every interpolated value (`nameLine`,
   quantity, unit) through a textContent-roundtrip `esc()` helper (line 74-79) — verified
   applied consistently, no raw interpolation of item name/unit into the HTML string.
5. **SSRF/uploads** — not applicable, no URLs or file uploads in this slice.
6. **Secrets/config** — none in scope.
7. **CSRF/CORS** — `record_wastage` (POST) carries no CSRF exemption; inherits the
   app-wide Flask-WTF protection like every other state-changing route. Clean.

## Findings

- F1 [fix — coverage gap, not a live vulnerability] `app/core/backend/backend.py:709-793`
  (`inventory_dispose`, `inventory_dispose_confirm`)
  The two disposal HTML pages have **no dedicated test file** (feature-index GAP,
  confirmed: `grep` for `dispose` across `tests/*.py` returns nothing) and **no
  cross-tenant probe** — `tests/e2e/test_tenant_isolation.py` covers the JSON API
  (`test_org_b_wastage_list_excludes_org_a_records` and the wastage-on-foreign-id 400
  case) but not these two GET routes. Code is correct by inspection (checklist item 2),
  so this is not a live leak — but AC-D2/AC-D3 in the reconstructed spec
  (`.agents/specs/wastage.md`) are unverified claims until a test exists proving org A
  gets the safe "item"/blank fallback for org B's `inventory_item_id`, not org B's real
  name/unit/quantity.
  repro/evidence: `grep -rln "inventory_dispose" tests/*.py` → no matches.
  patch: none applied here (read-only chain stage) — routed to review-feature's
  e2e-playwright gap-fill stage (Step 3.2) and unit-coverage stage (Step 3.3).
  rule_added: none — this is a coverage gap, not a mechanically-detectable code pattern.
  history: recorded `confirmed`, sig `6af62c9cbb24` (`finding_history.py`).
  Already fixed: `tests/e2e/test_inventory_dispose_pages.py` (commit `25e6ec7`) now
  exists with dedicated coverage for both routes, including
  `test_org_b_cannot_preview_dispose_org_a_item` — the exact cross-tenant regression
  test this finding asked for (verified 2026-08-25 by findings-sweep).

## Attempted but clean
- Advisory-lock key scoping (`org_id:idem_key` hash, `backend.py:3056`) — confirmed the
  org_id is part of the hashed key, so a cross-org idempotency-key collision cannot
  serialize (or block) against another org's request.
- Advisory-lock true concurrency (AC18) — re-litigated the inventory review's disclosed
  gap here since the same lock mechanism was flagged there as untested; found
  `tests/test_wastage.py::test_wastage_advisory_lock_serializes_concurrent_duplicate_submissions`
  already forces genuine Postgres-level lock contention (documented in its own docstring
  as a deliberate fix for an earlier, non-contending version of the same test). **Not a
  gap** — already closed at the wastage-slice level, ahead of the inventory review's
  disclosed-gaps note.
- Non-finite/NaN quantity handling on `dispose_confirm` — the exact bug class the
  inventory review's F2 fixed (commit `e748618`) is present and still catching
  `InvalidOperation` (`backend.py:742-746`); did not regress.
- `WastageRepository.create_wastage_record` — has no production caller (only
  `tests/factories.py` uses it to seed fixtures). Not a route, not reachable by an
  attacker; noted in the spec's Out of scope, not a finding.

## not_verified
- Live Postgres advisory-lock behavior under this session's specific DB instance was not
  re-run manually beyond the existing automated test (which does exercise it against the
  real test-DB Postgres, per its docstring) — treated as sufficient rather than
  duplicating it live.

VERDICT: findings-open
