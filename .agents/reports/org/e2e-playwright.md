# E2E / gap-fill report — org (`app/api/routes/org_routes.py`)

## Verdict

**Patched.** AC8 (cross-tenant isolation) had zero coverage before this pass; it now has
5 dedicated tests. Five other acceptance criteria (AC2–AC6) had partial coverage —
happy-path only, missing their negative/edge branch — and are now fully closed. Test
count: **11 → 23**, all passing.

## Note on test style (not live-browser Playwright)

`app_server` was down for this review (per preflight), and `tests/test_org_routes.py`
does not drive a browser — it authenticates through the real `/auth/login` route on an
in-process Flask app (`create_app()` + `flask_app.test_client()`) and then exercises
`/org/*` directly, same pattern as `tests/test_multi_tenant_isolation.py`. That is the
established pattern for this file, so all additions here follow it rather than
introducing a parallel `tests/e2e/` Playwright suite for a blueprint that has no browser
UI of its own (`/org` is a JSON/HTML admin surface with no dedicated frontend in this
codebase yet). This is consistent with the skill's gap-fill guidance to match the
existing pattern rather than force a mismatched tool.

## What existed before

`tests/test_org_routes.py` — 11 tests, covering:
- AC1 (GET /org happy path + unauthenticated redirect)
- AC2 (PATCH /org name update, response + persisted read-back only)
- AC3 (no invalid-status test)
- AC4 (list users — only checked roles present, not inactive users)
- AC5 (create user happy path, forbidden-for-member, duplicate-email 400 — no invalid-role
  test, no password-hashing proof)
- AC6 (delete as admin, self-delete rejected, unknown-user 404 — no invalid-UUID test)
- AC7 (PATCH and POST forbidden-for-member — DELETE forbidden-for-member was missing)
- AC8 — **no coverage at all**

## What was added (12 new tests, 11 → 23)

A concurrent session (security-audit, working the same shared worktree/spec) landed
`test_delete_user_forbidden_for_member` (closing the AC7 DELETE gap) and a `two_org_world`
fixture with 3 of the AC8 tests before I finished my pass; I added the remaining AC8
tests plus all AC2–AC6 gap closures on top of that shared state. Final set, by AC:

**AC8 — cross-tenant isolation (5 tests, using the new `two_org_world` fixture: two orgs,
one ADMIN each, real login):**
- `test_list_users_excludes_other_org` — org A's `/org/users` never returns org B's admin
- `test_delete_user_in_other_org_is_404_not_deleted` — org A `DELETE /org/users/<org-B-id>`
  → 404, and org B's user is confirmed still active afterward (proves scoping, not a
  vacuous deny)
- `test_created_user_not_visible_to_other_org` — a user org A creates via `POST /org/users`
  never appears in org B's listing
- `test_get_org_is_scoped_to_caller` — `GET /org` returns each caller's own org id, never
  the other's
- `test_patch_org_does_not_affect_other_org` — org A's `PATCH /org` rename doesn't touch
  org B's row (verified via org B's own `GET /org` before/after)

`GET /org` and `PATCH /org` take no org-id parameter — they resolve entirely through
`g.current_org_id` from the session (`app/api/middleware/tenant_context.py`), so there is
no injectable cross-org path for those two routes the way there is for
`DELETE /org/users/<user_id>`. The two tests above prove the isolation holds by construction
rather than via an attackable parameter, which is the correct shape of proof for those routes.

**AC3 — invalid status is rejected before any write (1 test):**
- `test_patch_org_rejects_invalid_status` — `PATCH /org {"status": "not_a_real_status"}` →
  400, and a follow-up `GET /org` confirms the org's status is untouched.

**AC2 — diff-scoped audit event (1 test):**
- `test_patch_org_emits_diff_scoped_audit_event` — patches only `name`, then queries the
  `entity_events` table directly (`EntityEvent.event_type == "org.settings_updated"`) and
  asserts `diff["name"]["after"]` is set while `"status"` is absent from `diff` — proving
  the event body is a genuine diff of what changed, not a fixed snapshot.

**AC5 — invalid role rejected, password hashed before storage (2 tests):**
- `test_create_user_rejects_invalid_role` — `role: "superuser"` → 400
- `test_create_user_hashes_password_before_storage` — reads the persisted `User` row
  directly, asserts `password_hash != PASSWORD`, and confirms
  `AuthService.verify_password(PASSWORD, stored.password_hash)` succeeds (proves it's a
  real, verifiable bcrypt hash, not just "different from plaintext").

**AC6 — malformed user_id (1 test):**
- `test_delete_user_invalid_uuid_is_400` — `DELETE /org/users/not-a-uuid` → 400 (previously
  only the valid-UUID-but-unknown-user 404 path was tested).

**AC4 — inactive users included in listing (1 test):**
- `test_list_users_includes_inactive_users` — soft-deletes a user, then confirms
  `GET /org/users` still returns it with `is_active: false` (previously only "roles
  present" was checked, never that a deactivated user stays in the list).

## Verification

Ran `unset ENVIRONMENT && uv run pytest tests/test_org_routes.py -v` against the test DB
at `localhost:8401`. Result confirmed independently (by the coordinating session, after a
transient collision caused by two concurrent pytest processes hitting the same
`OrganisationFactory` sequence counter mid-run — resolved once runs stopped overlapping):
**23 passed**, 0 failed.

## AC coverage still open

None of the 8 ACs are uncovered. One caveat worth flagging as a finding rather than a gap:
`OrgManager.switch_org` (noted in the spec's "Out of scope" section as possibly dead code)
is not exercised anywhere — that's explicitly out of scope for this blueprint's routes and
was already flagged by the spec, not something this pass should pull in.

VERDICT: patched
