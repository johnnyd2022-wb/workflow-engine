# SPEC: org
status: reviewed
name: Organisation Management
slug: org
blueprint: app/api/routes/org_routes.py (not a package blueprint — registered directly in app/api/app_factory.py as org_bp)
url_prefix: /org

## Description
Organisation-scoped administration: viewing and updating the current org's profile
(name, status), and managing the users that belong to it (list, create, soft-delete).
Backed by `OrganisationRepository`/`UserRepository` and `OrgManager`
(app/core/security/org_manager.py) for org+admin-user creation and org switching.
All routes operate on `g.current_org` / `g.current_org_id`, set by `@requires_org_scope`.

## Users & permissions
- roles: MEMBER (read), ADMIN (write)
- tenant_scoped: yes — every route resolves through `g.current_org_id`; `list_users`,
  `create_user`, `delete_user` filter/create against that org only.
- ASSUMPTION: `GET /org` and `GET /org/users` are readable by any authenticated org
  member (`@requires_org_scope` only); `PATCH /org`, `POST /org/users`,
  `DELETE /org/users/<id>` additionally require `@requires_role(UserRole.ADMIN)`. This
  matches the decorators present in the code as of this review.

## Acceptance criteria
- AC1: `GET /org` returns the current org's id/name/status/timestamps for any
  authenticated member of that org; 404 if `g.current_org` is unset.
- AC2: `PATCH /org` (admin only) updates name and/or status, logs the action via
  `log_action`, and emits an `org.settings_updated` audit event containing only the
  fields that actually changed (diff-based).
- AC3: `PATCH /org` rejects an invalid `status` value with 400 before touching the DB.
- AC4: `GET /org/users` lists all users (active and inactive) scoped to
  `g.current_org_id` only — never another org's users.
- AC5: `POST /org/users` (admin only) creates a user scoped to the current org, hashes
  the password before storage, rejects a duplicate email with 400
  (`EmailConflictError`), rejects an invalid `role` with 400, and logs the creation.
- AC6: `DELETE /org/users/<user_id>` (admin only) soft-deletes a user that belongs to
  the current org; 404 if the user_id doesn't resolve within this org (cross-tenant
  delete is not possible); 400 if `user_id` isn't a valid UUID; 400 if an admin targets
  their own account (self-delete blocked).
- AC7: A non-admin member calling `PATCH /org`, `POST /org/users`, or
  `DELETE /org/users/<id>` receives 403 (via `@requires_role`).
- AC8: A user authenticated into org A cannot list, create, or delete users in org B
  (cross-tenant isolation on every route in this blueprint).

## Data model
- changes: none (existing `organisation`, `user` tables)
- destructive: no

## External surfaces
- none (internal DB-backed CRUD only; emits internal audit events via `emit_event`)

## Out of scope
- Org creation flow (`OrgManager.create_org_with_admin_user`) — that's part of
  auth/signup, covered by the `auth` spec.
- `OrgManager.switch_org` — appears unused by any route in this blueprint; dead code or
  wired elsewhere. Flagged as a finding, not assumed in scope here.
