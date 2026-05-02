Below is a production-grade review focused only on the changes you showed, prioritised by severity (Critical → High → Medium → Low) and grouped by file. I’m focusing on security, data integrity, performance, and operational risk.

🔴 app/core/backend/checks/output_ready_date_check.py
⚠️ HIGH — N+1 query risk + unbounded ORM load in hot path
Issue
execution_step = (
    session.query(ExecutionStep)
    .filter(ExecutionStep.id == step_id)
    .options(joinedload(ExecutionStep.step))
    .first()
)

This function is called from list_inventory() per item:

rdt = get_operator_ready_instant_for_item(db_session, item)

That makes this effectively:

N inventory items → N SQL queries

Even with small datasets, this becomes a latency multiplier in inventory endpoints.

Risk
Degraded /inventory performance under load
DB connection saturation
Unpredictable response times (P95 spikes)
Recommendation

You need to pre-resolve execution steps in batch, not per item.

Options:

Preload all ExecutionStep for source_execution_step_id in one query
Pass a lookup map into the function
Or compute ready dates in a repository-level join
⚠️ MEDIUM — Defensive parsing inconsistency (actual structure trust)
actual = extra.get("ready_date_actual")
if isinstance(actual, dict) and actual.get("date"):
Issue
Assumes actual is dict-shaped JSON from DB
No schema validation
No fallback if malformed string/epoch/etc.
Risk
Silent failures (returns None)
Inconsistent inventory state between environments
Recommendation

Enforce a schema contract:

Either Pydantic validation upstream
Or strict coercion layer:
if isinstance(actual, dict):
    date = actual.get("date")
elif isinstance(actual, str):
    date = actual
else:
    return None
🟡 LOW — Early return reduces diagnostic visibility
if not config:
    return None
Issue

You lose observability on why ready date couldn't compute.

Recommendation

Log at debug level with context:

item.id
step_id
out_def.name
🔴 app/core/backend/backend.py

This is the highest risk file in the diff.

🔴 CRITICAL — Transaction control bug risk (double rollback + inconsistent state)

You now have multiple failure exits:

if execution_errors:
    db_session.rollback()
    return jsonify(...), 400

Appears twice in different sections of the same flow.

Risk

Depending on execution path:

partial DB flush already occurred
rollback may not restore in-memory ORM state
side effects may already have executed (inventory, audit, etc.)
Why this is serious

You explicitly commented:

"Single transaction"

But current structure allows:

partial flush
conditional rollback mid-flow
inconsistent inventory + execution step state
Recommendation (strong)

Refactor into a single atomic boundary:

with db_session.begin():
    ...

Then:

remove manual rollback() calls in business logic
let exception handling control rollback
🔴 CRITICAL — Security: trust boundary leakage via execution_data
if execution_data.get("completed_by_email") is not None:
    trace["completed_by_email"] = execution_data["completed_by_email"]
Issue

This is client-controlled input being persisted into trace/audit context.

Risk
Identity spoofing (any user can claim completion email)
Audit trail contamination
Compliance risk (if used for traceability or QA)
Recommendation

Never trust this field directly:

derive from authenticated session/user context
or validate against org membership
trace["completed_by_email"] = current_user.email
⚠️ HIGH — Missing authorization check visibility (hidden risk in refactor)

The snippet shows no validation around:

execution_step ownership
org isolation enforcement (beyond repo call assumption)
Risk

If repo layer is incomplete:

cross-org step completion possible
Recommendation

Ensure:

execution_step.org_id == org_id validated at service boundary OR DB layer
⚠️ HIGH — Redundant rollback paths increase failure complexity

You now have:

rollback on validation error
rollback on inventory failure
rollback on exception handler
Risk
unpredictable DB session state transitions
harder incident debugging
possible “rollback after rollback” no-op confusion masking real bugs
Recommendation

Centralise error handling:

try:
    with db_session.begin():
        ...
except Exception:
    logger.exception(...)
    return 500
🟡 MEDIUM — Potential expensive ORM lazy loading (hidden)
step_def = getattr(execution_step, "step", None)

No joinedload in repo call.

Risk
implicit lazy load per request path
contributes to DB chatter under load
Recommendation

Ensure repository returns:

options(joinedload(ExecutionStep.step))

(you did this elsewhere, but not guaranteed across all paths)

🟡 list_inventory() changes (same file section)

This block is where most performance debt accumulates.

🔴 CRITICAL — N+1 query regression introduced (execution_step lookup per item)
execution_step = (
    db_session.query(ExecutionStep)
    .filter(ExecutionStep.id == item.source_execution_step_id)
    .first()
)
Severity

Same issue as earlier but worse because:

happens inside inventory loop
also fetches execution_data + outputs parsing
Impact

For 500 items:

500 extra queries
JSON processing overhead per row
Recommendation

Batch preload:

step_ids = {item.source_execution_step_id for item in items}
steps = session.query(ExecutionStep).filter(ExecutionStep.id.in_(step_ids)).all()
step_map = {s.id: s}

Then use in-memory lookup.

⚠️ HIGH — Exception swallowing hides production issues

Repeated pattern:

except Exception:
    pass

and:

except Exception:
    pass
Risk
silent data corruption
missing fields without trace
debugging blind spots in production
Recommendation

At minimum:

logger.debug("inventory hydration failure", exc_info=True)

or structured error metric.

⚠️ MEDIUM — Unbounded JSON mutation risk
extra_data = {**(item.extra_data or {})}

Then multiple conditional inserts.

Risk
inconsistent schema drift in extra_data
large JSON payload growth over time
potential payload bloat in API responses
Recommendation
enforce schema versioning in extra_data
or migrate derived fields out of JSON into columns
🟡 LOW — Redundant defensive getattr usage
getattr(execution_step, "step", None)

If ORM is consistent, this is unnecessary overhead and hides model contract expectations.

🟡 app/core/db/repositories/inventory_repo.py
⚠️ HIGH — SQL injection surface via JSONB key access pattern
tagged_pid = InventoryItem.extra_data["producing_process_id"].astext == str(process_id)
Risk
JSON path injection is less about SQLi, more about:
schema manipulation
unexpected coercion behaviour
index bypass
Recommendation

Ensure:

process_id strictly validated as UUID/int before string conversion
ideally move producing_process_id to a column
⚠️ MEDIUM — OR condition disables index efficiency
or_(Execution.process_id == process_id, tagged_pid)
Impact
likely prevents index usage
forces seq scan on Execution join
Recommendation

Split query or use UNION ALL pattern for performance:

one indexed query on Execution
one filtered JSON query
combine in Python or union subquery
🟡 LOW — outerjoin always executed even if unnecessary

You always join Execution even when only JSON tag used.

Recommendation

conditionally build query depending on presence of process_id filtering mode.

🟡 app/core/backend/reconciliation_service.py
🟡 LOW — unsafe getattr pattern for data shaping
getattr(item, "supplier_batch_number", None)
Risk
inconsistent model contract hiding
silent schema mismatch bugs
Recommendation

Prefer explicit model fields unless polymorphic ORM required.

🧾 Summary (priority order)
🔴 CRITICAL (must fix immediately)
N+1 query explosion in inventory listing (ExecutionStep lookup per item)
Transactional inconsistency due to manual rollback strategy
Trusting client-provided completed_by_email (audit spoofing risk)
⚠️ HIGH
JSON-based filtering in SQL (extra_data["producing_process_id"])
Excess ORM lazy loading risk in execution step hydration
Hidden cross-org ownership validation risk
🟡 MEDIUM
Exception swallowing in inventory hydration
Schema drift risk in extra_data
OR-query index inefficiency in repository filtering
🟢 LOW
Missing observability in ready-date fallback paths
Defensive getattr overuse
outerjoin always executed regardless of need