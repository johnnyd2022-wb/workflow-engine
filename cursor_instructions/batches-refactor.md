🔴 CRITICAL — Security Findings
app/core/frontend/js/execution-doc-overlay.js
✅ Strengths
Strong improvement with isSameOriginDocumentUrl
Explicit blocking of:
javascript:
data:
vbscript:
Proper URL() resolution against base origin
Overlay teardown still intact (ESC + popstate already covered earlier)
⚠️ Remaining risks
1. Weak origin fallback logic
var origin = loc && loc.origin ? loc.origin : resolved.origin;
return resolved.origin === origin;

Issue:

If location.origin is missing (older browsers / weird contexts), fallback becomes:
resolved.origin === resolved.origin → always true

Impact:

Potential bypass of origin restriction in edge environments

Severity: HIGH (edge-case security bypass)

Fix:
Always prefer new URL(base).origin instead of location.origin.

2. Policy mismatch between overlay + embed
Overlay blocks unsafe URLs
But iframe still relies on same-origin logic only at creation time

Risk:
If URL validation is bypassed upstream, iframe is still the final sink.

Severity: MEDIUM-HIGH

app/core/frontend/js/execution-render-docs.js
✅ Strengths
Same-origin enforcement added for:
iframe
image preview
Blocks unsafe schemes
Provides fallback warning UI instead of rendering
⚠️ Issues
1. Duplicate security logic (drift risk)

You now have:

isSameOriginDocumentUrl in overlay
Another identical function in render-docs

Problem:

Divergence risk (security logic duplication is a classic failure point)

Severity: MEDIUM (maintainability → security drift)

Recommendation:
Centralise into shared utility:

execution-security-utils.js
2. iframe sandbox still permissive
allow-same-origin allow-scripts allow-popups allow-downloads

Risk:

allow-scripts + allow-same-origin effectively nullifies iframe isolation
If doc content ever becomes untrusted → XSS surface reintroduced

Severity: MEDIUM-HIGH (depends on doc trust model)

app/core/frontend/js/execution-step-spa.js
✅ Strengths
Delegated event handling introduced:
cardHost.addEventListener('click', function(ev) { ... })
_execSpaPickerDelegate prevents duplicate binding
⚠️ Issues
1. Delegation still depends on rerender integrity

If cardHost is replaced in DOM (not reused):

delegate breaks silently
no rebind logic shown

Severity: MEDIUM (resilience risk)

2. No event boundary hardening
t.closest('.exec-picker-card')
Assumes DOM structure stability
No guard for malicious DOM injection altering .exec-picker-card

Severity: LOW-MEDIUM

app/core/frontend/js/execution-modal-secondary.js
✅ Strengths
Fixed double submit via:
_executionUntrackedFormBound
_untrackedSubmitInFlight
Fixed race in refreshExecutionModalInventory using generation token
⚠️ Issues
1. Missing abort/cancellation for async submit path
submit uses in-flight flag but:
no AbortController
no request cancellation

Impact:

wasted network / race conditions on navigation

Severity: MEDIUM (performance + correctness)

2. Inventory refresh race still partially localised
var gen = ++refreshInventoryGeneration;

Good fix, BUT:

only guards post-fetch
does not cancel API call itself

Severity: LOW-MEDIUM

app/core/frontend/js/execution-open-step.js
✅ Strengths
Strong concurrency protection:
var openGen = ++openExecutionModalGeneration;
Guards inserted after each async stage
⚠️ Issues
1. Repeated guard pattern is brittle

You now have multiple:

if (openGen !== openExecutionModalGeneration) return;

Risk:

easy to miss future async branches
partial UI hydration still possible

Severity: MEDIUM (architectural correctness)

Better approach:
Single cancellation token or AbortSignal style orchestration.

app/core/frontend/js/execution-shared-utils.js
⚠️ Minor
1. Silent fallback still exists in other paths

You added:

console.warn('loadOrgUsersMap: failed to fetch')

Good, but:

function still returns empty Map implicitly elsewhere (not shown here)
may hide systemic API degradation

Severity: LOW

🟠 PERFORMANCE FINDINGS
app/core/frontend/js/execution-step-spa.js
⚠️ Good improvement
Delegated listener removes per-render binding overhead
Remaining concern:
1. Re-render cost still unknown
rerender() still likely rebuilds DOM nodes
delegation reduces listeners but not DOM churn

Severity: MEDIUM (depends on scale of inventory list)

app/core/frontend/js/execution-modal-secondary.js
⚠️ Performance issue
1. Inventory refresh still full fetch + full rehydrate

Even with generation guard:

still re-fetches full inventory every time

No caching layer or diffing

Severity: MEDIUM

app/core/frontend/js/execution-render-docs.js
⚠️ Minor performance concern
1. Repeated URL validation per render
isSameOriginDocumentUrl() called multiple times per doc

Impact:

negligible unless large doc sets, but still redundant

Severity: LOW

🟡 ARCHITECTURAL OBSERVATIONS (Cross-file)
1. Security logic duplication

Repeated in:

overlay
render-docs

➡️ This is the largest long-term risk
Not immediate exploit, but future inconsistency risk

2. Two different concurrency models
open-step → generation counter
modal-secondary → generation counter
others → flags / no model

➡️ Fragmented concurrency control

3. Sandbox model inconsistency
iframe sandbox present
but trust model still assumes:
“same-origin docs are safe”
no CSP enforcement shown
🧾 PRIORITISED SUMMARY
🔴 Highest priority (security)
execution-doc-overlay.js
origin fallback bypass edge case
execution-render-docs.js
duplicated security logic
iframe sandbox over-permissive model
🟠 Medium priority (correctness + perf)
execution-modal-secondary.js
missing abort/cancel for async flows
execution-open-step.js
brittle repeated guard pattern
execution-step-spa.js
dependency on DOM stability for delegation
🟡 Lower priority
execution-render-docs.js URL validation repetition
execution-shared-utils.js logging improvement