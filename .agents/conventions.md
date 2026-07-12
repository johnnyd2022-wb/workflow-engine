# Repo Conventions

Owned by the **repo-conventions** skill. Every builder (new-feature, review-feature,
fix-bug) reads this first. Extracted from evidence in this repo, not from a template —
each rule cites where it was observed. `new-feature`'s scaffold description is a rough
shape; this file is the actual, current pattern and wins on conflict.

Complements `cto-software-architect` (owns ADRs / architecture *decisions* in the
founder ops workspace). This file is code-level style + patterns, one level down from
architecture — link to ADRs when a rule exists because of one, don't restate the
decision here.

Append one lesson per shipped feature (new-feature's step 8) or fixed bug (fix-bug's
patch loop). Keep entries evidence-based: a rule without a file:line is a guess, not a
convention.

## 1. Blueprint / feature layout

Feature code lives under `app/features/<slug>/`, split by concern into subdirectories,
**not** flat files:

```
app/features/<slug>/
  routes/       # api_routes.py, page_routes.py, oauth_routes.py — thin, one Blueprint each
  services/     # <slug>_service.py — business logic, no Flask imports
  repositories/ # <name>_repo.py — one per model, all queries live here
  models/       # one file per SQLAlchemy model
  frontend/     # templates/, css/, js/
```
Evidence: `app/features/crm/{routes,services,repositories,models,frontend}/` (19 `*_repo.py`
files, 7 `*_service*.py`, 9 `*_routes.py` repo-wide — this is the established split, not
a one-off). The always-on core blueprint (`app/core/backend/backend.py`) predates this
split and is a single 5800-line file — don't copy that shape for new features; it's
legacy scale, not the pattern to follow.

Multiple `Blueprint()` objects per feature are normal: `app/features/crm/crm_bp.py:15`
(parent), plus `crm_api` (`routes/api_routes.py:14`), `crm_pages`
(`routes/page_routes.py:11`), `crm_oauth` (`routes/oauth_routes.py:18`).

## 2. Repository pattern (data access)

Every table gets a `<Name>Repository` class in `repositories/<name>_repo.py`, constructed
with a `Session`, one method per query shape. There is **no shared scoped-query helper**
— every method takes `org_id` explicitly and filters inline:

```python
# app/features/crm/repositories/product_mapping_repo.py:36-44
def get_by_id(self, mapping_id: UUID, org_id: UUID) -> ProductMapping | None:
    return (
        self.db.query(ProductMapping)
        .filter(ProductMapping.id == mapping_id, ProductMapping.org_id == org_id)
        .first()
    )
```
Same shape in `app/core/db/repositories/execution_repo.py:174,184,195` and
`app/features/crm/repositories/xero_token_repo.py:24,54,61`. Write new repository
methods the same way — explicit `org_id` parameter, inline `.filter(Model.org_id ==
org_id)` — rather than inventing a shared scoping helper the codebase doesn't have.

## 3. Auth/org-scope enforcement — a real discrepancy, not just a convention

`app/core/security/permissions.py` defines three decorators: `requires_auth` (29-52),
`requires_role` (10-26), `requires_org_scope` (29-39, checks `g.current_org_id`). In
practice **`requires_org_scope` is used almost nowhere** — only in
`app/api/routes/org_routes.py`, not in the 32 `@requires_auth`-decorated routes in
`app/features/crm/routes/api_routes.py` or the 61 in `app/core/backend/backend.py`.
Org scoping is actually enforced upstream, by `app/api/middleware/tenant_context.py`
populating `g.current_org_id`/`g.org_id` on every request (lines 44-98) before any route
runs — the decorator is a belt no one wears because the middleware is already the braces.
This matches CLAUDE.md's documented pipeline (middleware sets tenant context, decorator
just checks auth) — the decorator's existence just reads as more per-route enforcement
than actually happens. Not a bug, but new code should not assume `@requires_org_scope`
guards anything beyond `org_routes.py`; rely on the middleware having already run.

**Duplicate org-id accessor — flagged, not fixed.** The middleware sets *both*
`g.current_org_id` (already a `UUID`) and `g.org_id` (`str(org.id)`) —
`tenant_context.py:92,98`. 95 call sites read `g.org_id` (and then do `UUID(g.org_id)`
themselves, e.g. `app/features/crm/routes/api_routes.py:32`) vs 13 reading
`g.current_org_id` directly. Both work; the split is pure historical accretion, not two
intentional APIs. **Recommendation for new code: use `g.current_org_id`** (already typed,
no repeated `UUID(...)` cast) — but this file records the pattern, it doesn't migrate 95
call sites. Flagged to Johnny in the same pass that produced this file; a repo-wide
rename is a judgment call for him, not something to silently do mid-feature.

## 4. Request/response validation

No marshmallow/DRF-style schema layer repo-wide. Where a payload is complex or
security-sensitive enough to need a boundary, a **pydantic `BaseModel` with
`ConfigDict(extra="forbid")`** guards it, named after what it validates (not a generic
`schemas.py`) and colocated with the handler it guards:
`app/core/backend/complete_step_payload.py:11,39-46` — explicit size/depth/node-count
caps alongside the shape validation, because the endpoint accepts nested JSON from the
client. Simple CRUD payloads are parsed by hand in the route (`request.args.get(...)`,
manual `int()`/bounds-checking — see `list_customers` in
`app/features/crm/routes/api_routes.py:26-40`). Reach for a pydantic model at the same
bar `complete_step_payload.py` set: nested/dynamic JSON, or a mass-assignment risk — not
for a handful of scalar query params.

## 5. Inventory writes — hard rule, not a style preference

Any code touching `inventory_items.quantity` must go through the guard in
`app/core/domain/inventory_quantity_guard.py` and pass an
`InventoryQuantityWriteReason` — enforced in three layers (ORM `before_flush`, a
transaction-local Postgres GUC, and a DB trigger), documented at
`inventory_quantity_guard.py:1-20`. The module docstring's hard rule bears repeating
here because it's easy to violate from a new feature: **handlers that run inside the
same DB transaction as an inventory write must not perform external I/O, message
publishing, HTTP callbacks, or fire-and-forget async work** — side effects belong after
commit or in an out-of-band worker. This is enforced by review, not by a lint rule; treat
it as load-bearing.

## 6. Testing — flat files, no shared fixtures (a gap, not a convention to copy)

Actual layout is `tests/test_<thing>.py`, flat — **not** `tests/unit/<slug>/` +
`tests/integration/<slug>/` as `new-feature`'s scaffold in step 2 suggests. There is no
`conftest.py` anywhere in the repo. Every file that needs a DB session redefines its own
`db` fixture (e.g. `tests/test_dashboard_summary.py:21-27`), and every test needing
isolation seeds two orgs by hand and tears them down in a `finally` block
(`tests/test_dashboard_summary.py:109-149`, `org_a`/`org_b` via
`OrganisationRepository.create_org`, manual `db.query(...).filter(...).in_([...]).delete()`
cleanup). No factory-boy dependency exists yet (`pyproject.toml`'s `dev` group is ruff
only). This repetition, and the two-org/two-user world that `security-audit` and
`e2e-playwright` assume exists, is exactly what the new **test-fixtures** skill exists to
consolidate — see its `SKILL.md`. `new-feature`/`review-feature` should write new tests
as flat `tests/test_<slug>.py` files using the shared fixtures once that skill ships,
not the `tests/unit/<slug>/` shape in their current SKILL.md text.

## 7. Naming

- Files: `<name>_repo.py`, `<name>_service.py`, `<name>_routes.py` — suffix states the
  role, no `Impl`/interface split.
- Route functions: verb-first, resource-named (`list_customers`, `get_customer`) —
  `app/features/crm/routes/api_routes.py:27,44`.
- Utilities: shared/cross-feature helpers live in `app/core/utils/`; a feature's own
  helpers stay inside that feature's directory (no repo-wide `app/utils/misc.py`
  dumping ground) — confirmed by `app/utils/` holding only genuinely global things
  (`config_loader.py`) versus `app/core/utils/` and per-feature dirs holding the rest.

## Open items for Johnny (from this pass, not silently changed)

1. `g.org_id` vs `g.current_org_id` duplication (§3) — consider a repo-wide migration to
   `g.current_org_id` once there's a quiet window; 95 call sites, mechanical but not
   zero-risk.
2. `requires_org_scope` is effectively dead code outside `org_routes.py` (§3) — either
   start using it as real defense-in-depth on new routes, or accept the middleware is
   the actual enforcement and stop implying otherwise.
