You are working in a Flask-based public SaaS authentication system.
Harden the existing authentication and session handling based on the following requirements.
Do not break existing behaviour; build on top of it.

Review the existing dir structure and ensure all code goes into relevant areas.

1. Authentication & Security Hardening
Rate limiting

Add rate limiting to:

POST /auth/login

POST /auth/verify-2fa

Use IP-based throttling with sensible defaults:

Login: max 5 attempts per 15 minutes

2FA verify: max 5 attempts per 5 minutes

Ensure rate-limit violations return a generic error message (no internal details).

Error handling

Do not return raw exception strings to clients.

Replace str(e) responses with:

{"error": "Internal server error"} for 500s

Log full exceptions server-side only.

Email / user enumeration protection

Normalize login errors so that invalid email vs invalid password are indistinguishable.

Avoid revealing whether an account exists.

2. Pending 2FA Session Expiry

Add an expiry mechanism to pending_2fa_user_id.

Store:

pending_2fa_user_id

pending_2fa_created_at (UTC timestamp)

Enforce expiry (e.g. 5–10 minutes):

If expired, clear all auth-related session state and return:

{"error": "2FA session expired. Please log in again."}


Apply this check in /auth/verify-2fa.

3. Session Security Improvements
Session fixation protection

Rotate the session identifier on:

Successful login

Successful 2FA verification

Cookie hardening (production-safe)

Ensure Flask session cookies are configured with:

Secure

HttpOnly

SameSite=Strict

4. Inactivity-Based Session Timeout (Core Requirement)
Default behaviour

Implement 10 minutes of inactivity timeout by default.

Inactivity means no user interaction, including:

No HTTP requests

No frontend user input (mouse, keyboard, clicks)

When exceeded:

Automatically log the user out

Clear session

Return a 401 on the next request

Backend implementation

Track last_activity_at in the session.

Update it on every authenticated request via middleware.

Compare current time vs last_activity_at.

If exceeded user-specific timeout:

Clear session

Treat user as logged out

5. User-Configurable Session Timeout
Backend

Add a user profile field:

session_timeout_minutes

Default value: 10

Create an internal API endpoint (authenticated, non-public) to:

Get and update this value for the current user

Validate reasonable bounds (e.g. min 5, max 240 minutes)

Middleware behaviour

Use the user’s configured timeout instead of the default.

Fall back to default if unset.

6. Frontend Integration
Activity tracking

Implement frontend activity detection:

Mouse movement

Key presses

Clicks

Periodically notify backend (or rely on normal API traffic) to keep session alive.

User profile UI

Add a Session Timeout setting in the user profile screen:

Numeric input (minutes)

Clear explanation: “Automatically log me out after X minutes of inactivity”

Persist changes via the new backend endpoint.

Reflect current value on load.

UX

When a session expires:

Show a clear message: “Your session expired due to inactivity.”

Redirect to login.

7. Maintainability & Consistency

Keep code modular:

Middleware for session expiry

Services for auth logic

Add docstrings and comments where behaviour is non-obvious.

Keep JSON response structures consistent across auth endpoints.

8. Non-Goals / Constraints

Do not introduce breaking changes to existing auth flows.

Do not log sensitive data (passwords, 2FA tokens, secrets).

Do not expose internal configuration endpoints publicly.

Outcome:
A hardened, production-grade authentication and session system suitable for a public SaaS, with secure 2FA handling, rate limiting, inactivity-based logout, and user-configurable session timeout.