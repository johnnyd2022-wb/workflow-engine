🔴 CRITICAL (must fix / high risk)
1. execution-render-inputs.js — DOM XSS surface via inventory rendering
Risk: Stored / reflected XSS (HIGH)

You are building large HTML blocks with:

escapeHtml(...) used inconsistently
direct interpolation into HTML strings:
humanDetails += section(...)
extraBits += ...
JSON.stringify(...) injected into DOM
innerHTML style construction implied (via string concatenation patterns)
Problem areas:
a) Inventory fields rendered into HTML
escapeHtml(String(inv.process_name))
escapeHtml(String(inv.source_step_name))

Good — but later you also do:

var notes = String(inv.extra_data.notes)
...
white-space: pre-line;">' + escapeHtml(notes)

Fine in isolation, BUT:

🚨 Critical issue:

You sometimes bypass escaping in nested / conditional rendering paths:

humanDetails += section(...) (unknown implementation safety)
extraJson = JSON.stringify(extraCopy, null, 2); later rendered → likely injected into DOM

If section() or downstream rendering uses innerHTML, JSON blobs become XSS vectors if attacker controls inventory metadata.

Attack surface:

Any inventory field originating from:

user input
external integrations
execution metadata
can inject script payloads.
✔️ Fix recommendation:
Ensure all HTML injection points use textContent or safe DOM APIs
Never inject raw JSON via innerHTML

Replace:

JSON.stringify(...)

rendering with:

<pre> + textContent
or DOM node construction
Audit section() function — this is likely your highest-risk choke point
2. execution-render-inputs.js — uncontrolled dataset injection into DOM attributes
Risk: Attribute injection → DOM manipulation / XSS chain

Example:

data-input-name="${escapeHtml(input.name)}"
data-input-unit="${escapeHtml(input.unit || '')}"
Problem:

escapeHtml() is NOT sufficient for HTML attributes inside double quotes when used in template literals.

If escapeHtml is not attribute-aware, you can still break context:

" injection closes attribute
allows injection of new attributes or event handlers
✔️ Fix:

Use strict attribute encoding or:

setAttribute() instead of string HTML construction

Example safer pattern:

btn.setAttribute('data-input-name', input.name || '');
3. execution-open-step.js — process inference logic trusts API data implicitly
Risk: Logic manipulation / data poisoning

This block:

var steps = processData.steps || [];
...
var explicit = out && out.inventory_type;
var inferred = explicit === 'work_in_progress' || explicit === 'final_product'
  ? explicit
  : (o >= maxOrder ? 'final_product' : 'work_in_progress');
Problem:

You are:

trusting processData.steps
trusting out.inventory_type
deriving business-critical classification from client-fetched data
Why this matters:

If CoreAPI.getProcess() is compromised or returns malformed data:

inventory classification is wrong
downstream execution decisions become inconsistent
UI + workflow desync risk
✔️ Fix:
Treat process graph as advisory only
Validate server-side again during:
execution completion
inventory classification persistence
4. execution-modal-secondary.js — open redirect + URL construction risk
Risk: Open redirect + parameter injection
window.location.href = '/core/inventory/add/manual?' + params.toString();

and:

params.set('return_to', rtw);
Problem:

return_to is derived from:

window.location.pathname + window.location.search

If attacker can manipulate URL or querystring:

they can inject arbitrary return paths
potential open redirect chaining
phishing / workflow hijack vector
✔️ Fix:

Strict allowlist:

if (!rtw.startsWith('/core/')) rtw = '/core/';

or validate against regex:

^/core/[\w/-]*$
5. execution-render-inputs.js — dynamic filtering logic DoS vector
Risk: CPU amplification / UI slowdown

Pattern:

allInventory.filter(...)
.sort(...)
.map(...)

inside repeated render cycles:

filtering by name
type filtering
execution bias sorting
repeated DOM rebuilds
Problem:

Large inventory datasets → quadratic UI slowdown:

filter + sort + DOM rebuild per keystroke
✔️ Fix:
memoize:
normalized inventory names
type classification
debounce search input rendering

pre-index inventory:

Map(name → items)
Map(type → items)
🟠 HIGH (security-adjacent / robustness)
6. dataset-based state explosion (multiple files)

You are heavily relying on:

dataset.expectedInventoryType
dataset.outputInventoryType
dataset.sourceOutputId
Risk:
client-side state tampering
inconsistent UI state vs backend truth
Fix:
treat dataset as UI hint only
always validate on API submit
7. Weak normalization logic duplicated across files

Multiple copies of:

normalizeExpectedInventoryTabHint
normalizeInventoryTabType
safeName
Risk:
divergence bugs → inconsistent classification
subtle security bypass via inconsistent parsing
Fix:

centralize normalization module

8. HTML injection via fallback string concatenation

Example:

'<div class="exec-picker-kv__v">' + escapeHtml(String(inv.process_name)) + '</div>'

Even if escaped, mixing string HTML construction increases risk surface.

Fix:

Use:

DOM API construction
or templating library with auto-escaping
🟡 MEDIUM (performance / maintainability risks)
9. Repeated full inventory scans

Multiple files:

.filter()
.map()
.sort()

per render / modal open

Fix:
index once per load
reuse immutable cache
10. repeated Map construction per render
const inventoryById = new Map();
allInventory.forEach(...)

inside render path → unnecessary allocation

11. inline style explosion

Not security-critical, but:

makes CSP hard
prevents style hashing
increases XSS impact surface if styles ever user-controlled
🟢 SUMMARY (priority actions)
🚨 Do immediately
Audit section() → likely XSS root
Replace all innerHTML construction paths in execution-render-inputs
Stop JSON.stringify injection into DOM
Fix return_to open redirect risk
Replace attribute string interpolation with setAttribute
⚠️ Next
Centralize inventory normalization logic
Add server-side validation for inventory classification
Add caching/indexing for inventory filtering