# SECURITY: org
date: 2026-07-26
verdict: patched
scanned: semgrep(0 findings), gitleaks(17 repo-wide, 0 in scoped files), uv-audit(0)
manual_checklist: 7/7 completed

## Scope

`app/api/routes/org_routes.py` (`org_bp`, `/org/*`) and `app/core/security/org_manager.py`,
per `.agents/specs/org.md`. Focus per task: AC7 (admin-only role checks on `PATCH /org`,
`POST /org/users`, `DELETE /org/users/<id>`) and AC8 (tenant isolation across all five
routes in the blueprint).

## Findings

- F1 [fix] `app/api/routes/org_routes.py:115-118,156-158,264-267` — three exception
  handlers (`update_org`, `list_users`, `delete_user`) returned
  `jsonify({"error": f"Failed to X: {str(e)}"}), 500`, putting the raw exception string in
  the API response body. This leaks internals to any authenticated caller who can trigger
  a 500 (DB driver text, occasionally column/constraint names, internal state) — an
  information-disclosure issue (OWASP A05/A09-adjacent). `create_user`'s handler already
  followed the safe pattern (`logger.exception(...)` + generic message), which is what the
  other three now match.
  repro/evidence: pre-patch, `jsonify({"error": f"Failed to update organisation: {str(e)}"}), 500`
  patch: all three handlers now do `logger.exception("Error <verb-ing> <noun>")` then
  return a fixed, generic `{"error": "Failed to ... organisation/list users/delete user"}`
  message — no exception detail crosses the trust boundary. Verified via
  `git diff app/api/routes/org_routes.py` (3 hunks) and a clean `uv run pytest
  tests/test_org_routes.py -q` (23 passed).
  rule_added: `.semgrep/rules/learned.yml#bize-verbose-error-to-client` (fixture pair at
  `.semgrep/fixtures/bize-verbose-error-to-client/{vulnerable,fixed}.py`, proven via
  `python scripts/rule_candidates.py verify`)

- F2 [fix] `tests/test_org_routes.py` — the 11 pre-existing tests (confirmed via baseline
  run, `.agents/reports/org/baseline.md`) covered role checks (AC7 — member gets 403 on all
  three admin routes) but **had zero coverage of AC8 cross-tenant isolation**: no test ever
  created a second organisation and proved org A's session couldn't see/create/delete/
  affect org B's users or settings. Code-level review (tenant_context middleware
  `app/api/middleware/tenant_context.py::load_tenant_context` derives `g.current_org_id`
  solely from `session["user_id"]` → a fresh DB lookup of `user.org_id`; no route in
  `org_routes.py` reads an org_id from the client) indicated the isolation was already
  structurally sound, but "the code looks right" is not the same guarantee as a red-team
  test, per this skill's own rule.
  repro/evidence: `git diff --stat tests/test_org_routes.py` before vs. after; baseline
  showed `11 passed, 0 skipped, 0 failed` with no org-B fixture anywhere in the file.
  patch: added a `two_org_world` fixture (two orgs, one ADMIN client each) and 5 tests:
  `test_list_users_excludes_other_org`, `test_delete_user_in_other_org_is_404_not_deleted`
  (asserts 404, not 403 — confirms non-existence rather than access-denied, and that org
  B's user is untouched), `test_created_user_not_visible_to_other_org`,
  `test_get_org_is_scoped_to_caller`, `test_patch_org_does_not_affect_other_org`. All pass
  against the current code with no further route changes needed — AC8 holds.
  rule_added: none. Tenant isolation here is enforced by a single, already-audited
  middleware chokepoint (`tenant_context.py`), not a per-route pattern a semgrep rule could
  usefully generalise; the regression protection is the test suite itself.

- F3 [fix, incidental] Test file also gained coverage the audit surfaced as missing while
  verifying AC2/AC3/AC5/AC6/AC4 during this pass: `test_patch_org_rejects_invalid_status`,
  `test_patch_org_emits_diff_scoped_audit_event`, `test_create_user_rejects_invalid_role`,
  `test_create_user_hashes_password_before_storage`, `test_delete_user_invalid_uuid_is_400`,
  `test_list_users_includes_inactive_users`, `test_delete_user_forbidden_for_member`. None
  of these were security holes — the route code already implemented every one of these
  acceptance criteria correctly — but they were unverified by any test, which is the same
  "looks right but unproven" gap as F2. Bucketed as fix (coverage), not a vulnerability.

## Attempted but clean

- **Auth on every route**: all 5 routes (`GET /org`, `PATCH /org`, `GET /org/users`,
  `POST /org/users`, `DELETE /org/users/<id>`) carry `@requires_auth` +
  `@requires_org_scope`; the three mutating routes additionally carry
  `@requires_role(UserRole.ADMIN)`. Decorator order (`requires_auth` → `requires_role` →
  `requires_org_scope`) checks auth, then role, then org context — no bypass ordering
  issue.
- **Tenant isolation (structural)**: confirmed via a dedicated read-only sub-investigation
  of `app/api/middleware/tenant_context.py` — `g.current_org_id`/`g.current_org` are
  derived exclusively from `session["user_id"]` (Flask's signed server-side cookie) via a
  fresh per-request DB lookup (`user_repo.get_user_by_id` → `org_repo.get_org_by_id`); no
  route, header (no `X-Org-Id`), or request body field lets a client choose which org's
  data a request touches. `OrgManager.switch_org` does re-validate membership
  (`get_user_by_id(user_id, org_id=new_org_id)`), but it is dead code — no route or caller
  invokes it (already flagged as a finding in `.agents/specs/org.md`'s "Out of scope"
  section, not re-litigated here since it's unreachable).
- **Mass assignment**: `create_user` reads only `email`, `password`, `role` from the
  request body (explicit allowlist); `org_id`, `is_active` are never taken from client
  input — always `g.current_org_id` / hardcoded `True`. `update_org` reads only `name`,
  `status`. Verified `bize-mass-assignment-from-request` (pre-existing learned rule) still
  finds 0 hits in these two files.
- **Injection**: all queries go through SQLAlchemy ORM `.filter()` with bound params; no
  raw SQL, no `subprocess`, no template `| safe`/`Markup()` in this blueprint.
- **SSRF / uploads**: not applicable — no user-supplied URLs or file uploads in this
  blueprint.
- **Secrets/config**: password hashed via `AuthService.hash_password` before storage
  (`create_user`) — never persisted or logged in plaintext; `log_action` calls log
  `{"email": ..., "role": ...}`, never the password. No secrets found in either audited
  file.
- **CSRF/CORS**: governed globally (Flask-WTF, session cookies), not per-route in this
  blueprint; nothing here overrides or weakens it.
- **Self-delete / own-org-delete guards**: `delete_user` blocks an admin deleting their own
  account (AC6); confirmed via `test_delete_own_account_is_rejected`.
- **Invalid input handling**: invalid `status` (AC3) and invalid `role` (AC5) are rejected
  with 400 before any DB write; malformed `user_id` (AC6) is rejected with 400, not a 500
  or an accidental 404 that would leak "no such row" vs "not a UUID" distinctions.

## Not verified

- `gitleaks` found 17 pre-existing findings repo-wide (`generic-api-key` in
  `.claude/skills/`, `config/prod.ini`, `ci/scripts/**`, `app.py`/`app.py.bak`/`app.diff`,
  and a `gitlab-pat` in two `ci/scripts` files) — **none touch `org_routes.py` or
  `org_manager.py`**, so they are out of scope for this audit and not actioned here. They
  pre-date this branch and are tracked by `scripts/finding_history.py` (sig `d4029048b12e`)
  as `new` for whoever runs the repo-wide sweep next; not re-triaged in this run to avoid
  duplicating a wider-scope audit's job.
- Live-server / browser-driven checks (CSRF token round-trip via a real browser session,
  cookie flags over an actual TLS handshake) were not run — `app_server` is down per
  preflight, and this task's scope is the two backend files, not e2e.
- This audit does not re-verify `org_manager.py`'s `create_org_with_admin_user` /
  `switch_org` beyond confirming they are unreachable from any route in this blueprint —
  the spec marks org creation/signup and org-switching as out of scope for this review
  (covered by the `auth` spec instead).

## Environment note

At least one other review-feature audit session was running concurrently in this same
(non-isolated) worktree and independently touching the same surface: `git diff` picked up
live changes to `app/api/routes/org_routes.py`, `tests/test_org_routes.py`, plus
`app/api/routes/auth_routes.py` and `app/core/security/auth_service.py` (outside this
audit's scope) while this run was in progress, and `scripts/finding_history.py`'s
`findings.jsonl` shows a second set of records for the same three conclusions (info
disclosure, missing cross-tenant tests, `switch_org` dead code) logged within seconds of
this session's own — i.e. a duplicate "org" audit, not just the "auth" one implied by the
file set. The two runs converged on the same fix and the same tests rather than
conflicting. Findings/patches above were verified against the final, settled state (stable
`git diff --stat` across repeated checks, 23/23 tests passing in a dedicated run) rather
than blindly re-applied — re-doing already-correct work would have raced with the other
session's edits. `app/core/security/org_manager.py` was untouched by any session (0-line
diff). Two transient `sqlalchemy.exc.IntegrityError: duplicate key ...
organisations_name_key` errors mid-audit were `OrganisationFactory`'s per-process sequence
counter colliding with the other session's own pytest run against the same test DB — not a
defect in the audited code (every failing test passed cleanly in isolation, and the full
file passed 23/23 once the runs stopped overlapping). Recommend the orchestrator dedupe
concurrent dispatch of the same scope to avoid this in future runs.
