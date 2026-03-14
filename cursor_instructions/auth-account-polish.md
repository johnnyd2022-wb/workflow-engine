Context

This is a Flask + SQLAlchemy + Alembic application with session-based authentication, a multi-tenant user model, and a shared frontend component (account-info) that loads user/org identity and provides logout. The system is production-bound behind Cloudflare WAF.

The goal of this task is to polish and harden the auth + account flows without changing core architecture or introducing new dependencies.

Objectives (in priority order)
1. Make the shared account-info component render immediately

Problem

The shared account-info component currently appears ~1 second after page render.

This is caused by async HTML fetching + polling for JS readiness.

Required outcome

The component shell (HTML structure) should render synchronously with page load, with placeholders if needed.

User/org data can load asynchronously, but the component frame must not pop in late.

Guidelines

Eliminate polling loops and race conditions around DOMContentLoaded and window.loadAccountInfo.

Prefer one of:

Server-rendered HTML shell (static include)

Inline HTML injection at page load with JS-only data hydration

Ensure:

No duplicate components

No flicker

No blocking of page render

Keep the component reusable across dashboard, settings, and future pages.

2. Centralize and simplify account-info initialization

Problem

Multiple pages manually fetch and initialize the shared component.

Initialization logic is duplicated and fragile.

Required outcome

A single, deterministic initialization path for the account-info component.

One entry point that:

Ensures the component exists

Loads user/org data

Handles unauthenticated states cleanly

Guidelines

Export one clear public initializer (e.g. initAccountInfo(containerId)).

Avoid global timing assumptions.

Ensure it is safe to call exactly once per page.

3. Prevent email reuse across the system (race-condition safe)

Problem

Email uniqueness is enforced at DB level, but:

Email updates do not proactively check for conflicts.

Integrity errors can surface as 500s.

Concurrent updates can race.

Required outcome

Email addresses must never be reusable across active users.

Conflicts must return a clear 409-style error, not 500.

Behavior must be race-condition safe.

Guidelines

Rely on DB uniqueness as the final authority.

Catch and handle IntegrityError during email updates.

Return a deterministic API error for “email already in use”.

Ensure session state is not mutated if the update fails.

Keep logic centralized (repository or service layer).

4. Normalize email update behavior across signup and settings

Problem

Email validation and uniqueness logic is duplicated.

Behavior differs slightly between signup and update.

Required outcome

One consistent validation and uniqueness rule set for:

Signup

Settings update

No divergent logic paths.

Guidelines

Reuse existing abstractions where possible.

Avoid adding new frameworks or services.

Do not change public API shapes unless required.

5. Improve frontend feedback for email conflicts

Problem

Email conflicts may surface as generic errors.

Required outcome

If an email is already in use:

The user sees a clear, actionable message

UI state remains consistent

No partial updates are reflected

Guidelines

Handle 409-style responses explicitly in frontend logic.

Do not leak backend exception details.

Maintain existing UI patterns for success/error messaging.

Non-goals (do NOT implement)

Do NOT add email verification flows

Do NOT add phone verification or SMS

Do NOT introduce external auth providers

Do NOT refactor the entire auth system

Do NOT change session mechanics

Acceptance criteria

Account-info component renders instantly with page layout

No delayed pop-in or polling-based initialization

Email uniqueness is enforced cleanly and safely

Email update conflicts return deterministic user-facing errors

No new regressions in signup, settings, or logout flows

Code remains idiomatic to the existing Flask + SQLAlchemy stack

Deliverable
Apply the changes directly in code. Update backend, frontend, and shared UI components as needed to meet the above objectives in one cohesive pass.