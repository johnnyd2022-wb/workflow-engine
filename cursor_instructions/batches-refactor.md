🔴 CRITICAL — Security Findings
app/core/frontend/js/execution-security-utils.js
✅ What is now strong
Centralised policy module (ExecutionSecurityUtils)
Fail-closed design:
rejects missing location.href
rejects malformed URLs
Blocks unsafe schemes:
javascript:
data:
vbscript:

Correct use of:

new URL(loc.href).origin

instead of unreliable location.origin

⚠️ Remaining security concerns
1. Trust boundary is still “client-side only”

This module is now the single source of truth, but:

It only enforces policy in UI rendering
Any backend-supplied docUrl is still trusted until it hits this function

Risk:
If any future UI bypasses ExecutionSecurityUtils, there is no server-side enforcement.

Severity: HIGH (architectural security dependency)

2. Fail-closed behavior may break valid embeds in edge environments
if (!pageOrigin) return false;

Impact:

SSR / embedded contexts / sandboxed iframes could unintentionally block all docs

Security tradeoff:
Correct (fail closed), but may cause operational surprises.

Severity: LOW (but operational risk)

app/core/frontend/js/execution-doc-overlay.js
✅ Improvements

Now delegates to:

root.ExecutionSecurityUtils.isSameOriginEmbedUrl
Removes duplicated security logic (good architectural cleanup)
⚠️ Issues
1. Thin wrapper still introduces dependency risk
function urlAllowedForEmbed(url) {
  var sec = root.ExecutionSecurityUtils;

Problem:

If ExecutionSecurityUtils fails to load:
overlay silently denies everything
no diagnostic or fallback mode

Severity: MEDIUM

Suggestion:
Add explicit failure logging:

“security module missing” is currently invisible failure mode
app/core/frontend/js/execution-modal.js
⚠️ Critical architectural inconsistency

You now have:

ExecutionSecurityUtils (overlay + docs)
BUT ALSO a local duplicate wrapper:
function urlAllowedForEmbed(url) {
  var sec = root.ExecutionSecurityUtils;
Problem

This creates:

dual policy access paths
risk of divergence if modal evolves separately

Even though both call the same underlying function, the duplication is unnecessary coupling.

Severity: MEDIUM-HIGH (maintainability → security drift vector)

2. Mixed responsibility: modal rendering + security decisioning

This file still:

decides embed eligibility
renders images
renders iframe

Risk:
Security logic is still not fully isolated at render boundary level.

app/core/frontend/js/execution-render-docs.js
✅ Improvements
Correctly uses shared security utility
Same-origin enforcement now consistent across:
iframe
image preview
⚠️ Issue
1. Partial duplication of policy usage pattern

Even though logic is centralized, usage pattern is still duplicated:

overlay → urlAllowedForEmbed
modal → urlAllowedForEmbed
render-docs → direct ExecutionSecurityUtils

Risk:
Inconsistency in future extensions (new embed types likely to bypass one path)

Severity: MEDIUM

🟠 PERFORMANCE FINDINGS
app/core/frontend/js/execution-security-utils.js
⚠️ Minor performance concern
1. Double URL parsing overhead
var resolved = new URL(s, loc.href);
return resolved.origin === pageOrigin;
getPageOrigin() already uses new URL(loc.href)
then each call constructs another URL()

Impact:

negligible per call
but can accumulate in large document lists

Severity: LOW

app/core/frontend/js/execution-render-docs.js
⚠️ Minor inefficiency
2. Repeated security checks per asset

Each doc may call:

isSameOriginEmbedUrl(viewUrl) multiple times

Impact:

unnecessary repeated URL parsing for same string

Severity: LOW

app/core/frontend/js/execution-modal.js
⚠️ Performance + maintainability
3. Repeated policy wrapper overhead

Local urlAllowedForEmbed() adds:

function call indirection
no caching

Impact:

negligible individually
becomes noisy in large render loops

Severity: LOW

🟡 ARCHITECTURAL OBSERVATIONS
1. Good: Security consolidation achieved (mostly)

You successfully moved from:

duplicated inline logic ❌
to:
shared policy module ✔

This is a meaningful improvement in attack surface control

2. Remaining duplication is conceptual, not logical

You still have 3 layers:

execution-security-utils.js   (policy engine)
execution-doc-overlay.js      (wrapper)
execution-modal.js            (duplicate wrapper)
execution-render-docs.js      (direct usage)
Problem:

Policy is unified, but access patterns are not

3. Best remaining improvement (highest leverage)

Eliminate all wrappers and enforce:

ONLY execution-security-utils.js is allowed to decide embed safety

Everything else should do:

ExecutionSecurityUtils.isSameOriginEmbedUrl(url)

directly.

🧾 FINAL PRIORITISED SUMMARY
🔴 Critical (security architecture)
execution-security-utils.js
good fail-closed model, but still UI-only enforcement
execution-modal.js
redundant security wrapper (drift risk)
execution-doc-overlay.js
silent failure if security module missing
🟠 Medium (correctness / consistency)
execution-render-docs.js
consistent usage, but still pattern drift risk
cross-module duplication of urlAllowedForEmbed
🟡 Low (performance)
repeated URL() parsing in security util
repeated embed checks per render
wrapper function overhead in modal

Architecture review findings
🔴 CRITICAL — Security / correctness risks
app/core/frontend/js/execution-security-utils.js
1. ❗ Weak origin validation fallback behavior (fail-closed but overly strict)

Issue

var pageOrigin = getPageOrigin();
if (!pageOrigin) return false;

If location.href is temporarily unavailable or malformed, you block all embeds, even same-origin safe ones.

Impact

Breaks embedded docs in edge SPA states (early boot, iframe reuse, or prerender contexts)
Causes silent UX failure rather than degraded mode

Why it matters
Fail-closed is correct for security, but here it's over-applied to UI embed rendering, not just hostile URLs.

Suggestion

Allow a secondary safe fallback:
root.location.origin (if available)
or cached origin at module init time
2. ⚠️ URL parsing relies on new URL(loc.href) without guarding about:blank / blob contexts

Issue

return new URL(loc.href).origin;

Impact

about:blank, blob:, or sandboxed iframe contexts can throw or yield unexpected origin handling
Could cause inconsistent embed blocking across environments
app/core/frontend/js/execution-doc-overlay.js
3. ⚠️ Duplicate policy enforcement logic still exists (architectural risk)

You now have:

ExecutionSecurityUtils.isSameOriginEmbedUrl
local wrapper urlAllowedForEmbed
overlay depends on shared module
render-docs also depends on shared module

Issue
Even though centralized, you still:

re-wrap the function in multiple files
duplicate guard semantics (urlAllowedForEmbed vs direct call)

Impact

Divergence risk reintroduced (security logic drift across wrappers)
Harder audit surface (2-hop trust chain instead of 1)

Recommendation
Remove local wrapper entirely:

ExecutionSecurityUtils.isSameOriginEmbedUrl
4. ⚠️ Missing enforcement symmetry between overlay + render-docs

Overlay blocks via:

urlAllowedForEmbed()

Render-docs blocks via:

urlAllowedForEmbed()

But they still diverge in behavior:

overlay: hard block
render-docs: fallback message UI

Impact

Same URL can behave differently depending on entrypoint
Potential UX-based bypass confusion (not a direct vuln, but inconsistent trust boundary)
app/core/frontend/js/execution-open-step.js
5. ⚠️ AbortController does not cancel non-fetch async work

You correctly abort:

openExecutionModalAbortController.abort();

But:

loadOrgUsersMap
ExecutionRenderPrompts
ExecutionRenderOutputs

Only partially respect signal

Impact

UI work continues after abort in some branches
wasted CPU + potential stale DOM mutations if a module ignores signal internally

Severity
Medium-to-high correctness risk in SPA race conditions

app/core/frontend/js/execution-modal-secondary.js
6. ⚠️ AbortController race still leaves shared global mutation window
refreshInventoryAbort.abort();
refreshInventoryAbort = new AbortController();

Issue
Between abort + new assignment:

async continuation from prior request can still resolve just before abort is checked

You mitigate with:

if (gen !== refreshInventoryGeneration) return;

But:

you now rely on two independent race guards (abort + generation)

Impact

redundant safety layers → harder debugging
subtle timing bugs under load
app/core/frontend/js/core-api.js
7. ⚠️ AbortError handling still mixed with business logic errors
if (error.name === 'TypeError' && message === 'Failed to fetch')

Issue
Browser fetch failure semantics are brittle:

"Load failed"
"Failed to fetch"
opaque network errors vary by browser

Impact

inconsistent user-facing error classification
can mislabel infrastructure issues as client-side network issues

Not security-critical, but reliability-critical in production UX

🟠 HIGH — Performance / architectural concerns
execution-open-step.js
8. ⚠️ Excessive parallel dependency fan-out
Promise.all([
  getInventory,
  getExpiredMaterials,
  getUntrackedItems,
  docsPromise,
  loadOrgUsersMap
]);

Issue

All fire on every modal open
No caching layer
No partial reuse across steps

Impact

unnecessary load amplification per modal open
worst-case API thundering herd under multi-step workflows
execution-render-prompts.js
9. ⚠️ Evidence list deduplication is O(n²)
stepList.filter((e, i, arr) =>
  arr.findIndex(x => x.id === e.id) === i
);

Impact

quadratic behavior for large evidence sets
becomes noticeable in long-running executions

Better
Use Set-based dedupe.

execution-step-spa.js
10. ⚠️ Delegation fix is correct but incomplete lifecycle-aware cleanup missing

You fixed:

_execSpaPickerDelegate

But:

no teardown when container is removed/recreated
handler persists across SPA route replacements

Impact

potential memory leak in long-lived sessions (low severity but real in SPA-heavy usage)
🟡 MEDIUM — Maintainability / consistency
execution-security-utils.js
11. Slight over-abstraction for a single concern

Right now:

utils module
overlay wrapper
render-docs wrapper

This is drifting toward policy indirection complexity

Not a bug, but:

increases cognitive overhead during audits
increases chance of bypass via future wrapper drift
execution-modal-secondary.js
12. Abort + generation dual-tracking is duplicated pattern

You now have:

refreshInventoryGeneration
AbortController

This pattern is repeated in:

open-step
refresh-inventory

Impact

repeated race-control logic across modules
future inconsistency risk
🟢 LOW — Positive / confirmed improvements

These are correct and solid:

✔ execution-open-step.js
Proper abort chaining
stale guard (openGen)
correct async cancellation model
✔ execution-modal-secondary.js
in-flight submit guards fixed
proper finally cleanup
✔ core-api.js
signal propagation correctly wired into fetch + wrapper API
✔ execution-security-utils.js
correct centralization of URL policy
explicit scheme blocking (javascript:, data:, vbscript:)