# Staff site role foundations (7.1g, partial)

## Delivered boundary

Custom roles have `site_access_mode`: `all` or `selected`. Existing roles receive `all`
and no grants. Built-in roles keep all-site compatibility. `OrgRoleSite` stores selected
sites; composite organisation/role and organisation/site foreign keys prohibit tenant
mixing. No stock, execution, transfer or customer ownership files change in this slice.

Admins can prepare unassigned selected-site roles through the role editor and `/org/roles`.
Grants accept active same-org sites only. Existing archived grants survive unrelated edits,
so historical authorization is retained; archive status still prevents operational writes.
Empty selected grants mean no access. An all-site role cannot carry selected grants.
Role/grant/assignment changes serialize through an organisation `FOR NO KEY UPDATE` lock.

**Selected-role assignment stays closed.** Creating or inviting a person with a selected
role, changing a person's role to selected, and changing an occupied role to selected all
fail on the server. There is no additional admin switch. The code release gate is false.
A future activation MR needs complete subject/projection guards; flipping the constant
alone grants no handler access because every sensitive registry entry remains blocked.

A privileged/raw selected assignment also fails closed in central middleware. Fresh scalar
SQL, in one statement, resolves the trusted user/org/custom role/grants and bypasses ORM
identity-map cache. Missing, foreign, mismatched or malformed roles and missing/empty selected
grants never fall back to built-in permissions/all sites. No organisation site/operations
flag appears in this authorization decision: opt-out cannot remove staff restrictions.

Authentication/session-exit and immutable public assets have exact endpoint/method
exemptions. Ordinary RBAC's `PUBLIC` contract is not reused: `/auth/me` returns private
information, and broad `serve_*` handlers can render private projections. Staff-site
middleware runs before RBAC redirects, and retains normal RBAC checks for all-site users.
The scope is immutable and request-local, and is explicitly cleared at teardown.

The static registry covers all live endpoint/method pairs on this base and the pending
whole-org CCA movement register. Unknown additions default to denial; the coverage test
requires an explicit audit entry. Being listed as blocked is not an operational guard.

## Next activation audit

All of the following remain blocked for selected staff until their reviewed integration.
Every server mutation must authorize trusted persisted subjects, rather than client tags.
An explicit selected/default site may narrow scope, never broaden it; an ungranted default
or unknown/null historical site fails closed. Customer ownership and staff sites intersect.

| Surface | Files / required guard or projection |
| --- | --- |
| Inventory CRUD, adjust, FIFO/manual sales | `app/core/backend/backend.py`, `inventory_repo.py`: explicit granted shipping site; all consumed/deposited lots checked before writes; selected queries filtered and aggregates recomputed. Carve routes first rather than expand the legacy file. |
| Barcode/CSV | `inventory_upload_routes.py`: barcode matches and CSV preview/commit only resolve authorized sites/lots; no preview or error leaking remote matches. |
| Production | `ExecutionRepo`, core completion hook: Step → Execution → Order → Org/Site → sorted Inventory. Persisted execution site, all actual/reconciliation inputs and inherited outputs require grants. No partial debit before preflight. |
| Locations and legacy moves | `stock_locations.py`: site grants checked against persisted location and every source/destination lot, preserving existing physical/owner guards. |
| Transfers | `features/site_transfers`: source **and destination** grants required for dispatch, receipt, loss, options, list, detail, docket and snapshot projections. Remote execution/stock history must not leak in lineage. Destination-only receiving requires a separate deliberately limited projection later. |
| Evidence and lineage | `core/backend/evidence`, workflow traces and reconciliation: authorize parent execution before file bytes, children, embedded JSON or historic graph traversal. Filtering only the current lot site is insufficient. |
| Stocktakes and wastage | `stocktake.py`, wastage routes: scope every counted/resolved/debited lot before writes. Existing org-wide stocktake headers cannot be presumed single-site; unproved headers remain blocked. |
| Planning | `features/planning`: batches/board/start plus material snapshots and dependent executions. Current demand headers are org-wide; narrowing batch rows alone does not secure their aggregates or cancellations. |
| Dashboard, activity and feeds | dashboard/activity routes and `changes_feed.py`: raw SQL, cursors, ETags, counts and JSON payloads require scoped sources. Deleted/legacy events lacking trusted site proof cannot be guessed to the default site. |
| CRM/sales valuation and reconciliation | Sales imports, manual consumption, value/cost reports and matches require granted shipping stock and the ownership guard; global totals can leak inaccessible lots. |
| Module registers/exports | Compliant CCA movement GET stays blocked until period aggregates and both-end source/destination snapshots are filtered. Module routes belong to their owner. |
| Customer portal realm | Customer principal authorization is separate; never turn an external customer principal into staff all-site access. Background jobs use an explicit system context, not implicit absence of scope. |

Query criteria are defense in depth, not a substitute for DTO/file/raw-SQL authorization.
Before-flush mutation guards must also catch retained identity-map instances, bulk paths,
children and inferred destinations. All unsupported paths remain denied during activation.

## Concurrency and prerequisites

This migration follows the two actual heads `contract_orders_001` and `multiple_sites_001`.
It does not rewrite applied planner/contract migration ancestry. The integration owner can
restack the new migration after intervening heads; submitted parents remain untouched.

Middleware does not take an ambient organisation lock: planned-batch services currently
upgrade to `FOR UPDATE`, and concurrent SHARE→UPDATE upgrades could deadlock. Before any
future stock write, refresh staff scope after the existing organisation SHARE lock and before
site/inventory locks. Admin assignment/grant changes use NO KEY UPDATE, which conflicts with
SHARE while remaining compatible with foreign-key KEY SHARE. Review this with the ownership
Step → Execution → Order → Org/Site → Inventory lock order and add revocation-versus-write
regressions in the activation MR. Read authorization is a single-statement snapshot.

Downgrade refuses assigned selected roles; removing restrictions must not silently broaden
holders to all sites. Privileged raw SQL bypasses API staging and can configure invalid data,
but request scope still rejects it. Full 7.1g remains open.
