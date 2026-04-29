1. execution-security-utils.js (CRITICAL — security foundation)
What you did right (MERGE SAFE)
✔ Origin resolution hardening
You fixed a real class of opaque origin bugs:
about:blank
blob:
file:
non-http(s) contexts
You now:
Prefer loc.origin on http(s)
Fall back to new URL(loc.href) safely
Reject "null" origins

✔ This meaningfully closes:

origin spoofing edge cases
broken comparisons in sandboxed contexts
inconsistent embed policy between browsers
Security status

GOOD — no blocking issues left

Performance impact
Negligible
One URL() parse per check is fine (low frequency path)
Residual (NON-BLOCKING)
None that matter for your stated goal
2. execution-doc-overlay.js (CRITICAL — embed sink)
What you improved (GOOD)
✔ Centralized security policy
Removed duplicate URL logic
Uses:
ExecutionSecurityUtils.isSameOriginEmbedUrl
✔ Fail-closed behavior
If missing dependency → overlay disabled
Logs once per tab
✔ Explicit embed gating
prevents:
cross-origin iframe injection
javascript:/data: injection
Security status

SAFE TO MERGE

Performance notes
Slight improvement (less duplicated logic)
No regressions
Residual risk (LOW)
Only UX: overlay silently disabled if utils not loaded
but this is intentional fail-closed
3. execution-render-docs.js (CRITICAL — second embed sink)
What you improved (GOOD)
✔ Same security model enforced
Uses:
viewUrlEmbedOk = ExecutionSecurityUtils.isSameOriginEmbedUrl(viewUrl)
✔ Prevents unsafe rendering in BOTH:
iframe
image preview
✔ Proper fallback UX (text warning instead of embed)
Security status

SAFE

Performance status
Slight improvement (less DOM creation for unsafe URLs)
No meaningful overhead introduced
Residual risk (LOW)
None security-wise
4. execution-modal.js (CRITICAL — enforcement boundary)
What you did (IMPORTANT)
✔ Hard dependency enforcement
throw new Error('execution-security-utils.js must be loaded before execution-modal.js');
Why this matters

This is actually one of the strongest improvements in the entire patch set:

prevents silent bypass of embed policy
avoids partial initialization states
enforces load-order correctness at runtime
Status

GOOD — MERGE SAFE

5. execution-render-prompts.js (HIGH — correctness + performance)
What you improved
✔ Abort correctness
throwIfAborted(signal) added
prevents post-abort DOM work
✔ Evidence deduplication fix

Before:

O(n²) via .findIndex

After:

Set-based dedupe
Impact
Performance
Real improvement in large executions
prevents quadratic blowups in evidence-heavy steps
Correctness
eliminates duplicate UI entries
Status

SAFE + ACTUAL IMPROVEMENT

Residual notes
nothing blocking
6. execution-modal-secondary.js (MEDIUM → PERFORMANCE + SAFETY)
What you improved
✔ AbortController added for inventory refresh
refreshInventoryAbort.abort()
✔ Prevent stale UI updates
generation token still exists (good)
now combined with abort (stronger model)
Impact
Performance
prevents wasted network + DOM updates
avoids race-heavy UI churn
Security
none directly, but improves correctness under rapid user actions
Status

SAFE TO MERGE

7. execution-open-step.js (CRITICAL — orchestration correctness)
What you improved
✔ Full lifecycle cancellation model
AbortController introduced
signals passed into:
inventory
expired materials
untracked
docs
org users
render steps
✔ Combined with:
generation token guard (staleOpen)
abort handling in all async chains
Why this matters

This is the most important runtime stability fix in the entire change set:

You eliminated:

stale modal rendering
cross-click race conditions
wasted parallel fetch execution
Status

MERGE SAFE — HIGH VALUE

Residual risk
minor: still assumes all downstream renderers respect signal (you partially enforce this — good enough for now)
8. core-api.js (MEDIUM — resilience layer)
What you improved
✔ Broader network error detection

Now catches:

failed to fetch
load failed
networkerror
network request failed
Impact
Reliability
fewer misleading generic errors
better UX under mobile / flaky network conditions
Security
none directly
Status

SAFE

Residual note
still no retry/backoff (but explicitly deferred elsewhere)
9. execution-submit.js (HIGH — correctness)
What improved
✔ Submit in-flight guard
modal._submitExecutionInFlight
✔ Guaranteed reset via finally

Prevents:

stuck disabled submit button
duplicate submissions
Status

SAFE

10. execution-step-spa.js (PERF — LOW/MEDIUM)
What improved
✔ Listener lifecycle note + DOM reset behavior
clarifies event cleanup via innerHTML replacement
Important reality check

This is NOT a full fix for listener accumulation risk, but:

You already removed the worst case (per-card rebind loop earlier)
Current state is acceptable given your constraints
Status

ACCEPTABLE

CROSS-CUTTING SUMMARY (WHAT ACTUALLY MATTERS)
🔴 Critical security issues — RESOLVED
iframe injection risk → FIXED
cross-origin embed → FIXED
javascript:/data: injection → FIXED
missing security module → FAIL-CLOSED enforced
🟠 Critical runtime correctness — RESOLVED
stale modal race conditions → FIXED
concurrent openExecutionModal calls → FIXED
submit duplication → FIXED
inventory refresh race → FIXED
🟡 Performance issues — IMPROVED
evidence dedupe O(n²) → FIXED
abort/cancel reduces wasted fetch work → FIXED
reduced redundant DOM rendering paths → PARTIAL
FINAL MERGE VERDICT
✅ SAFE TO MERGE

No blocking security or correctness issues remain.

What you achieved (in practical terms)

You’ve effectively added:

a defensive embed security layer
a cancellation-aware modal orchestration system
race-condition hardening across 3 independent async pipelines
removal of at least one real quadratic UI bug
improved network error semantics