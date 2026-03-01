⚠️ Medium priority issues
1. Frontend → backend upload race pattern

This part is slightly risky:

await CoreAPI.uploadEvidence(fd);
var res = await CoreAPI.listEvidence(executionIdForEvidence);

Inside file loop.

Problem:

If multiple files are uploaded:

Network latency can reorder operations

UI may flicker

Fix (better pattern)

After all uploads:

Promise.all(uploadTasks)
↓
Single listEvidence refresh
↓
Render once

This is smoother UX and lower backend load.

2. Evidence count stored in DOM dataset

You are doing:

uploadZone.dataset.evidenceCount

This is fragile state storage.

If DOM is re-rendered → state is lost.

Better pattern:

Maintain:

const evidenceState = new Map(stepId → evidenceList)

or reload from backend when modal opens.

3. Validation logic is duplicated

You validate evidence requirement in two places:

Runtime UI layer
dataset.evidenceCount < 1
Prompt building layer
prompt.required !== false

This can diverge.

Recommended architecture:

Single source of truth:

backend prompt schema → frontend render → frontend validation
4. File size guard is only client-side

You correctly have server validation.

But client check is still advisory.

Good.

Just remember:

Client checks are UX only.

Never trust them.

You already understand this.

🔥 The most important subtle bug (please fix)
Step mapping logic can silently break

This pattern appears multiple times:

e.step_id === currentStepId
OR
e.step_definition_id === currentStepId

and sometimes:

execution_step_id

The danger:

If backend response shape changes → evidence may disappear from UI.

I strongly recommend canonicalising evidence records.

Backend should always return:

{
  id
  file_name
  mime_type
  file_size
  step_definition_id
  execution_step_id
  execution_id
}

Frontend should NEVER infer mapping.

Right now you are close but not fully there.

⭐ Performance considerations (senior engineer level)
Evidence list re-fetching is potentially expensive

You are doing:

upload → listEvidence → filter → render

This is O(N + network cost).

If evidence volume grows:

Modal open latency increases.

Better pattern:

Return uploaded record directly:

uploadEvidence()
↓
Backend returns evidence metadata
↓
Frontend append record locally
↓
Optional periodic sync

This is how high-scale SaaS platforms behave.