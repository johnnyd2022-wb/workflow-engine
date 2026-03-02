Evidence Upload System — Implementation Instructions
1. Create Evidence Backend Module

Create new directory:

app/core/backend/evidence/

Inside it create:

__init__.py
evidence_service.py
evidence_routes.py
evidence_storage.py
evidence_validation.py

Purpose:

Handle execution evidence uploads

Keep logic separate from inventory and execution flows

2. Storage Strategy
Store metadata in PostgreSQL

Create table:

execution_evidence

Fields:

Field	Type	Required
id	UUID	Yes
org_id	UUID	Yes
execution_id	UUID	Yes
step_id	UUID	Optional
file_name	String	Yes
storage_path	String	Yes
mime_type	String	Yes
file_size	Integer	Yes
checksum_sha256	String	Yes
uploaded_by	String	Optional
created_at	Timestamp	Yes
extra_data	JSONB	Optional

Add migration file under:

app/core/db/migrations/versions/
3. Evidence File Storage Location

Create root directory:

app/core/evidence_storage/

Storage format must be:

app/core/evidence_storage/{org_id}/{execution_id}/

Rules:

Use UUID filenames

Do not trust client filenames

Generate filename using:

uuid4() + original_extension
4. Supported File Types

Whitelist only:

image/jpeg

image/png

application/pdf

Reject all other file types.

Also enforce maximum file size.

Recommended limit:

10MB per file

Configuration variables:

EVIDENCE_STORAGE_ROOT
EVIDENCE_MAX_FILE_SIZE_MB
EVIDENCE_ALLOWED_MIME_TYPES
5. Upload Flow Implementation
Step 1 — Authentication

All routes must use:

@requires_auth

Validate:

org_id from request context

user identity if available

Step 2 — Receive Upload Request

Create API route:

POST /api/core/evidence/upload

Request must contain:

file

execution_id

optional step_id

Step 3 — Validate Input

Check:

File exists

File size ≤ configured limit

MIME type is allowed

execution_id belongs to org

Return HTTP 400 on validation failure.

Step 4 — Generate Storage Path

Use this pattern:

root/
 └── org_id/
     └── execution_id/
         └── uuid_filename

If directories do not exist, create them.

Step 5 — Save File

Write file using atomic write:

Save to temporary file

Rename to final path after successful write

This prevents corruption.

Step 6 — Store Metadata Record

After file is successfully written:

Insert record into execution_evidence table.

Metadata must include:

storage_path

checksum_sha256 (compute using SHA256)

file_size

mime_type

6. Retrieval Endpoint

Implement:

GET /api/core/evidence/{evidence_id}/download

Backend must:

Verify org ownership

Stream file content

Set correct Content-Type header

Prevent direct filesystem access

7. Execution Linking

Evidence can be linked to:

Execution level

Step level (optional)

Store:

execution_id
step_id (nullable)
8. Frontend Behaviour

Allow uploads inside:

Execution modal flow

Mobile friendly UI

Support:

Drag and drop upload

Camera capture on mobile

Frontend should compress images before upload if possible.

9. Audit Requirements

Evidence records must be:

Append-only

Never overwritten

Timestamped

If user re-uploads, create a new record.

10. Security Requirements

Enforce:

Org-level isolation

Auth middleware on all routes

File type whitelist

Size limits

Checksum validation

11. Logging

Log evidence upload events using existing audit logging system.

12. Code Placement Rules

Business logic → evidence_service.py
Filesystem logic → evidence_storage.py
Request validation → evidence_validation.py
Routes → evidence_routes.py

Do not mix responsibilities.

13. Commit Order (Important)

When uploading evidence:

Write file to disk

Generate checksum

Insert database metadata

Return success response

Rollback if any step fails.

Add an upload evidence option in the execution modal under execution prompts. Use the same approach as we have done for Batch number here with the same options and defaults. This should then have an upload option in executions with optional and required logic working. This should cleanly map to the backend code we setup and store evidence upon execution completion and also we should be able to see evidence on executions in sourcemap tracing with an 'evidence' button when evidence exists on a node