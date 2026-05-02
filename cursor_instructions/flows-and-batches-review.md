This is now much closer to production-grade. The remaining issues are no longer “obvious bugs” but tight edges around correctness, query planning, and data-contract enforcement.

I’ll focus strictly on what changed.

🔴 CRITICAL FINDINGS
1. ⚠️ ExecutionStep filtering via Execution.id IN subquery is logically correct but can silently degrade query plans
What you changed
org_execution_ids = db_session.query(Execution.id).filter(Execution.org_id == org_id)

ExecutionStep.execution_id.in_(org_execution_ids)
Why this is still critical

This pattern is correlated subquery without materialization guarantee.

On Postgres, depending on planner state:

it may re-evaluate subquery per row
or fail to use index-only scan on execution_id
or produce a hash semi-join (good) OR nested loop (bad under scale)
Risk in production
inventory endpoint latency spikes under large Execution tables
unpredictable query plans across environments (dev vs prod drift)
worst-case: O(n × m) planner fallback
Recommendation (important)

Force materialisation:

org_execution_ids = [
    id for (id,) in db_session.query(Execution.id)
    .filter(Execution.org_id == org_id)
]

Yes—it looks less “clever”, but:

guarantees stable plan
removes planner ambiguity
converts to indexed IN list

OR (better long-term):

denormalise org_id onto ExecutionStep
2. ⚠️ CRITICAL — _strip_incoming_execution_trace_keys now creates a false sense of security boundary
What improved

Good:

explicit removal of trace keys from client payload
centralised sanitisation
Subtle remaining issue
return {k: v for k, v in execution_data.items() if k not in _EXECUTION_DATA_TRACE_KEYS}
Problem class

This assumes:

“if key is removed, system is safe”

But downstream:

execution_data is still merged elsewhere
unknown keys are still fully accepted
nested structures are not sanitized
Real risk

A malicious or buggy client can still:

inject unexpected nested audit fields
pollute downstream _split_execution_data
bypass assumptions by nesting (execution_data["meta"]["completed_by"])
Recommendation

If this is a SaaS boundary:

You need schema enforcement, not key filtering:

Pydantic model OR
explicit whitelist, not blacklist
or recursive sanitisation

Blacklist is always bypassable in evolving JSON APIs.

🟠 HIGH FINDINGS
3. ⚠️ Logging upgrade is correct but changes failure semantics

You changed:

logger.warning(...)

from silent pass

Improvement

✔ good — you now have observability

But subtle issue

You are now logging at WARNING for:

per-item hydration failures
per-item producing step failures
per-item fallback failures
Risk

At scale:

inventory endpoint becomes log-saturated
Datadog / logging backend noise spike
real alerts get buried
Recommendation

Split log levels:

debug: expected missing data
warning: truly unexpected schema corruption
error: DB/ORM failure

Right now everything is warning, which is too coarse.

4. ⚠️ MEDIUM — _normalize_dt fallback behaviour still drives silent data divergence

You now added:

if dt:
    return dt
_log.debug("ready_date_actual string did not parse")
Issue

You are now:

silently downgrading bad data to None
logging only debug
Risk

In production:

bad data silently propagates as "no ready date"
UI inconsistencies appear without alerting system owners
Recommendation

For SaaS correctness:

emit metric counter (ready_date_parse_failures)
or escalate malformed ISO strings to warning level
5. ⚠️ HIGH — execution_step.execution_id.in_(...) still double filters org ownership

You now enforce:

ExecutionStep.execution_id.in_(org_execution_ids),
ExecutionStep.id.in_(step_ids)
Issue

This is redundant constraint duplication:

ExecutionStep already belongs to Execution
Execution already scoped to org
Risk
query planner overconstrained → worse index selection
unnecessary join elimination complexity
Recommendation

Pick ONE enforcement layer:

Best options:

ExecutionStep has org_id → fastest
OR join Execution only once, no subquery IN

Current approach is safe but not optimal.

🟡 MEDIUM FINDINGS
6. ⚠️ ready_date_display still hides failure signal
except Exception:
    logger.warning(...)
Issue

You are now suppressing all failure modes into:

warning log
empty UI field
Risk

If logic breaks:

users see missing ready dates
no API-level signal
Recommendation

Consider returning structured fallback:

ready_date_error = "parse_failed"

This matters for SaaS observability.

7. ⚠️ _strip_incoming_execution_trace_keys is not applied recursively
Risk class

If payload evolves:

{
  "execution_data": {
    "meta": {
      "completed_by_email": "fake"
    }
  }
}

Your filter does nothing.

Recommendation

Either:

recursive sanitizer
or schema validation (preferred)
8. ⚠️ Query planning still depends heavily on ORM join behavior
.options(joinedload(ExecutionStep.step))
Issue

You assume:

step is cheap
outputs are embedded JSON

But if this ever becomes:

relationship → table
or expands metadata

You silently reintroduce N+1.

Recommendation

Lock model contract:

explicitly document step.outputs is JSONB
or enforce DTO projection at repo layer
🟢 POSITIVE CHANGES (important)

These are strong improvements:

✔ N+1 fully resolved (correctly this time)
batch ExecutionStep load
map-based hydration
removed per-item DB access
✔ Logging visibility improved (major operational gain)
✔ Query scoping improved
org-level enforcement tightened
reduced accidental cross-org leakage risk
✔ Separation of concerns improved
sanitisation moved into explicit function
split logic clarified with documentation

---

## Round-2 follow-up (addressed in code)

| # | Topic | What we did |
|---|--------|----------------|
| **1** | IN subquery / plan instability | **Reverted to a single `JOIN Execution` + `Execution.org_id` + `ExecutionStep.id.in_(step_ids)`** — work is bounded by inventory `step_ids`, not by materializing all execution PKs for the org (which would not scale). |
| **2** | Blacklist “false security” + nested `meta` | **`_strip_trace_keys_recursive`**: removes `_EXECUTION_DATA_TRACE_KEYS` at **any depth** in dicts/lists (capped depth 8). Docstring notes that a **stricter Pydantic whitelist** is the long-term SaaS contract. |
| **3** | WARNING log saturation | Per-item paths (`hydrate`, `producing_step`, `ready_date_display`, `producing_step_name` fallback) back to **`logger.debug(..., exc_info=True)`** so production log sinks are not flooded. |
| **4** | `ready_date` parse / metrics | **Comment** in `output_ready_date_check` that a **`ready_date_parse_failures` metric** can be added; per-row remains DEBUG. |
| **5** | “Double filter” / join vs IN | **Single join** is the one enforcement layer for org + step id filter in this query. |
| **6–8** | UI/API signals, schema, model drift | **Recursive strip** covers nested injection; **Step** model comment locks **`outputs` as JSONB column** contract for inventory loading. API field `ready_date_error` deferred — would require FE contract. |

**Still deferred:** full **`complete_step` atomic transaction refactor** (`complete-step-transaction-refactor-plan.md`), strict **Pydantic** `execution_data` schema, **`ExecutionStep.org_id`** denormalization, **`ready_date_parse_failures` metric** wiring.