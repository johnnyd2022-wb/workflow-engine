# Global wins: other places where per-call-site discipline stands in for a structural guarantee
date: 2026-08-09
context: written alongside the global ORM tenant-scoping change (app/core/db/tenant_filter.py,
app/core/db/tenant_flush_guard.py, app/core/db/models/tenant_mixin.py) — that work replaced
"every repository method must remember `.filter(Model.org_id == org_id)`" with a structural
guarantee at the ORM layer. This document catalogues other places in the app with the same
shape: a security or correctness property that depends on every call site remembering to do
the right thing, rather than the framework making the wrong thing hard to write. Candidates
below are investigated and evidenced, not assumed — none are fixed here; this is a catalogue
for future work, prioritized security-first.

## 1. `requires_org_scope` is dead code outside one blueprint — real enforcement is 100% implicit

**Evidence:** `app/core/security/permissions.py:42` defines `requires_org_scope`, a decorator
that aborts 400 if `g.current_org_id` is unset. Grepped every usage: exactly 5, all in
`app/api/routes/org_routes.py` (lines 25, 47, 124, 165, 228). The other 148 `@requires_auth`
routes across `app/core/backend/backend.py` and `app/features/crm/routes/api_routes.py` never
apply it. Tenant-context enforcement for those 148 routes is entirely implicit: the
`tenant_context.py` middleware populates `g.current_org_id` before any route body runs, and a
route that never checks it just... has it available, or doesn't notice if it's missing.

**Impact:** Low today (the middleware's `abort(403)` on missing/invalid user already closes
the realistic gap — an authenticated request always has org context by construction), but
it's a decorator whose name promises a guarantee 97% of routes don't actually request, which
is misleading to read and easy to reach for as false reassurance ("this route has
`requires_org_scope`" vs. "this route runs after tenant-context middleware, same as every
other route"). Now that the global ORM filter (this branch) enforces org scoping structurally
at the data layer, the decorator's remaining value is close to zero — it checks a precondition
the ORM layer no longer depends on.

**Effort:** Small. Either (a) delete `requires_org_scope` and its 5 usages, documenting that
tenant context is a middleware-wide guarantee, not a per-route opt-in — or (b) rename/repurpose
it as an explicit *no-org-context-expected* marker for the few routes that are legitimately
org-agnostic, inverting its meaning to match how it's actually used. (a) is more honest about
current reality.

## 2. Raw SQL bypasses the new global tenant filter entirely — by design of the mechanism, not a bug in it

**Evidence:** `with_loader_criteria`/`do_orm_execute` (this branch's mechanism) only intercepts
ORM-mapped statements — confirmed in `tenant_filter.py`'s own guard clause
(`execute_state.is_orm_statement`) and empirically in `tests/test_tenant_filter_spike.py`
(a raw `text()` call reports `is_orm_statement=False`). Four real `session.execute(text(...))`
call sites touch application data directly:
- `app/core/backend/event_writer.py:171-201` (`_do_upsert`) — raw `INSERT ... ON CONFLICT`
  into `entity_event_summaries`; `org_id` is a bound *value*, not a filter.
- `app/core/backend/event_writer.py:224-231` (`_load_existing_summary`) — raw `SELECT summary
  FROM entity_event_summaries WHERE entity_id = :eid`, **no org_id in the WHERE clause at
  all**. Judged safe today because `entity_id` is the table's PK and is always derived from an
  already org-scoped `items` list upstream — but that safety is an invariant of the caller,
  invisible at this call site, and silently stops being true if a future caller passes an
  unscoped `entity_id`.
- `app/core/backend/checks/output_ready_date_check.py` — raw `text()`, not yet audited for
  tenant-data exposure as part of this pass.
- `app/core/domain/inventory_quantity_guard.py` — raw `text()` calls are GUC/session-config
  sync (`set_config('app.inventory_qty_guard', ...)`), not tenant data; out of scope here.

**Impact:** Medium. This is a real, permanent gap in the new global mechanism's coverage —
it doesn't retroactively make raw SQL safe, and the ORM migration doesn't reduce the incentive
to reach for raw SQL for performance-sensitive paths (upserts, bulk ops) where it's most
tempting. `event_writer.py`'s two call sites are the concrete, named exposure.

**Effort:** Medium. A semgrep rule flagging `session.execute(text(...))` / `.execute(text(...))`
against any table backed by a `TenantScoped` model, requiring an explicit `# nosemgrep` with a
justification comment (mirroring the `# nosemgrep: route-missing-requires-auth` convention
already used in `app/api/app_factory.py`), would make every future raw-SQL tenant-data access
a deliberate, reviewed decision instead of an invisible one. Fixing the two known
`event_writer.py` sites to include `org_id` in their WHERE/ON CONFLICT clauses is a smaller,
independent fix that doesn't need the semgrep rule to land first.

## 3. `ondelete` behavior on `org_id` foreign keys is inconsistent, and no migration reconciles it

**Evidence:** Discovered directly while building the `TenantScoped` mixin for this branch.
Live schema check (not just model source) shows: `users`, `audit_logs`, `entity_events`,
`entity_event_summaries`, and every CRM table (`xero_tenants`, `xero_contacts`,
`xero_invoices`, `xero_invoice_line_items`, `xero_sync_jobs`, `xero_oauth_tokens`,
`crm_notes`, `crm_tasks`, `product_mappings`, `crm_sales_traceability_config`) have
`ON DELETE CASCADE` on their `org_id` FK at the DB level. `processes`, `process_versions`,
`process_step_documents`, `inventory_items`, `inventory_movements`, `inventory_wastage`,
`execution_evidence`, `executions`, and `api_idempotency_keys` do not — confirmed via `\d` on
the live test DB, not inferred from model source (which had already drifted from reality in
three cases, see #4). Deleting an `Organisation` today cascades cleanly through one set of
tables and raises `ForeignKeyViolation` on the other — reproduced directly during this
branch's own test-writing (`tests/test_tenant_filter.py`'s `two_org_two_user` teardown hits
exactly this on `process_versions` before a manual cleanup step was added).

**Impact:** Medium. There is no organisation-deletion flow in the product today (confirmed:
no route or CLI command calls `session.delete(org)` or bulk-deletes an `Organisation`), so
this hasn't caused a production incident — but it means "delete a test org" is landmine-y
for exactly the tables without CASCADE, and any future org-deletion/GDPR-erasure feature would
hit this immediately and inconsistently table-by-table.

**Effort:** Medium — a single migration adding `ON DELETE CASCADE` to the 9 FKs listed above
(mirroring the pattern already used twice: `org_fk_cascade_users_audit_001.py`,
`event_sourcing_org_cascade_001.py` — drop constraint, recreate with `ondelete="CASCADE"`),
would make the behavior uniform. Deliberately **not** done as part of this branch's
`TenantScoped` mixin — bundling an unrelated schema behavior change into a tenant-scoping
security fix was judged out of scope; see `tenant_mixin.py`'s docstring for the same
reasoning recorded at the point the decision was made.

## 4. SQLAlchemy models have already drifted from the live schema at least 3 times, silently

**Evidence:** Found while investigating #3. `AuditLog.org_id` and `EntityEvent.org_id` declared
no `ondelete` in their models, yet the live DB already had `ON DELETE CASCADE` on both (added
by `org_fk_cascade_users_audit_001` and `event_sourcing_org_cascade_001` respectively) — the
model was simply never updated to match after those migrations shipped. `EntityEventSummary
.org_id` had no `ForeignKey` declared **at all** in the model, while the live DB has had one
(`entity_event_summaries_org_id_fkey`, CASCADE) since `event_sourcing_org_cascade_001`. None
of these three were caught by anything before this pass — they were only found because
building `TenantScoped` required inspecting every `org_id` column by hand.

**Impact:** Low-to-medium by itself (none of the three drifted in a way that caused incorrect
runtime behavior — SQLAlchemy's `ondelete=`/`ForeignKey` presence is DDL-generation metadata,
not enforced by the ORM at query time), but it's a structural blind spot: nothing currently
checks that `app/core/db/models/*.py` actually matches the schema Alembic has applied. The
next drift might not be this benign — a model missing a `nullable=False` that the DB enforces,
or a stale `unique=True` after a migration relaxed it, would misdescribe real constraints to
anyone reading the model as documentation.

**Effort:** Small-to-medium. `alembic revision --autogenerate` against a fully-migrated DB
already computes exactly this diff (that's how it decides what a new migration needs to
contain) — a CI/scheduled job that runs autogenerate against a scratch DB and fails if it
produces a non-empty migration would catch this class of drift automatically, without needing
new tooling. The **docs-truth** skill's mandate ("verifies documented facts... against the
real ini files and source") is the closest existing analogue in this repo; this is the same
idea applied to schema-as-documentation instead of prose docs.

## 5. Audit logging (`log_action`) is an opt-in call, not a systemic guarantee

**Evidence:** `app/core/utils/log_action.py` defines `log_action(...)`; grepped 28 call sites
across `app/` against 148 `@requires_auth` routes. A mutating route that never calls
`log_action` produces no audit trail — there's no structural guarantee every write is logged,
only convention that the ones someone remembered to instrument are.

**Impact:** Medium, compliance-adjacent — this is exactly the kind of gap that shows up as "we
can't tell you what changed" during an incident or audit, and it's invisible until that
moment (unlike a missing org filter, a missing audit log doesn't produce an error or a test
failure — it produces silence).

**Effort:** Medium-large. The same mechanism this branch just built for tenant scoping
generalizes here: a `before_flush`/`after_commit`-style listener that logs every
insert/update/delete on `TenantScoped` models automatically would make audit coverage
structural instead of per-route. Bigger scope than #1-#4 (needs a decision on what "changed"
means for a diff-style log entry, and probably a allow-list of tables to exclude from
auto-logging — e.g. `api_idempotency_keys`, `entity_events` itself), so sizing it as its own
follow-up rather than a quick fix.

## 6. The one existing tenant-isolation semgrep rule doesn't catch the query shape that actually leaked

**Evidence:** `.semgrep/rules/python-multitenant.yml`'s `filter-by-missing-org-id` rule
pattern-matches `$Q.filter_by($...KWARGS)` — the keyword-argument style. The confirmed
CRITICAL/MEDIUM findings in `.agents/reports/{inventory,execution}/security-audit.md` were all
`.filter(Model.x == y, ...)` — the positional/expression style this codebase actually uses
throughout (confirmed in the original tenant-scoping research: zero `.filter_by()` usage found
across the repo's repositories). The existing rule would not have caught the bug class it
exists to catch.

**Impact:** Now largely superseded by this branch's ORM-level fix (the global filter closes
the gap structurally, regardless of query style), but worth recording: a static-analysis rule
that never matches anything in the codebase it's meant to protect is worse than no rule, if
its presence in `.semgrep/rules/` reads as "this is covered."

**Effort:** Small. Either extend the rule to also match `.filter(...)` calls lacking an
`org_id` comparison (harder to pattern-match precisely, since `.filter()` takes arbitrary
expressions, not keyword args), or retire it in favor of relying on the ORM-level guarantee
plus a comment explaining why. Not urgent given #2 and the ORM fix are the real backstops now.

## Priority read

Security-first ordering: **#2** (raw SQL bypasses the new tenant filter) and **#3** (CASCADE
inconsistency, landmine for any future org-deletion feature) are the two worth picking up
next — both have concrete, named call sites, not just categories. **#4** (schema drift
detection) is the highest-leverage *structural* fix — it would have caught #3's root cause
automatically. **#1** and **#6** are cleanup/honesty fixes, not open exposure, now that the
ORM-level filter is the real backstop. **#5** is the largest single win but also the largest
lift — good candidate for its own dedicated pass rather than a quick follow-up.
