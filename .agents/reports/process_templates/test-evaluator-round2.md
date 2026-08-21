# test-evaluator — process_templates (round 2)

engine: codex (gpt-5.6-sol, effort high), `--sandbox read-only` via direct CLI
invoked_as: chain stage (called by new-feature) — read-only grader, no remediation performed
verdict: valid

Report captured and written by the orchestrator on the grader's behalf per
`.agents/verification-chain.md` §5 (the grader's own write was correctly rejected by
the read-only sandbox). Same environment limitation as round 1: the sandbox can't
resolve the configured test-DB host, so 26/29 unit tests couldn't execute inside it (3
DB-free tests ran and passed); grading is source-level verification of each round-1 fix
against the real code it claims to match, cross-checked against this session's own
confirmed 37/37 (29 unit + 8 e2e) green run.

## Verification of each round-1 fix

1. **AC7 method match** — confirmed `GET /api/core/processes/<id>`
   (`backend.py:1493`, `get_process` handler) calls `repo.get_process_with_steps`, the
   same method the fixed test now calls directly for the cross-org assertion, and the
   in-org assertion goes through that exact route via `compliant_app_client`. Matches.

2. **AC7 immutability PUT-result check** — confirmed the test now asserts
   `put_resp.status_code == 200` and the returned `name` before checking the catalogue
   is untouched, closing the "vacuous pass on a failed edit" gap.

3. **AC4 route-layer coverage** — confirmed the test now calls
   `compliant_app_client.get("/api/core/process-templates")` and
   `.../<synthetic_template_id>` after registering the synthetic family/template,
   asserting both against the live route. Fixture ordering traced end to end: the
   client fixture logs in against the org's *initial* Compliant profile, the test body
   then commits the synthetic-module profile update, and each subsequent HTTP request
   re-queries the current profile through `ComplianceService` per-request (not cached
   at login) — the `finally` block restores both registry state and the org's
   `nz_alcohol` profile so nothing leaks into other tests. Sound.

4. **E2E family-filter positive control** — confirmed `expect(page.get_by_role(
   "button", name=re.compile("Grape intake"))).to_be_visible()` was added alongside
   the existing negative assertion.

5. **Advisory literal strings** — confirmed both the unit and e2e literals match
   `TEMPLATE_CUSTOMISE_ADVISORY`'s current text in
   `app/features/process_templates/catalog/registry.py` verbatim (checked via direct
   source read, not just diff review) — no copy-paste drift.

6. **AC11 `== 1`** — confirmed both analytics-event tests now assert exact count.

7. **AC13 negative control** — confirmed `_assert_flow_process_access`
   (`backend.py:278-291`) 404s on an org-scoped lookup miss, and the test now checks a
   random UUID against the same route 404s alongside the real copied id's 200.

## Fresh pass for new issues

None found. Specifically checked whether the AC4 fix's added `compliant_app_client`
fixture parameter could introduce ordering/state bugs (given `compliant_app_client`
itself depends on `compliant_org`, already a parameter of this test) — fixture caching
means both resolve to the same org instance; no duplication or drift.

## Findings

None.

VERDICT: valid
