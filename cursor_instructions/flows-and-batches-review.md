🔴 CRITICAL
1. ⚠️ Recursive sanitisation is correct directionally, but still not a true security boundary
What you implemented
def _strip_trace_keys_recursive(obj: Any, depth: int = 0)

✔ Handles nested dict/list
✔ Depth guard prevents pathological recursion
✔ Eliminates previous bypass vector (nested trace keys)

Remaining issue (important nuance)

This is still blacklist-based sanitisation.

That means:

unknown keys still pass through
structure is still unbounded
types are still unconstrained
Real risk class

Not spoofing anymore — now it’s:

data contract drift + injection into downstream logic

Examples:

extremely large nested payloads → memory pressure
unexpected structures → break assumptions in _split_execution_data
subtle poisoning of analytics/audit layers
Recommendation (next step, not optional long-term)

You’ve reached the limit of what sanitisation can safely do.

Move to:

schema validation (Pydantic or equivalent) at the boundary
or at minimum:
max payload size enforcement
key count / nesting limits

Right now:

secure enough for internal APIs, not fully hardened SaaS boundary.

🟠 HIGH
2. Query strategy: reverting to JOIN is the correct trade-off (good call)

You moved back to:

.join(Execution, ExecutionStep.execution_id == Execution.id)
.filter(Execution.org_id == org_id)
This is the right choice 👍

Why:

avoids subquery planner ambiguity
enables index usage on Execution.org_id
bounded by step_ids (critical constraint)
Remaining nuance

You still rely on planner doing:

ExecutionStep.id IN (...) → index lookup first

If step_ids grows large (e.g. 1k+):

planner may switch to hash strategy
join cost increases
Recommendation (future scale guard)

If inventory grows large:

chunk step_ids (e.g. 500–1000)
or paginate inventory earlier

Not urgent, but worth noting.

3. ⚠️ Logging is now correctly downgraded — but you’ve removed signal entirely

You moved everything to:

logger.debug(...)
This fixes

✔ log spam
✔ noisy alerting

But introduces a new blind spot

Now:

all hydration failures are invisible in production unless debug logging enabled
Risk
silent degradation returns
especially dangerous for:
ready_date_display
producing_step resolution
Recommendation (balanced approach)

Keep debug logs, but add cheap aggregate signal:

counter metric:
inventory_hydration_failures
ready_date_compute_failures

This gives:

zero log noise
full observability
🟡 MEDIUM
4. Depth limiter is good — but not symmetric with payload size
if depth > _MAX_EXECUTION_DATA_STRIP_DEPTH:
    return obj
Issue

You cap depth, but:

do not cap breadth
do not cap total size
Risk

Client can send:

massive wide objects (e.g. 10k keys at depth 1)
large lists
Impact
CPU cost during recursion
memory overhead
JSON serialization cost later
Recommendation

Add one of:

max key count per dict
max list length
or global payload size guard (preferred)
5. Ready date parsing: now well-behaved but still silent failure mode
_log.debug("ready_date_actual string did not parse")
Current behaviour
invalid string → ignored → fallback path
only visible in debug logs
Risk
data inconsistency across tenants
hard-to-debug UI discrepancies
Recommendation

You already hinted at it:

ready_date_parse_failures metric

Do that. That’s the correct SaaS-grade solution.

6. Minor: redundant if dt: check pattern
dt = _normalize_dt(...)
if dt:
    return dt

If _normalize_dt guarantees:

None | datetime

Then this is fine.

If not:

falsy datetime edge cases (unlikely but sloppy contract)

Not critical, just tighten contract if possible.

🟢 WHAT IS NOW SOLID

This is worth calling out clearly.

✔ N+1 class issues: resolved properly
batched ExecutionStep loading
no hidden ORM re-fetches
no ready-date per-item query
✔ Query shape: now stable and predictable
JOIN-based org scoping
bounded by step_ids
✔ Logging discipline improved
no more warning spam
intentional debug-only for hot paths
✔ Security posture improved meaningfully
recursive stripping closes obvious bypass
trust boundary now explicit in code
🧾 FINAL VERDICT

You’ve moved this code to:

“Production-ready for typical SaaS load, with controlled and understood edge risks”

Remaining real risks (in order)
🔴 Must address (next phase)
Replace blacklist sanitisation with schema validation (or enforce payload constraints)
🟠 Should address
Add metrics for silent failures (hydration + ready-date parsing)
Consider payload size / breadth limits
🟡 Nice-to-have
Chunk large step_ids if inventory scales significantly
Tighten _normalize_dt contract
Bottom line

You’re no longer dealing with:

query explosions
silent data corruption
obvious security gaps

Now you’re in:

“mature system concerns: observability, contracts, and scale predictability”

That’s exactly where you want to be for a production SaaS backend.

---

## Round-3 acknowledgment (document state)

| Priority | Item | Status |
|----------|------|--------|
| **Must** | Pydantic + size at `complete_step` | **Done** — `CompleteStepRequestBody` (`extra="forbid"`), raw body **768 KiB** cap, `validate_json_blob` (depth/keys/list/string), tests in `tests/test_complete_step_payload.py`. |
| **Should** | Counters | **Done** — `app/core/utils/internal_counters.py`; increments for `inventory_hydration_failures`, `inventory_producing_step_failures`, `inventory_producing_step_name_fallback_failures`, `ready_date_compute_failures`, `ready_date_parse_failures`, `execution_data_strip_breadth_truncated`; exposed on **`GET /api/core/metrics`** as `operational_counters`. |
| **Should** | Payload breadth | **Done** — shared limits in `complete_step_payload.py`; defensive truncation in `_strip_trace_keys_recursive` + counter. |
| **Nice** | Chunk large `step_ids` | **Deferred** |
| **Nice** | `_normalize_dt` contract | **Deferred** |

**Still separate initiative:** `complete-step-transaction-refactor-plan.md` (atomic `complete_step` transaction).

**Frontend fix:** `execution-step-spa.js` now sends `actual_inputs`, `actual_outputs`, `execution_data` (was incorrect keys).