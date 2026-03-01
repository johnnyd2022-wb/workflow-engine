⚠️ Backend Issues (Important)
⭐ Issue 1. Potential race condition window (MOST IMPORTANT)
Problem

You do:

DB commit
↓
Finalize file move

But if server crashes between these steps:

You may get:

DB record exists

File does not exist

You partially mitigate but not fully.

Recommendation (Production grade fix)

Add file existence recovery check or transactional marker.

Option A (Best): Write file first → then DB commit.

But you intentionally want "no orphan files".

So instead implement:

DB record status = PENDING_FILE
↓
Finalize move
↓
Update status = ACTIVE

Add column:

evidence_status ∈ {PENDING, ACTIVE, FAILED}

This is enterprise-safe design.

⭐ Issue 2. Temp file cleanup is inconsistent

In:

upload_evidence_from_temp()

If finalize_from_temp() fails:

You return error but do NOT clean:

record in DB
temp file (already moved? maybe not)

You should guarantee cleanup path.

Add:

try:
    finalize_from_temp(...)
except Exception:
    rollback DB record
    delete final file if created
⭐ Issue 3. Checksum is computed before final storage move

You compute checksum on temp file.

This is fine.

But you never:

✅ Verify checksum after finalize move

I strongly recommend adding:

verify_checksum_after_move()

Even if expensive, it protects against:

Disk corruption

Partial OS write anomalies

⭐ Issue 4. Streaming upload memory safety

Good move switching to streaming temp save.

But Flask request.files["file"].save() may internally buffer depending on server config.

If you expect very high load, consider enforcing:

MAX_CONTENT_LENGTH

at Flask app level.

⭐ Issue 5. Repository layer lacks optimistic concurrency guard

Current pattern:

db_session.flush()
commit()

No versioning.

If multiple uploads happen concurrently on same execution-step:

Ordering is undefined.

If business logic requires sequencing, add:

sequence_number
OR
created_at monotonic constraint
⚠️ Frontend Issues
⭐ Evidence Map is correct but duplicated

You maintain:

modal.evidenceByStepId = Map()

Good.

But you also repeatedly filter backend lists.

This is O(N²) in worst rendering paths.

Not a dealbreaker but can be optimized.

Suggest caching normalized evidence index:
{
 execution_step_id → evidence[]
 step_definition_id → evidence[]
}

Build once per modal load.

⭐ Upload concurrency bug (Important)

Frontend:

Promise.all(toUpload)

If multiple files are selected:

✔ Good parallelism.

But if one upload fails:

You don’t remove already uploaded files from UI.

User may think batch upload failed.

Add partial success handling.

⭐ Multiple file upload UX risk

You allow:

multiple

But backend schema does not enforce batch semantics.

Meaning:

Frontend assumes batch → backend treats as independent records.

This is acceptable but should be documented.

⭐ Validation mismatch risk (Medium severity)

Frontend enforces:

10MB

Backend also enforces.

Good.

BUT:

Both must be source-of-truth.

Right now config lives in backend.

Frontend hardcodes:

var maxEvidenceBytes = 10 * 1024 * 1024;

This is fragile.

Fix

Expose config via API or embed metadata in page.