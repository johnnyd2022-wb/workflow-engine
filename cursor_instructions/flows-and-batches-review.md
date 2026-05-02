Below is a security + performance + correctness review of:

app/core/frontend/processes/flows2.html

I’m treating this as a high-risk frontend execution + rendering module (it handles inventory rendering, dynamic HTML injection, and user-facing data transformation).

🔴 CRITICAL FINDINGS (Fix immediately)
1. DOM XSS risk via innerHTML construction (HIGH → CRITICAL)
Location

Multiple places, but most severe:

createInventoryItemCardFlows
buildFlows2InventoryDetailsSection
flows2RenderInventoryAuditSection
flows2RenderInventoryInputsSection
flows2RenderInventoryUpstreamSection
Problem

You are heavily using:

card.innerHTML = `...`

and constructing large HTML strings from:

API data (item, extra_data, execution_trace)
nested objects (execution_prompts, system_findings, etc.)

Even though you use escapeHtml(...) in many places, there are multiple structural gaps:

❌ Dangerous patterns
1. Unescaped object serialization
flows2SerializeForDisplay(val)

Used in:

execution_prompts
completed_by
execution_trace
step.execution_errors / warnings

If any upstream source injects HTML-like strings, they propagate into innerHTML.

2. Partial escaping inconsistencies

Example:

display = flows2SerializeForDisplay(raw);
return `<span>${escapeHtml(display)}</span>`;

BUT earlier:

if (typeof raw === 'object') display = flows2SerializeForDisplay(raw);

→ You are trusting serialized JSON which can contain:

{"x":"</div><script>alert(1)</script>"}

Once stringified → it is no longer safely escaped in all branches.

3. Direct insertion of user-controlled labels
<span class="execution-id">${escapeHtml(item.name)}</span>

Good, BUT:

item.name is not validated elsewhere
could still be null injection vector if escapeHtml is bypassed or incomplete
Impact
Full stored + reflected XSS
Execution in admin / operator dashboards
Potential token/session theft
Inventory manipulation via DOM injection
Fix (required)

Rule: NEVER use innerHTML with concatenated data objects.

Replace with:

DOM APIs (createElement, textContent)
OR a strict HTML builder with guaranteed escaping

At minimum:

function safeText(el, text) {
  el.textContent = text ?? '';
}

And eliminate:

card.innerHTML = `...`
2. Click handler injection via inline onclick (HIGH)
Location
onclick="toggleInventoryItemDetailsFlows('${item.id}')"
Problem
item.id is not sanitized for attribute context
allows quote-breaking injection in worst case
inline JS is CSP-hostile
Impact
XSS vector if ID is ever attacker-controlled or UUID spoofed
Fix

Replace with:

card.addEventListener('click', () => toggleInventoryItemDetailsFlows(item.id));
3. Unsafe object inspection → prototype pollution exposure (HIGH)
Location
Object.keys(vOut).forEach(...)
Object.keys(entry)
Object.entries(prompts)
Problem

You directly iterate object keys from API payloads without:

hasOwnProperty (sometimes used, but inconsistent)
prototype-safe guard
schema validation

If backend is compromised or polluted:

__proto__
constructor
prototype

could be traversed into UI logic.

Fix

Add global safe iterator:

const safeKeys = (obj) =>
  Object.keys(obj).filter(k => Object.prototype.hasOwnProperty.call(obj, k));

And replace all raw Object.keys(...).

4. Unbounded rendering of nested arrays (performance + DoS risk) (HIGH)
Locations
flows2FormatAuditHistoryEntries(history)
flows2RenderInventoryUpstreamSection
flows2RenderInventorySystemFindingsSection
Problem

No limits on:

history entries
prevSteps
reconciliation_history
prompts

A malicious or buggy backend can send:

history: Array(50,000)

→ causes:

DOM explosion
blocking UI thread
memory spikes
Fix

Add caps everywhere:

const MAX_ITEMS = 50;
history.slice(0, MAX_ITEMS)

Also consider virtualization for lists.

5. Regex-based UUID filtering is unsafe/fragile (MED-HIGH)
/^[0-9a-f]{8}-...$/i

Used to detect "fake operator names".

Problem
only filters UUID shape
attacker can still inject meaningful strings
false sense of safety
Fix

Do not infer identity validation in frontend.

Move identity validation to backend.

6. Global mutable state pollution (MED-HIGH)
Variables:
window.flows2InventoryFilter
let flows2InventoryItemsCache = [];
Problem:
global mutable state
race conditions if multiple panels exist
filter not scoped per process
Risk:
cross-process leakage in SPA
stale cache rendering wrong dataset
Fix:

Encapsulate in module scope or class:

class Flows2InventoryState {}
🟠 MEDIUM FINDINGS
7. Redundant recomputation in render pipeline

Each render:

re-filters full cache
re-maps entire list
rebuilds full DOM

No memoization or diffing.

Impact
O(n) full redraw every filter click
slow on large inventory sets
Fix
pre-index by inventory_type
or maintain separate arrays per filter
8. Overuse of inline styles (maintainability + CSP risk)

Example:

style="margin:0 0 12px 0;"
Issue
hard to secure with CSP strict mode
inconsistent UI theming
harder to audit
9. Data formatting functions mixing concerns

Examples:

date formatting
UI labeling
business logic in same functions

This increases attack surface because:

inconsistent escaping
inconsistent output encoding contexts
🟡 LOW / CLEAN BUT NOTEWORTHY
10. Good security practices already present

Positive signals:

escapeHtml used widely
no eval / Function() usage
no template injection from raw concatenation (mostly controlled)
separation of rendering helpers
📊 PRIORITY SUMMARY
🔴 CRITICAL (fix now)
innerHTML usage with semi-trusted serialized data → XSS risk
Inline onclick handlers with dynamic IDs
Unsafe object iteration from API payloads
🟠 HIGH
Unbounded rendering loops (DoS via large payloads)
Global state leakage (window.flows2InventoryFilter)
Weak UUID-based trust logic
🟡 MEDIUM
Performance inefficiency (full re-rendering)
Inline styling overuse
Mixed concerns in formatting utilities