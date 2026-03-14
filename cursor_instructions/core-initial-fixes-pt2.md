Goal:
Finalize auth and static asset handling with zero architectural changes. Resolve remaining edge risks only.

1. Static Asset Fallback Hardening (CRITICAL)

In core/backend/backend.py:

Remove or replace any usage of current_app.send_static_file(...)

Do not fall back to Flask’s global static handler

If fallback is required, use send_from_directory from a known directory and keep @requires_auth guarantees intact

If fallback is not strictly required, remove it entirely and return 404.

2. Normalize Static Validation Logic

Ensure all static-serving routes (ui/shared, core JS, core CSS):

Reject .., /, \

Use safe_join for validation only

Use send_from_directory for file IO

Return:

400 for invalid paths

404 for missing files

500 only for unexpected failures

Make behavior consistent across all routes.

3. Verify Rate Limit + Lockout Ordering

Audit login flow to confirm:

Account lockout check occurs before authentication

Rate limiting does not leak user existence via timing or error shape

All login failures return the same response body

Do not refactor logic — only adjust ordering if required.

4. Phone Number Normalization Consistency

Ensure:

Phone number normalization logic is reused for:

Signup

Settings updates

Admin user creation

DB column supports up to 15 digits

Stored value is digits-only

5. Final Logging Sanity Pass

Confirm:

Missing static files → info

Validation failures → no stack traces

Unexpected failures → logger.exception

No logs contain secrets or credential pairs

6. No Architecture Changes

Constraints:

No new dependencies

No auth model changes

No new middleware

No refactors

Minimal, surgical fixes only.