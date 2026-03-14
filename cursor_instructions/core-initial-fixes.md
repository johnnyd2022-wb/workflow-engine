Context

This is a Flask application using SQLAlchemy + Alembic, with a custom authentication and 2FA system, multi-tenant org isolation via org_id, a DAG-based execution system, and a UI composed of HTML/CSS/JS templates.

The goal of this task is to do a final production-readiness and polish pass across security, data integrity, execution correctness, and UI consistency — without over-engineering.

Treat this as a single cohesive change set, not isolated fixes.

1. Security & Auth Hardening (Highest Priority)

Static Asset Serving

Remove or refactor any custom Flask routes that serve JS/CSS without authentication.

Static assets must either:

Be served via Flask’s standard static mechanism, or

Be protected by the same auth middleware as application pages.

Do not allow unauthenticated enumeration of frontend assets.

Path Traversal Protection

Any use of send_from_directory must be hardened.

Reject or sanitize filenames containing .., /, or invalid extensions.

Prefer explicit extension whitelisting.

Email Uniqueness

Enforce case-insensitive uniqueness of email addresses at the database level.

Prevent race conditions where two signups with the same email could succeed concurrently.

Handle constraint violations gracefully in the API and surface a clear user-facing error.

2. Execution & DAG Correctness (Critical)

Terminal Step Detection

Remove any logic that infers the final step using list length or ordering.

Introduce a deterministic mechanism:

Either an explicit is_terminal_step

Or a terminal step resolved and stored at execution creation time

Inventory classification and execution completion must rely on this, not array order.

Step Order Enforcement

Prevent completing execution steps out of order.

Before a step can be marked complete:

All required prior steps must already be completed.

If violated, return a proper conflict/error response (do not silently accept).

Execution Creation Atomicity

Execution creation and initial execution-step instantiation must be fully transactional.

Ensure no duplicate or partial execution state can be created under concurrent requests.

Progress Calculation Integrity

Avoid division by zero.

Progress should not change if steps are added or reordered later.

Snapshot the expected step count at execution creation and use that consistently.

3. Inventory & Data Integrity (High Priority, Non-Blocking)

Maintain current flexible inventory representation (JSONB / strings), but:

Ensure schema decisions made now will not block later unit normalization.

Validate required fields exist before writing inventory records.


4. Error Handling & API Hygiene (Medium Priority)

Replace generic Exception handling with domain-specific errors where reasonable.

Avoid returning raw exception strings to clients.

Standardize error response shapes for frontend consumption.

5. Non-Goals (Do NOT Do These)

Do not introduce:

Full DAG cycle validation

Over-abstracted workflow engines

Premature unit conversion systems

New frontend frameworks

Do not refactor for elegance unless required for correctness or security.

6. Acceptance Criteria

This task is complete when:

No unauthenticated access to static assets exists

Execution steps cannot be completed out of order

Email reuse is impossible at both DB and API layers

Shared account UI loads instantly on page navigation

All changes are cohesive, minimal, and production-safe

Make changes incrementally, validate assumptions against the existing codebase, and prefer correctness and clarity over abstraction.