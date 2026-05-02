Here’s the security + performance review for the changes in these two files, ordered by severity and focusing only on critical/high risk.

🔴 CRITICAL (security-impacting)
1. execution-render-inputs.js — remaining DOM XSS surface via HTML attribute interpolation
Risk: XSS (medium-to-high likelihood depending on escapeHtml correctness)

You still have multiple instances like:

data-input-name="${escapeHtml(input.name)}"
data-safe-name="${safeInputName}"

and:

<input ... data-input-name="${escapeHtml(input.name)}" ...>
Why this is still risky

Even though escapeHtml() is used, this is not a safe guarantee for attribute contexts inside template literals.

If escapeHtml() is not explicitly attribute-safe (quotes, backticks, newlines), you can still get:

attribute breakouts (", ')
injection of synthetic attributes
malformed DOM leading to script execution depending on downstream handlers
Key issue:

You are mixing:

HTML string building
attribute injection
dynamic DOM parsing

That combination is the classic DOM XSS pattern surface.

✔️ Fix (important)

Replace string-based DOM construction with:

const el = document.createElement('div');
el.dataset.inputName = input.name || '';
el.dataset.safeName = safeInputName;

This removes all parsing-based injection risk.

2. execution-render-inputs.js — inline HTML label injection (label + span blocks)

Example:

<span> ${escapeHtml(String(input.quantity != null ? input.quantity : '0'))} ${escapeHtml(input.unit || '')}</span>
Risk: low → medium (context dependent)

Why:

still HTML string concatenation
still dependent on escapeHtml correctness
used in multiple UI entry points (execution flow)
Impact:

If bypass occurs here:

UI spoofing of expected quantities
misleading operator instructions
potential workflow manipulation (not just visual)
✔️ Fix:

Prefer DOM construction for labels:

span.textContent = `${qty} ${unit}`;
3. execution-modal-secondary.js — return_to sanitization is improved but still incomplete
What you fixed:

Good improvement:

/^\/core\//i.test(s)

and:

if (s.indexOf('//') === 0) return '';
Remaining issue:

You are not preventing:

⚠️ URL encoding bypasses

Examples still possible depending on server decode behavior:

/core/%2f%2fevil.com
/core//evil.com (already partially blocked but ambiguous)
/core/..%2fcore/...
Risk:
open redirect chaining
phishing via return_to parameter
session confusion in navigation flows
✔️ Fix (recommended hardening)

Use stricter parsing:

const url = new URL(rt, window.location.origin);
if (url.origin !== window.location.origin) return '';
if (!url.pathname.startsWith('/core/')) return '';
return url.pathname + url.search;

This eliminates:

encoding tricks
protocol-relative bypass attempts
path traversal ambiguity
🟠 HIGH (robustness / integrity risks)
4. execution-render-inputs.js — duplicate normalization logic still spread across system

Even after improvements, you still have:

normalizeInventoryTabType
pickDefaultInventoryTab
inline normalization inside picker logic
Risk:
inconsistent classification between:
modal
SPA
secondary execution modal
Impact:
inventory misclassification drift
UI showing wrong tabs
subtle workflow integrity issues (WIP vs final mismatches)
✔️ Fix:

Centralize:

inventory-type-utils.js

Single source of truth for:

raw_material / work_in_progress / final_product mapping
expected_inventory_type inference
5. execution-render-inputs.js — dataset usage still a trust boundary leak

Example:

data-input-name="${escapeHtml(input.name)}"
data-step-unit="${escapeHtml(input.unit || '')}"
Risk:

Dataset is being used as:

state carrier
implicit backend truth substitute
Problem:
any DOM mutation or extension script can alter dataset
no integrity guarantee
Impact:
inventory mismatch bugs
potential bypass of expected inventory constraints
✔️ Fix:

Treat dataset as:

UI hint only, never authoritative state

Ensure backend re-validates:

expected_inventory_type
source_output_id
quantities
6. execution-modal-secondary.js — DOM label composition risk

Example:

triggerLabel.textContent =
  (inv.process_name ? inv.process_name + ' - ' : '') +
  inv.name + ' - ' + inv.quantity + ' ' + inv.unit;
Risk: low but real injection surface if any upstream field escapes escaping rules elsewhere

You are safe because this is textContent, but:

inconsistent use vs other areas (string concatenation patterns elsewhere)
introduces accidental future regressions (someone may switch to innerHTML)
✔️ Recommendation:

Good pattern but standardize:

triggerLabel.textContent = formatInventoryLabel(inv);
🟡 MEDIUM (performance / architectural risk)
7. execution-render-inputs.js — repeated string filtering on large inventory

Still present:

allInventory.filter(...)

inside picker rendering logic

Risk:
O(n²) behavior under frequent re-renders
UI lag with large inventories (500–5000+ items)
✔️ Fix:

Precompute indices:

Map(name → inventory[])
Map(type → inventory[])
memoized normalized names
8. repeated normalization functions inside closures

Example:

function normalizeExpectedInventoryTabHint(i) { ... }
function safeName(inv) { ... }
Risk:
repeated function allocation
inconsistent logic across modules
✔️ Fix:

Hoist to shared module scope

🟢 SUMMARY (what actually matters)
🚨 Must fix (security integrity)
Replace string-based DOM construction with DOM APIs in execution-render-inputs
Strengthen return_to using new URL() validation
Remove reliance on escapeHtml for attribute injection contexts
⚠️ Should fix (robustness)
Centralize inventory type normalization logic
Treat dataset as non-authoritative state only
🟡 Improve (performance)
Pre-index inventory instead of repeated filtering
Hoist normalization utilities