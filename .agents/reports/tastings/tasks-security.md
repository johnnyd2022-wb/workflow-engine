# SECURITY: Tastings as a Tasks type

date: 2026-10-27
verdict: clean
scope: HEAD `28010005` to working tree; typed Tasks integration
execution: inherited-model read-only security grader; manual tenant-security equivalent included because that separate skill is unavailable
manual_checklist: 7/7 completed

Read `.claude/skills/security-audit/SKILL.md` and `.agents/specs/tastings-tasks.md`. No app/test/script/schema edits or delegation. Root's E2E stage ran in the declared parallel group; all my writes were confined to this report. All dynamic checks used only `workflow-engine-test_tastings_build`, with independently created orgs purged in `finally`.

## Scanner pass and explicit triage

Fresh scoped Semgrep ran Python/Flask/OWASP and repository rules over the Tastings package, changed CRM routes/services/repositories/model/JS, Core tasks and both task-type migrations. It returned **two migration-only matches** and one Jinja partial-parse warning:

1. `tastings_tasks_002_backfill_task_types.py:22`, `semgrep.rules.sqlalchemy-query-in-for-loop`: the deliberate migration loop executes bounded1000-row UPDATE batches for two fixed passes. It is not a per-task SELECT/read N+1. It implements the migration-safety requirement rather than a request-path workload. Builder can add a narrow justified annotation if a zero-match enforcement gate requires it; this read-only reviewer added no suppression.
2. Same line, `python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text`: SQL concatenates one of **two literal internal migration predicates**; the assigned type value is a bound `:value` parameter. No request, URL, user, tenant text or external data supplies SQL syntax. There is no demonstrated SQL-injection path. Prefer a scoped comment documenting these static inputs rather than a broad ignore.

History-store `decide` returned `new` for both signatures (`7c1ae766d334`, `4766c99ea215`); no prior human suppression or accepted-risk decision was invented. These applicability conclusions are source-based triage, not an accepted-risk grant. No app security finding was reported by this scan. Jinja extension/block tags remain partially parsed; I manually inspected the included template and JS output sinks rather than claiming full template scanner coverage.

Fresh redacted gitleaks scans covered the current tracked app diff (~79KB), untracked typed backend tests (~6KB), and both new migration files: **no leaks found**. This was a worktree check, not a full-history certification. Dependencies/lockfile are unchanged in this refinement; the earlier frozen audit's94 packages/zero vulnerabilities is retained evidence, not represented as a newly rerun dependency audit here.

## Manual checks

- **Auth and role/site gates:** new task GET has `requires_auth`, falls under existing CRM sales.view policy and is explicitly blocked for selected-site staff in the registry. Unified POST retains existing CRM sales.record enforcement and selected-site block. Specialized dispatch retains its additional inventory.adjust requirement. Read-only Auditor cannot create via the new generic entry point.
- **Tenant/object scoping:** direct GET predicates combine session org, UUID and subscription visibility. Unified creation obtains org/actor from request context and delegates to the existing same-org rep/contact/item/pool validators. No nested org/actor/task ID is mass-assigned. Wrong-org GET returns404 rather than leaking a record; foreign allocation/assignee input returns generic validation400.
- **Subscription lapse:** generic list/direct GET/contact detail and contact last-contact aggregation share the visibility predicate; Core normal/archive use it before limits. Both explicit tasting type and actual event linkage are hidden, preventing stale/unbackfilled general labels from exposing a linked event. Unified tasting POST rechecks the subscription independently of the specialized blueprint. Accounting history remains stored.
- **Forged lifecycle/type:** outer tasting creation accepts exactly type+nested tasting payload. The inner service keeps its explicit allowlist. Ordinary creation rejects unsupported/non-string/tasting types outside the specialized branch. Ordinary PUT cannot attach tasting type; actual event relationships prohibit edits/deletes/lane changes even if the caller submits general or omits task_type. UI hiding is not the authority.
- **CSRF/CORS:** neither new GET nor unified POST changes CSRF configuration or adds exemptions. Non-Core JS wrapper sends the common CSRF header and same-origin credentials; direct GET carries no mutation. No new CORS policy introduced.
- **Injection/output/SSRF:** encoded IDs/query values; parameterized ORM object lookups; no user-supplied HTML, unsafe Jinja filter, shell/file operation, URL fetch or upload path introduced. The compatibility redirect constructs a fixed local Tasks URL from a validated same-org event's task UUID.
- **Config/secrets:** no new secret/debug/session-cookie configuration. `TESTING=True` is confined to test-created apps. Header/dataset permission hints are cosmetic; server checks remain intact.

## Stock and transactional safety

The unified entry point invokes the existing event/task atomic save path, not a preliminary generic task write. Validation/integrity failures roll back; the success response exposes the actual one linked task and event. No new stock mutation occurs from choosing a type, scheduling, generic completion or changing a lane. Dispatch still validates producer ownership/provenance, same-org pool/source references, whole-pack/conversion facts and dated source authority under the existing locks. Finalisation/reuse/cancellation/excise snapshot behavior is unchanged by this refinement. The new task-type default/backfill does not modify pool balances or immutable removal evidence.

## Independent dynamic evidence

`PYTHONPATH=. ENVIRONMENT=test uv run python /tmp/tastings_pytest.py tests/test_tasting_task_types.py -q -p no:cacheprovider`: **9 passed**, three existing Flask-Limiter warnings,2.60s. Covers one typed task/event, no partial task on invalid nested details, generic mutation rejection, lapse, allowed/default/forged types and database check enforcement.

Additional real login/Flask test-client probes, with two distinct subscribed orgs and retained foreign records, all passed:

- New direct task GET for the other org:404.
- Unified tasting POST with foreign warehouse source:400; foreign rep:400.
- Auditor unified POST:403.
- Forged top-level status on specialized creation:400.
- Generic PUT attempting to detach/complete a linked tasting:400.
- Unified POST without CSRF after enabling protection:400.
- After lapse: direct GET404 and unified tasting POST404.
- A tasting linked to a customer was visible in customer detail before lapse and absent afterward; Core list also excluded it.

Eleven hostile/authority/lapse assertions completed. Probe data was purged; no migration ran. Selected-site restrictions were verified in code/registry, not falsely described as an extra live site-login probe. Root's separate browser/expanded regression results are outside my independently executed counts.

No new feature-scoped security vulnerability remains open. No learned rule was added because this manual pass found no new vulnerability class; the two scanner matches above already have rules and are intentional migration constructs. Later source changes and exact-head CI still require their normal checks.

## Fresh-main integration security delta

Re-reviewed after merging main `1468fea4`, which introduces `CRMTaskRepository.dashboard_open_tasks` for Home's narrow projection. Root added the existing `visible_task_filter(self.db, org_id)` to that reader's SQL filter, alongside the explicit authenticated org and open-status predicates, before ordering/materialization. This closes the newly introduced alternate read path without hydrating all task/event models or filtering returned records after collection. The customer outer join retains its own same-org predicate.

Read `get_dashboard_overview`, the repository projection and surrounding existing task readers together. Home's service delegates its entire task collection to this filtered method; no second unfiltered task query exists in that service. Active subscribers retain their open tasting records; after lapse, both typed and relationship-linked tasting tasks are excluded by the same shared policy as other generic readers. Ordinary open tasks and the narrow response fields remain unchanged. No mutation, new authorization shortcut, lifecycle action or stock write is introduced.

The existing lapse test now proves that the tasting appears through `get_dashboard_overview()["open_tasks"]` before disabling NZ Alcohol and that the exact remaining set afterward is the independently created ordinary task. This catches both the original lapse leak and a degenerate implementation that always returns no tasks. I inspected the assertions and ran scoped `git diff --check`; no database mutation or test execution was performed for this read-only delta. Root's in-progress private-DB backend run remains its own evidence.

No open finding in this merged Home-reader integration.

### Final Home projection revision — supersedes the eager SQL-filter implementation above

Read the final `dashboard_open_tasks` implementation after the constant-query tests identified the eager subscription lookup's cost. The task SQL now projects `is_tasting` as `(task_type == 'tasting') OR EXISTS(actual linked event)` alongside the same narrow task/customer fields. Authenticated org and open-status predicates remain in SQL, and the customer join remains same-org. The EXISTS is part of that one projection query; it does not hydrate task/event objects or execute one ORM query per row. The linked task identity is unique and protected by the existing same-org task/event constraints.

Only when at least one projected row is specialized does the reader call `nz_alcohol_active` once. If inactive, it excludes every specialized row **before returning the public task dictionaries**, so Home's caller cannot count, link or serialize them. This reader has no limit/pagination; filtering here therefore cannot underfill a page or expose totals derived from unfiltered specialized rows. Matching either the declared type or actual event link preserves the earlier protection against stale/unbackfilled labels. Empty/ordinary-only collections incur no subscription query from this method.

This final pattern retains the subscription security boundary and avoids the eager lookup's extra ordinary-tenant query count. Structural review establishes one scalar projection and at most one entitlement decision, not a measured latency result; root's constant-query and lapse test reruns supply runtime confirmation separately. The existing regression still proves specialized visibility before lapse and the exact ordinary-only set afterward through the actual Home service. No new finding, database mutation or test/source edit in this review.

VERDICT: clean
