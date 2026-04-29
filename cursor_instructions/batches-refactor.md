1. execution-docoverlay.js
What it does

Full-screen iframe overlay for step documentation.

🔴 Critical / High Risk
1. No sandboxing on iframe (security risk)
iframe.src = docUrl;

There is:

no sandbox attribute
no referrerpolicy
no origin validation
Risk

If docUrl is ever attacker-controlled (even partially via stored content):

XSS via iframe escape vectors
clickjacking / data exfiltration depending on doc origin
ability to load internal routes with auth context
Fix

At minimum:

iframe.sandbox = "allow-same-origin allow-scripts";
iframe.referrerPolicy = "no-referrer";

Or stricter if possible:

iframe.sandbox = "allow-same-origin";

If docs are same-origin only → enforce it.

2. No DOM cleanup hook on navigation

Overlay removal:

overlay.parentNode.removeChild(overlay);
Risk
If user navigates away or SPA reroutes, overlay can leak into new page state
no global escape handler (ESC key, route change, etc.)
Fix

Add:

keydown Escape listener
window.popstate cleanup
optional mutation observer teardown hook
3. Z-index hardcoded (1100)

Risk:

collision with modals (you already use 1000 elsewhere)
future layering bugs (multiple overlays)
🟡 Medium Risk
4. Inline styles everywhere
prevents CSP tightening
hard to override in themes
performance: repeated style parsing
🟢 Low Risk
Simple lifecycle
no async logic
no shared state
2. execution-modal-secondary.js

This is your highest risk file in the system. It mixes:

UI state mutation
API calls
DOM rebuilding
global state (window.*)
event binding
inventory reconciliation logic
🔴 Critical Issues
1. Global mutable state explosion
window.addInventoryContext
window.untrackedOutputContext
window.openAddInventoryModalForMissingInput
window.openAddUntrackedOutputModal
window.refreshExecutionModalInventory
Risk
race conditions between multiple open modals
stale context overwrites
hard-to-debug cross-page leakage
Example failure mode:
user opens modal A
opens modal B
context gets overwritten
inventory refresh applies to wrong execution
2. Race condition in refreshExecutionModalInventory

This function:

fetches inventory async
mutates DOM
depends on window.addInventoryContext
Problem:

No versioning or tokening:

var ctx = window.addInventoryContext;

If another update happens mid-flight:

stale render overwrites newer selection state
Fix pattern:

Introduce:

const renderToken = Symbol()

or execution-scoped version id.

3. DOM traversal fragility (high break risk)

Examples:

var section = hiddenInput.closest('.execute-input-section');
var cardsContainer = section.querySelector(...)
Risk:
UI refactor breaks logic silently
no defensive guards
nested null access not protected consistently
4. innerHTML injection surfaces
card.innerHTML = '<div ...>' + escapeHtml(...) + ...
Risk:

You partially escape, but:

mixed escaped/unescaped concatenation
subtitleLine built from join after escape
detailsParts partially escaped
This is a classic DOM XSS risk area.

Even if currently safe:

future dev may insert raw values
very easy regression
Fix:

Use:

document.createElement
or strict templating helper
5. Event handler memory leaks

You attach:

form.addEventListener('submit', async function(e) { ... })

inside install scope but never:

remove listeners on teardown
prevent duplicate binding on re-init
6. Hard-coded unit logic (business coupling)
var allowedUnits = ['kg', 'g', 'L', 'mL', 'pcs', 'units'];
Risk:
schema drift vs backend
UI becomes source of truth incorrectly
🟡 Medium Issues
7. Mixed responsibilities (SRP violation)

This file:

opens modals
submits forms
fetches API
renders DOM
performs reconciliation logic

This will become unmaintainable as system grows.

8. Missing concurrency guards in submit flow
await CoreAPI.createInventoryItem(payload);

No:

double-submit protection
loading lock
retry handling
🟢 Lower Risk
Good validation around UUIDs
Reasonable defensive checks
No obvious direct injection vectors (currently)
3. execution-open-step.js

This is your core orchestration layer.

🔴 Critical Issues
1. Massive sequential async chain (performance bottleneck)
await Promise.all([
  CoreAPI.getInventory(),
  CoreAPI.getExpiredMaterials(),
  CoreAPI.getUntrackedItems(),
  docsPromise,
  loadOrgUsersMap()
]);

Good parallelism — BUT:

Hidden issue:
subsequent renders depend on full dataset
no partial streaming
UI blocks until all complete
2. Race condition: render invalidation missing

You do NOT consistently guard stale execution:

Example:

var isDraft = executionId == null

But no:

request token
cancellation mechanism
abort controller
Risk:

User navigates quickly between steps:

old execution renders over new one
3. DOM mutation tightly coupled to data fetch
window.ExecutionRenderInputs.renderVariableInventoryInputs(...)
Risk:
renderer assumes full valid data
no fallback handling
no defensive schema validation
4. Over-reliance on modal.dataset
modal.dataset.executionId = executionId || '';
Risk:
string coercion issues
cross-module mutation conflicts
silent stale state bugs
5. Hidden coupling via globals
SessionAPI.get(modal)
window.ExecutionRenderDocs
window.ExecutionRenderInputs
window.ExecutionRenderOutputs
Risk:
load-order dependency fragility
impossible to statically reason about system
breaks easily under bundling/minification changes
🟡 Medium Issues
6. No abort support on CoreAPI calls

All requests:

cannot be cancelled
may resolve after user leaves screen
7. Mixed orchestration + business logic

This file now owns:

inventory filtering logic
expired material rules
execution state logic

This is drifting into backend responsibility.

🟢 Positive
Good parallel fetch strategy
Clear decomposition into renderer modules
Reasonable separation vs earlier monolith
4. batch-start.css
🔴 High Risk
1. Heavy reliance on !important

This appears throughout:

display: block !important;
padding: 0 !important;
border: none !important;
Risk
CSS specificity war escalation
impossible safe refactoring later
overrides become accidental coupling layer
2. Layout override of modal into SPA mode
#execute-step-modal {
  display: block !important;
  position: static !important;
}
Risk:

You are effectively:

hijacking modal component into page component
breaking semantic separation

This will cause:

future modal reuse issues
z-index / scroll locking bugs
🟡 Medium Risk
3. Layout logic encoded in CSS

Example:

section spacing
divider rules
“wizard feel” semantics
Risk:

Business UI logic lives in CSS → hard to evolve safely.

🟢 Low Risk
Good use of CSS variables
Reasonable typography system
No obvious performance issues
5. execution-modal.css (partial)
Observation-level risks
shared styling between modal + SPA
unclear boundary ownership
increasing likelihood of style collisions with batch-start.css overrides
6. core-api.js
🔴 Critical
1. API abstraction hides query semantics
return this.request(`/executions/${encodeURIComponent(executionId)}/with-process?minimal=1`);
Risk
frontend assumes minimal=1 shape
backend changes silently break UI
2. No retry/backoff handling

All calls:

fire once
fail hard
no circuit breaking
🟡 Medium
No request cancellation support
No caching layer (leads to duplicate inventory fetches)
7. HTML Templates (batch-start.html, flows2.html, core2.html)
🔴 Critical architectural risk
1. Script duplication across pages

All three include:

same execution modules
same global dependencies
Risk:
double-binding events
duplicate initialization
race conditions between scripts loaded twice in SPA contexts
2. Load order dependency fragility

Example:

execution-render-docs.js
execution-render-inputs.js
execution-modal.js
Risk:
any reordering breaks runtime silently
no module system enforcement
3. Multiple entry points for same system

You effectively have:

modal entry (flows2)
page entry (batch-start)
hybrid entry (core2)
Risk:
divergent runtime behavior
inconsistent state assumptions
8. Overall System-Level Findings
🔴 Critical systemic issues
1. Global namespace architecture

Everything depends on:

window.* modules
shared mutable state

→ This guarantees future race conditions

2. No execution context isolation

Multiple executions can:

overwrite each other
share modal state
corrupt inventory selection state
3. No request cancellation strategy

Across the system:

no AbortController usage
no render invalidation pattern consistency
4. DOM-driven state model

Instead of:

state → UI

You have:

DOM → state → DOM → state

This creates:

race conditions
subtle desync bugs
hard-to-reproduce UI corruption

1) execution-render-docs.js
Purpose

Renders step-level documentation inside the execution UI, supporting:

Inline markdown rendering
Remote document preview (PDF/images via iframe/img)
Download + open actions
Optional fullscreen overlay hook
Strengths
1. Clean separation of concerns
Pure render module (ExecutionRenderDocs)
No modal/state mutation logic
Correct dependency inversion via CoreAPI + optional globals
2. Safe markdown handling (partial)
escapeInlineMarkdownContent()
Prevents HTML injection
Preserves formatting via <br>
3. Good progressive enhancement model
Inline markdown → fallback to storage-backed documents
Handles:
images
PDFs (iframe)
generic docs
4. Mobile-aware behavior
isNarrowOrTouch && isPdf
Uses fullscreen overlay instead of iframe UX on mobile
Issues / Risks
1. Inline HTML injection risk (summary section)
summary.innerHTML = 'View inline...'
Minor but unnecessary HTML injection surface
Should be textContent + separate hint node
2. Iframe rendering is unbounded trust
iframe.src = viewUrl;
Assumes viewUrl is safe
No sandboxing (sandbox attribute missing)
No CSP enforcement here
3. Redundant CoreAPI retrieval pattern
var coreApi = root.CoreAPI || window.CoreAPI;
Repeated pattern across modules → should be centralized adapter
4. Styling embedded in JS

Heavy inline styles:

reduces theming consistency
hard to override in design system
Architectural Notes
This module is effectively a document viewer renderer
Could be evolved into:
DocumentRendererService
with pluggable renderers per MIME type
Suggested Improvements
Add renderer map:
image/pdf/html/text
Introduce sandboxed iframe:
sandbox="allow-same-origin allow-scripts"
Move styles → CSS classes
Replace innerHTML summary usage
2) execution-render-prompts.js
Purpose

Renders execution input prompts for a step, including:

Text / number / date / select inputs
Evidence upload system (files + backend reconciliation)
Draft-pending evidence staging
Per-step evidence state hydration
Strengths
1. Strong feature completeness (high complexity module)

Handles:

API hydration (listEvidence)
config fetch (getEvidenceConfig)
file staging (pre-execution persistence)
validation hooks
dynamic UI rendering per prompt type

This is a full mini workflow engine UI layer

2. Good separation of evidence lifecycle

Distinct states:

persisted evidence
pending client evidence
merged view per step
ses.pendingEvidenceFilesByStepId
ses.evidenceByStepId

This is a solid session-scoped state model.

3. Defensive API usage
guards around CoreAPI presence
try/catch on all async calls
4. UX-aware design
file size validation
inline error container
immediate list updates
remove actions for both pending + persisted
Issues / Risks
1. Large function complexity (high cognitive load)

renderExecutionPrompts does everything:

API calls
state mutation
DOM building
event binding
validation logic

➡️ This is a candidate for decomposition

Suggested split:

renderPromptField()
renderEvidenceUploader()
hydrateEvidenceState()
2. State stored on ses without schema
ses.evidenceByStepId = new Map();

Risk:

implicit global session mutation
hard-to-debug lifecycle bugs
3. Potential race condition

Async sequence:

await CoreAPI.listEvidence()

No cancellation or stale response protection if:

modal re-renders
step changes quickly
4. DOM event handler accumulation risk

Each render attaches:

fileInput listener
listEl click listener

If re-rendered without cleanup → duplicates possible.

5. Mixed responsibility: UI + API + validation

Evidence upload:

UI rendering
validation (size limits)
API interaction
state reconciliation

This should be split into:

EvidenceService
EvidenceUI
Architectural Notes

This is effectively:

a form runtime engine + attachment system + step input renderer

It’s approaching “mini platform module” complexity.

Suggested Improvements
Introduce:
EvidenceController
EvidenceRenderer
EvidenceStateStore
Add event delegation root instead of per-element listeners
Extract validation constants:
MAX_EVIDENCE_BYTES
Consider optimistic UI model for uploads
3) execution-render-outputs.js
Purpose

Renders:

variable outputs for a step
reconciliation with untracked inventory/items
expiry rules
readiness date constraints
complex selection UI for matching inventory records
Strengths
1. Strong domain modelling (inventory reconciliation UI)

This is not generic UI — it models:

production outputs
untracked inventory matching
reconciliation workflows

Good abstraction of:

backend matching API
UI selection state
2. API-aware matching logic
CoreAPI.getMatchingUntracked(...)

Supports:

backend-authoritative matching
fallback client filtering
3. Rich UX for reconciliation

Includes:

dropdown card selector
expandable details
quantity overrides
metadata display
step provenance traceability

This is enterprise-grade trace UI

4. Validation layering (expiry vs ready date)

Complex logic:

duration-based expiry
datetime expiry
warning constraints
cross-field validation (expiry vs ready date)
Issues / Risks
1. Extremely high complexity function

renderVariableOutputs is:

API layer
domain logic
UI rendering
validation engine
interaction controller

➡️ This is too many responsibilities in one closure

2. Deep DOM coupling

Selectors like:

.querySelector('.execute-output-expiry-input-mode')

Risk:

brittle DOM coupling
hard to refactor UI markup
3. Inline string-heavy HTML construction

Large template strings:

hard to maintain
no component reuse
no escaping consistency guarantee
4. Hidden dependency on globals
window.ExpiryReadyDateValidation
window.CustomExpiryValidation

Risk:

implicit runtime coupling
order-of-load fragility
5. Mixed reconciliation logic (frontend + backend semantics)

Matching logic:

duplicates backend rules
but also local filtering fallback

Risk:

divergence between client/server truth
Architectural Notes

This module is essentially:

a domain-specific reconciliation engine UI for production outputs

It is not just rendering — it encodes business rules.

Suggested Improvements
1. Split into layers

Renderer

builds UI

Reconciliation engine

matching logic
selection state

Validation engine

expiry + readiness constraints
2. Replace inline HTML with builder functions

Example:

renderUntrackedCard(item)
renderOutputSection(output)
3. Centralize validation

Move:

expiry validation
ready date validation

into:

OutputValidationService
4. Introduce state model

Instead of DOM-derived truth:

{
  selectedUntrackedId,
  quantityOverride,
  expiryMode,
  readyDate
}
Cross-file observations (important)
1. All three modules share a pattern:

They are:

“Render + business logic + DOM + API hybrid modules”

This leads to:

tight coupling
high cognitive load
difficult testing
2. Common improvement opportunity

Introduce a shared architecture:

Suggested structure
Renderers/
docs
prompts
outputs
Services/
EvidenceService
OutputReconciliationService
DocumentService
State/
ExecutionSessionStore
Utils/
escapeHtml
formatting helpers
3. Key technical risk across all three

Event + render duplication risk

None of the modules explicitly:

teardown listeners
guard against re-render duplication

1) execution-session.js
Purpose / Responsibility

A UI session state container for execution-step flows. It centralises ephemeral, client-side state such as:

input editing state
inventory picker state
evidence staging (pending uploads + cached evidence per step)

It deliberately avoids identity/business logic and only manages in-memory maps tied to a DOM root element.

Strengths
Correct use of WeakMap
Prevents memory leaks by tying session lifetime to DOM lifecycle.
Clear separation of concerns
No API calls, no rendering, no persistence logic.
Simple lifecycle model
get() lazily initialises session
resetForOpen() provides explicit reset boundary
Weaknesses / Risks
1. Silent coupling via shared structure

The session object shape is implicitly relied upon elsewhere:

pendingEvidenceFilesByStepId
evidenceByStepId
inputStateByKey

There is no schema enforcement or guardrails.

➡️ Risk: accidental breakage if any module mutates structure incorrectly.

2. Overloaded session responsibility (early growth smell)

Even though small, it already mixes:

inventory UI state
evidence upload staging
input state tracking

This will likely expand into a “god session object” if not constrained.

3. No lifecycle observability

No hooks for:

debug tracing
session inspection
cleanup verification

This makes production debugging harder in complex flows.

Suggested Improvements
Define a session schema constant
Consider splitting into:
inventorySession
evidenceSession
inputSession
Add optional debug flag:
session snapshot logging
Document ownership boundaries explicitly
2) execution-shared-utils.js
Purpose / Responsibility

A pure utility module for execution UI logic:

user mapping (/org/users)
label formatting
unit conversion logic

This is a classic “shared helpers” layer.

Strengths
1. Good caching strategy
__OrgUsersMap cached globally
avoids repeated API calls
2. Functional purity (mostly)
prettyLabel and convertUnit are deterministic
no DOM dependencies
3. Reasonable unit conversion model

Supports:

mass
volume
length

Clear separation of conversion domains.

Weaknesses / Risks
1. Global namespace pollution
Uses globalThis.__OrgUsersMap

➡️ Risk: collision with unrelated modules in larger frontend.

2. Silent failure on API fetch
catch (e) {
  g.__OrgUsersMap = new Map();
  return g.__OrgUsersMap;
}
No logging
No fallback signalling

➡️ Debugging blind spot in production.

3. Unit conversion is fragile scaling-wise

Current model:

hardcoded factors
no extensibility layer

Risks:

cannot support domain-specific units (e.g. chemical concentrations, brewery-specific measures)
no validation for incompatible conversions beyond silent fallback
4. Inconsistent API semantics
convertUnit returns input unchanged on mismatch
but no explicit “conversion failed” signal

This leads to silent correctness risk.

Suggested Improvements
Replace global cache with module-scoped singleton
Add structured logging on failure
Introduce:
conversionSupported(from, to)
explicit error return option
Consider externalising unit system to config (future-proofing)
3) execution-submit.js
Purpose / Responsibility

This is the core orchestration layer for completing a step execution, including:

validation
evidence upload
inventory checks
output reconciliation
API submission (completeStep)
UI teardown + notifications

This is the highest complexity module in the set.

Strengths
1. End-to-end orchestration is well structured

Clear phases:

execution bootstrap
validation (inputs, prompts, evidence)
evidence upload
output validation (expiry + readiness rules)
payload construction
API submission
UI cleanup

This is logically sound sequencing.

2. Good defensive API usage
multiple fallback paths for CoreAPI availability
handles missing draft execution state
tolerates partial session state
3. Strong validation coverage

Covers:

input quantities
inventory bounds
required prompts
evidence requirements
output expiry rules
ready-date constraints
override flows

This is enterprise-grade validation breadth.

Weaknesses / Risks
1. Very high cyclomatic complexity

This file is doing too much:

orchestration
validation rules
API coordination
UI manipulation
business rules enforcement

➡️ This is effectively a mini backend controller in the frontend

2. Hidden coupling to DOM structure

Relies heavily on:

.execute-input-row
.execute-output-quantity-input
.execute-reconcile-untracked-value
.execute-prompt-input

➡️ Any UI change risks breaking submission silently.

3. Evidence upload is tightly embedded in submission flow

This creates:

long blocking async chain
mixed responsibilities (upload + validation + submission)

Risk:

partial failure states are hard to recover from cleanly
4. Business logic embedded in UI layer

Examples:

unit conversion validation against inventory
ready-date constraints
expiry rules validation
reconciliation rules

➡️ This is domain logic leakage into UI orchestration

5. Error handling is inconsistent
Some errors throw
others return silently
others notify user

No unified error strategy.

6. Potential race-condition sensitivity

Evidence upload + execution creation is sequential and blocking:

could lead to partial execution creation before validation fails later
Suggested Improvements
Structural refactor (high impact)

Split into services:

execution-validator.js
execution-payload-builder.js
execution-evidence-service.js
execution-orchestrator.js (thin controller)
Introduce execution pipeline pattern

Instead of inline flow:

validate()
hydrateExecution()
uploadEvidence()
buildPayload()
submit()
Centralise validation rules

Right now rules are duplicated across:

inputs
outputs
expiry validation
ready-date validation
Improve failure consistency

Adopt one of:

exception-based flow
result object pattern { ok, error }
Cross-file observations (important)
1. Architecture pattern: “UI-driven domain logic”

Across all three:

session state
validation rules
conversion logic
reconciliation logic

➡️ All drift toward frontend-as-domain-engine

This is maintainable at medium scale but becomes fragile as:

rules grow
multiple UIs (modal + page) diverge
backend parity is required
2. Strong implicit contract coupling
DOM structure = data model
class names = business semantics
dataset attributes = state persistence

This is fast to build but:
➡️ expensive to refactor safely later

3. Good modular intent, incomplete separation

You’ve done the right kind of splitting:

session
utils
render
submit

But:

submit still contains orchestration + domain rules + UI concerns
4. Biggest systemic risk

The highest-risk area is not bugs—it’s:

rule duplication across UI + backend + future features


execution-render-inputs.js
1) Correctness / hidden bugs
⚠️ safeInputName is a silent dependency

You use:

'execute-inv-arrow-' + safeInputName + '-' + id

and similarly for details IDs.

If safeInputName is not guaranteed in scope, this will:

break selectors (querySelector returns null)
make toggleInventoryCardDetails silently fail

Fix: pass it explicitly into createCardForInv or close over it.

⚠️ firstRow fallback is unsafe
setRowSelection(ses.editingInputRow || firstRow, id);

If:

ses.editingInputRow is null AND
firstRow is undefined

→ this silently breaks selection.

Better:

const targetRow = ses.editingInputRow || firstRow;
if (!targetRow) return;
⚠️ filterAddAnotherDropdown() DOM mutation loop logic is fragile

You do two full loops over children:

first pass: hides/shows cards
second pass: controls headers

But header visibility depends on scanning forward every time:

for (var j = i + 1; j < children.length; j++)

This is O(n²) per filter keystroke.

⚠️ dataset.searchText may be undefined-safe but inconsistent

You set:

card.dataset.searchText = (searchParts.join(' ') || '').toLowerCase();

But later:

var text = (el.dataset.searchText || '');

If any non-card element is accidentally included in filtering loop, behavior becomes inconsistent.

⚠️ style.display used as state source

You rely on:

next.style.display !== 'none'

This is brittle because:

computed style vs inline style mismatch
external CSS could override visibility

Better: use a class like .is-hidden.

2) Performance concerns
🔥 Repeated DOM queries in tight loops

In filterAddAnotherDropdown:

cardsContainer.children loop twice
repeated .classList.contains
repeated .dataset

This runs on every keystroke.

Fix direction:

cache cardsContainer.children into array once per call
maintain separate cards and headers arrays
🔥 Full reflow risk on every input

Each filter triggers:

style changes on many nodes
header recomputation scanning DOM repeatedly

For large inventories (100+ items), this will lag.

🔥 innerHTML heavy rebuild in createCardForInv

This is fine for occasional use, but:

you mix string concatenation + DOM events
makes future diffing impossible

If this grows, consider:

document.createElement per node
or template cloning
3) Architecture / maintainability issues
🧠 Mixed responsibilities in one function

createCardForInv is doing:

data formatting
DOM creation
event binding
business logic (expired reason, prompts rendering)

This should be split:

buildInventoryCardData(inv)
renderInventoryCard(data)
attachInventoryCardEvents(card, inv)
🧠 Global state coupling (ses, inputSection, rowsContainer)

This module implicitly depends on:

ses.editingInputRow
inputSection
rowsContainer
pickerState

That makes it:

hard to reuse
hard to test
fragile under re-entrancy
🧠 Event binding duplication risk

You do:

newRow.addEventListener('click', function() { setActiveRow(newRow); });

But if createInputRow already binds selection events (comment suggests it does), you risk double-binding or inconsistent activation paths.

🧠 Toggle logic tied to inline styles
details.style.display = isExpanded ? 'none' : 'block';

Better:

toggle class .is-expanded
let CSS handle layout/animation

This avoids inline style fighting CSS.

4) Small but important improvements
Use early returns consistently

Example:

function toggleInventoryCardDetails(cardId) {

Good candidate for:

if (!details || !arrow) return;

already done 👍 but keep pattern consistent everywhere.

Avoid repeated querySelector on same parent

Inside loops:

inputSection.querySelector(...)

Cache once per function.

Escape safety is partial

You use escapeHtml correctly for text nodes, but:

dataset.searchText is derived from raw fields (ok)
but innerHTML concatenation is still present everywhere

If any field bypasses escape (future dev change), you’ll get XSS surface.

5) If I were tightening this up

Priority order:

Replace style.display state tracking → class-based visibility
Remove O(n²) header filtering logic
Centralise row selection model (no firstRow fallback guessing)
Split createCardForInv into:
data
render
events
Cache DOM node lists during filtering
Remove implicit globals (safeInputName, ses, etc. → pass context object)

Tests
📄 File: app/core/frontend/js/execution-render-inputs.js
🧠 What this file is now responsible for (implied by tests + code)

This module is effectively a UI orchestration layer for execution inputs, including:

Inventory row rendering
Picker card generation
Dropdown filtering
Row selection state
Integration hooks into:
ExecutionRenderInputs.renderVariableInventoryInputs
ExecutionRenderInputs.renderConfirmExecutionInputs
⚠️ Critical issues (will likely break tests or future refactors)
1. ❌ Hidden global dependency: safeInputName
Problem
id="execute-inv-arrow-" + safeInputName + '-' + id

There is no import, argument, or closure guarantee for safeInputName.

Risk
Breaks DOM lookup in:
toggleInventoryCardDetails
card expansion state
Makes tests like:
execution-modal.js delegates render inputs API
indirectly fragile (IDs must be stable)
Fix (recommended)

Pass it explicitly:

createCardForInv(inv, ctx)

or:

ctx.safeInputName
2. ❌ O(n²) DOM filtering in filterAddAnotherDropdown
File impact
This is the only interactive search path in the picker
Runs on every keystroke
Problem section
for (var i = 0; i < children.length; i++) {
  ...
  for (var j = i + 1; j < children.length; j++)
Why this matters with your test suite

Your system tests assume:

stable modal performance (execution-modal-secondary, execution-open-step)
responsive inventory refresh (refreshExecutionModalInventory)

This function becomes a bottleneck under:

batch-start workflows (explicitly tested in test_batch_start_loads_session_before_execution_modal)
Fix direction

Precompute:

const cards = [];
const headers = [];

Then update visibility in single pass grouping, not DOM scanning.

3. ❌ Layout state encoded in style.display
Affects:
header visibility
card filtering
“selected elsewhere” suppression
Problem
el.style.display = 'none'

Then later:

next.style.display !== 'none'
Why this is fragile
inline style != computed style
CSS overrides break logic silently
test suite does NOT assert UI correctness, so regressions go unnoticed
Fix (recommended)

Use class-based state:

.is-hidden
.is-active
.is-selected

This aligns better with your CSS-driven architecture implied by:

test_execution_modal_frontend_assets.py
assert ".exec-picker-card" in text
4. ⚠️ Tight coupling to session state (ses global)
Problem
ses.editingInputRow
Risk

Breaks modularity expected by:

execution-session.js (WeakMap-based session model)
execution-modal-secondary.js (installable flows)
Test hint
assert "WeakMap" in body

This implies:
👉 session is meant to be encapsulated, not globally mutated

Fix direction

Inject session:

function renderVariableInventoryInputs(ctx, session)

or:

ctx.session.get()
5. ⚠️ Event handler duplication risk
Problem
newRow.addEventListener('click', function() { setActiveRow(newRow); });
firstRow.addEventListener('click', function() { setActiveRow(firstRow); });

But also:

createInputRow(false) may already attach handlers (not shown but implied by comment)
Risk
double activation
stale row references
inconsistent active row state
6. ⚠️ Inline HTML generation = XSS surface
Affected function
createCardForInv(inv)
Problem areas:
innerHTML concatenation
partial escaping via escapeHtml (not consistently applied everywhere)
Why tests don’t catch this

Your tests validate:

module existence
API wiring
file structure

They do NOT validate:

DOM safety
rendering correctness

So this is a production-only risk

🧪 Test alignment review
✔️ Good alignment with tests

Your implementation correctly supports:

execution-render-inputs.test.js
renderVariableInventoryInputs exists ✔️
renderConfirmExecutionInputs exists ✔️
execution-modal.test.py
delegates to:
ExecutionRenderInputs.renderVariableInventoryInputs ✔️
ExecutionRenderInputs.renderConfirmExecutionInputs ✔️

So module boundaries are correct.

⚠️ Potential future test fragility
1. ID coupling

Tests do not assert DOM IDs, but your system relies on:

execute-inv-details-${safeInputName}-${id}

👉 Any refactor of safeInputName will cascade silently.

2. Ordering assumptions

You rely heavily on:

rowsContainer.firstElementChild === rowEl

No test enforces ordering invariants → fragile runtime assumption.

🧱 Design-level assessment (important)

This file is currently doing 3 roles at once:

1. Renderer
createCardForInv
populateDropdownContent
2. State manager
setActiveRow
ses.editingInputRow
3. Interaction controller
dropdown filtering
row locking logic
selection propagation
🧭 Recommended refactor direction (minimal disruption)

If you want to stabilise without rewriting:

1. Introduce a context object
{
  session,
  safeInputName,
  rowsContainer,
  inputSection,
  pickerState
}
2. Replace display logic with class toggles

Instead of:

style.display = 'none'

Use:

el.classList.add('is-hidden')
el.classList.remove('is-hidden')
3. Split filtering logic into pure function

Move out:

filterAddAnotherDropdown()

into:

computeFilteredVisibility(cards, query, selectedIds)

→ makes it testable (your current JS tests don’t cover UI logic at all)

4. Stabilise card identity

Replace DOM-ID coupling with:

data-inventory-id
data-row-id

Avoid composite IDs entirely.

📌 Summary
What is good
Module boundaries align with test suite
API exports are correctly structured
WeakMap session design exists (good direction)
What is risky
DOM identity tied to unstable string IDs (safeInputName)
O(n²) filtering logic in interactive path
Inline style state management
Hidden global coupling (ses)