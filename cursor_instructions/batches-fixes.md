🔴 Remaining critical issues
1) renderInFlight still leaks on early return before try

You moved renderInFlight = true outside the try:

renderInFlight = true;
try {

But this block still exists before entering try:

if (!isOnExecutionStepScreen()) return;
Scenario
Call enters
renderInFlight = true
Route check fails → return
No finally → stuck forever
Fix

Move assignment inside the try:

if (!isOnExecutionStepScreen()) return;

var myToken = ++renderToken;
if (renderInFlight) {
  renderQueued = true;
  return;
}

try {
  renderInFlight = true;
  ...
} finally {
  renderInFlight = false;
}
2) myToken missing in snippet (possible regression)

Your updated code uses:

if (myToken !== renderToken) return;

But I don’t see:

var myToken = ++renderToken;

in the new snippet.

If actually missing:
race protection is completely broken
stale responses can overwrite newer ones
3) _safe_flow_return_to → path traversal edge case

Your checks block:

schemes
//
absolute URLs

But this still passes:

/core/flows/../../admin
Impact
internal route hopping
could bypass UI-level access assumptions
Fix (optional but safer)

Normalize:

import posixpath

normalized = posixpath.normpath(s)
if not normalized.startswith("/core/flows"):
    return default
4) API endpoint: potential N+1 / lazy-load explosion
for es in execution.execution_steps:
    "step_name": es.step.name if es.step else None,
Risk

If es.step is lazy-loaded:

→ N queries per execution

Same for:

process.steps
Fix

Ensure repo uses eager loading:

SQLAlchemy: joinedload / selectinload

Otherwise this endpoint becomes O(n) queries

5) Payload size bloat (hidden performance cost)

You return:

{
  execution: {
    execution_steps: [...],
    evidence: [...]
  },
  process: {
    steps: [...]
  }
}
Risk
large processes (20–50 steps)
evidence arrays
repeated navigation

→ payloads easily hit 100–300KB

Suggestion

Not urgent, but consider:

omit unused fields (e.g. description, execution_prompts unless needed)
or add ?minimal=1
6) Missing guard: bundle shape
executionData = bundle && bundle.execution;
processData = bundle && bundle.process;
Risk

If backend returns unexpected shape:

→ silent undefined usage downstream

Fix

Hard guard:

if (!bundle || !bundle.execution || !bundle.process) {
  throw new Error('Invalid execution bundle response');
}
🟠 Medium-risk issues
7) Duplicate fallback lookup defeats Map benefit
stepDefinition = stepMap.get(...) || procSteps.find(...)
Reality

If Map is built correctly, fallback is unnecessary.

Impact
redundant O(n) scan
hides data integrity issues
Better

Fail fast:

stepDefinition = stepMap.get(String(stepId));
if (!stepDefinition) throw new Error(...)
8) Draft path still does double work
processData = await window.CoreAPI.getProcess(processId);
Observation

You could extend your bundle endpoint to support:

GET /processes/:id/with-steps

Then both paths use single API pattern

9) returnTo still trusted on client

Even though backend sanitises it, you still:

window.location.href = dest;
Subtle issue

If frontend state gets corrupted (or reused elsewhere):

→ potential redirect misuse

Safer

Optionally enforce:

if (!dest.startsWith('/')) dest = '/core/flows';
10) isDraft parsing duplicated logic
ctx.draft === true || ctx.draft === 'true' || ...
Minor, but brittle

Centralise:

function toBool(v) {
  return v === true || v === 'true' || v === 1 || v === '1';
}
🟡 Minor observations
_safe_flow_return_to is well thought out 👍
startsWith change is cleaner
API naming is good (with-process is explicit)
consistent ISO timestamps 👍
🧠 Architectural note (important)

You’re moving toward:

“execution screen = data-driven page with reusable renderer”

That’s the right direction.

But you still have:

modal-driven rendering core
page adapting around it
Long-term risk

You’ll accumulate:

CSS overrides
render mode flags
behavioural edge cases
Cleaner direction

Split:

ExecutionRenderer (pure UI)
ExecutionModal (wrapper)
ExecutionPage (wrapper)

Right now, ExecutionModal is doing too much.

TEST review

1) You’re testing the right threat model

You covered:

absolute URLs (https://, http://)
protocol-relative (//evil.com)
script schemes (javascript:, data:, vbscript:)
empty / whitespace
malformed relative (core/flows, ?tab=1)

That’s the correct attack surface for open redirects.

🔴 Critical gaps
1) No test for encoded bypasses

Attackers don’t send clean strings. They send encoded payloads.

Missing cases:
"%2F%2Fevil.com"              # encoded "//"
"%68%74%74%70%3A%2F%2F..."   # encoded "http://"
"/%2F%2Fevil.com"
"/\\evil.com"                # backslash variant
Why this matters

Your function:

if "://" in s:

→ won’t catch encoded versions

Add:
@pytest.mark.parametrize("value", [
    "%2F%2Fevil.com",
    "/%2F%2Fevil.com",
    "%68%74%74%70%3A%2F%2Fexample.com",
])
def test_encoded_bypass_attempts_blocked(value):
    assert _safe_flow_return_to(value, PROCESS_ID) == EXPECTED_DEFAULT
2) No test for path traversal

You don’t currently restrict paths to /core/flows.

So this passes:

"/core/flows/../../admin"
Add:
def test_path_traversal_not_allowed():
    value = "/core/flows/../../admin"
    assert _safe_flow_return_to(value, PROCESS_ID) == EXPECTED_DEFAULT

Even if you don’t enforce it now, this test will catch future tightening.

3) No test for urlparse quirks

urlparse has edge cases like:

"/\\evil.com"
"/evil.com:80"
Add:
@pytest.mark.parametrize("value", [
    "/\\evil.com",
    "/evil.com:80",
])
def test_weird_netloc_like_paths(value):
    assert _safe_flow_return_to(value, PROCESS_ID) == EXPECTED_DEFAULT
4) Missing query/fragment edge cases

These can sometimes sneak through:

"/core/flows#//evil.com"
"/core/flows?next=//evil.com"
Add:
@pytest.mark.parametrize("value", [
    "/core/flows#//evil.com",
    "/core/flows?next=//evil.com",
])
def test_embedded_redirect_vectors(value):
    # depends on your policy — currently these PASS
    assert _safe_flow_return_to(value, PROCESS_ID) == value

👉 Important: This forces you to decide policy explicitly

🟠 Medium issues
5) Overly permissive “valid” tests
("/core/flows?id=abc", ...)

You’re not validating:

id format
query integrity

That’s fine for this function, but the test name implies stronger guarantees than reality.

6) No test for whitespace normalization inside string

You test:

"  /core/flows  "

But not:

"/core/flows   "
"/core/flows\n"
"/core/flows\t"
Add:
@pytest.mark.parametrize("value", [
    "/core/flows   ",
    "/core/flows\n",
    "/core/flows\t",
])
def test_trailing_whitespace_trimmed(value):
    assert _safe_flow_return_to(value, PROCESS_ID) == "/core/flows"
7) Case-insensitive scheme test is incomplete

You test:

"Javascript:alert(1)"

But not:

"JaVaScRiPt:alert(1)"
Add:
def test_mixed_case_scheme_blocked():
    assert _safe_flow_return_to("JaVaScRiPt:alert(1)", PROCESS_ID) == EXPECTED_DEFAULT
🟡 Minor observations
Test names are clear and scoped 👍
Parametrization is clean 👍
Good use of default constant 👍
🧠 Subtle design issue the test exposes

Right now your function allows:

"/any/internal/path"

But your app logic really expects:

"/core/flows..."
Your test currently reinforces permissiveness

If your intent is:

“only allow navigation within flows UI”

Then your test suite should enforce that.

✅ Recommended additions (minimal set)

If you want high confidence without overkill, add just these:

# 1. Encoded bypass
"%2F%2Fevil.com"

# 2. Path traversal
"/core/flows/../../admin"

# 3. Mixed case scheme
"JaVaScRiPt:alert(1)"

# 4. Weird slashes
"/\\evil.com"
Final verdict

Your test is:

✅ Correct for obvious attacks
⚠️ Not robust against real-world bypass techniques

It will catch regressions, but not clever inputs.