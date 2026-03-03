Step-by-Step Implementation Plan for Cursor

This is written as clean execution instructions.

🎯 Goal

Enable:

Uploading SOP documents to process steps

Writing inline step documentation

Displaying this content inside the execution modal

PHASE 1 — Database Changes
1️⃣ Create New Table: process_step_documents

Add migration under:

app/core/db/migrations/versions/
Table: process_step_documents

Fields:

Field	Type	Required
id	UUID	Yes
org_id	UUID	Yes
process_id	UUID	Yes
step_id	UUID	Yes
title	String	Yes
storage_path	String	Nullable
content_markdown	Text	Nullable
mime_type	String	Nullable
file_size	Integer	Nullable
created_at	Timestamp	Yes
updated_at	Timestamp	Yes
created_by	UUID	Optional

Rules:

Either storage_path OR content_markdown must exist.

Do not allow both null.

This allows:

File-based SOP

Inline written SOP

PHASE 2 — Storage Design

Create new directory:

app/core/process_docs_storage/

Storage format:

app/core/process_docs_storage/{org_id}/{process_id}/{step_id}/

This keeps documentation tied to process definitions, not executions.

Use UUID filenames.

Do not reuse evidence_storage.

PHASE 3 — Backend Module

Create new directory:

app/core/backend/process_docs/

Inside:

__init__.py
process_docs_service.py
process_docs_routes.py
process_docs_storage.py
process_docs_validation.py

Do not mix this into evidence module.

PHASE 4 — Upload + CRUD Endpoints
1️⃣ Upload SOP File
POST /api/core/process-docs/upload

Request:

process_id

step_id

file

Validation:

org ownership

allowed mime types

size limit (recommend 20MB)

Allowed MIME types:

application/pdf

application/msword

application/vnd.openxmlformats-officedocument.wordprocessingml.document

text/markdown

text/plain

Reject images (images belong to evidence).

2️⃣ Create / Update Inline SOP
POST /api/core/process-docs/inline

Body:

process_id

step_id

title

content_markdown

This allows writing SOP directly inside platform.

3️⃣ List Step Documentation
GET /api/core/process-docs/{step_id}

Returns:

file-based docs

inline docs

4️⃣ Delete Documentation

Admins only.

Soft delete preferred.

PHASE 5 — Execution Modal Integration

Modify:

frontend/js/execution-modal.js

When execution modal loads:

Fetch step documentation

Render documentation above or beside step instructions

Display behavior:

If markdown → render as formatted HTML

If file → show downloadable link

If PDF → optionally preview in iframe

Documentation must be read-only during execution.

PHASE 6 — Process Versioning (Important)

If your process definitions are versioned:

Step documentation must attach to a specific process version

Do not mutate historical documentation for past versions

If not versioned yet:

At minimum:

Store process_id at time of upload

Do not allow cross-process document reuse

PHASE 7 — Permissions

Enforce:

Only org admins can upload/edit/delete SOP

Operators can only view during execution

Reuse existing permissions framework.

PHASE 8 — Configuration

Add:

PROCESS_DOCS_STORAGE_ROOT
PROCESS_DOCS_MAX_FILE_SIZE_MB
PROCESS_DOCS_ALLOWED_MIME_TYPES
PHASE 9 — Logging

Log:

SOP upload

SOP update

SOP deletion

Use existing audit_log system.

Do NOT log inline content body (only metadata).

PHASE 10 — Clean Separation Rules

Strict rules:

Evidence code must never import process_docs

Process_docs must never import evidence

Execution must read-only access process_docs

UI UX Recommendations

Inside execution modal:

Structure:

--------------------------------
Step Title
--------------------------------
📘 Documentation
--------------------------------
Step Instructions
--------------------------------
Evidence Upload Area
--------------------------------

Documentation should feel like “reference manual”.

Evidence should feel like “proof requirement”.

Architectural Outcome

After implementation you will have:

Process Definition Layer

Execution Layer

Audit Layer

Instruction Layer

This is proper SaaS workflow architecture.