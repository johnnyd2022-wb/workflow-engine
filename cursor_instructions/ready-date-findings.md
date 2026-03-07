⭐ Domain Model Design Feedback (Most Important Section)
🔴 Potential Logical Inconsistency — Ready Date Semantics

Right now you have three representations:

Backend check computes readiness as:
if now >= ready_dt:
    continue

Meaning:
👉 Item is not flagged once ready date is reached.

Frontend messaging sometimes says:

cannot be used until X

This is correct.

BUT test fixture comment says:

ready = completed_at + duration

There is slight ambiguity in:

Whether equality is allowed

Whether readiness is inclusive or exclusive

Recommendation (Very important for compliance systems)

Define invariant explicitly:

👉 Product is usable when:

current_time >= ready_time

You already implement this in code.

Add this as domain documentation.

Do not change logic.

Just lock the definition.

⭐ Backend Code Issues
🟠 1. Potential Performance Risk — Inventory Lookup Pattern

This part is expensive:

inventory_items = session.query(InventoryItem)...

Then:

Build map

Iterate execution steps

Cross match

Worst case complexity:

O(execution_steps × inventory_items)
Suggestion (if dataset grows)

Add database-level filtering:

Instead of:

load all inventory items then map in memory

Do:

JOIN inventory → execution_step → step_output config

This will matter if org size grows.

Right now acceptable.

But worth planning.

🟠 2. UUID Deduplication Logic

You have:

seen_item_ids: set[UUID]

Good.

But deduplication happens after candidate selection.

Minor inefficiency but fine.

🟠 3. Normalization Functions

These are good but slightly fragmented:

You have:

_normalize_dt

_normalize

repeated strip/lower patterns

If you evolve this system, consider:

domain_value_object layer

Not urgent.

⭐ Frontend Code Issues
🔴 UI Copy Consistency Problem (Most Important UX Issue)

You use multiple phrasings:

Examples:

"Output cannot be consumed..."

"Product not yet ready"

"Not ready"

"Nearing ready"

"Cannot be used until..."

This will hurt platform polish.

⭐ You should standardize messaging template.

Recommend format:

⚠️ Ready from: <date>
Status: <state label>
Detail: <explanation>

Where state label is one of:

Not ready

Nearing ready

Ready

🟠 Execution Ready Date Input Validation

This is slightly weak:

if (!payload || !payload.date)

You should also validate:

ISO parseability

Future/past policy (if you ever add it)

⭐ Modal Confirmation Pattern

This is good:

system finding → user confirmation → execution allowed

You are implementing:

Defensive workflow continuation control

Nice.

⭐ Minor Technical Improvements (Low Risk)
1. Remove Magic Strings

You repeat:

custom_ready_date

and

output_ready_date

Consider constants.

2. Logging Strategy

Backend check currently has no diagnostic logging.

If this becomes compliance critical:

Add:

org_id
execution_id (if available)
count_flagged_items

at debug level.

3. Timezone Handling

You are correctly forcing UTC.

Keep it.

Do not change unless localisation is required.

I would add ONE more concept:

⬆️ Readiness State Machine

Instead of:

compute → check → message

I would model:

PENDING_READY
NEAR_READY
READY
EXPIRED_READY (if rule ever reverses)

You are 80% there already.

This is future-proofing.