# Final Session & Security Hardening Review – Closure Checks

Cursor Instructions: Final Session Security Tweaks
1. Consolidate session activity update to after_request

Goal: Avoid writing session data twice on every authenticated request (before_request + after_request). Only update last_activity_at in after_request.

Instructions:

In session_security.py:

In @app.before_request:

# Remove session write logic
# Old:
session["last_activity_at"] = datetime.utcnow().isoformat()
session.modified = True

# Keep only reading logic for inactivity enforcement:
last_activity_str = session.get("last_activity_at")
if last_activity_str:
    try:
        last_activity = datetime.fromisoformat(last_activity_str)
        time_since_activity = datetime.utcnow() - last_activity
        if time_since_activity > timedelta(minutes=timeout_minutes):
            logger.info(f"Session expired due to inactivity for user {user_id}")
            session.clear()
            session.modified = True
            # handle redirect / API JSON as before
    except ValueError:
        # Reset on invalid format
        session["last_activity_at"] = datetime.utcnow().isoformat()


In @app.after_request:

# Keep writing activity here for all authenticated requests
user_id = session.get("user_id")
if user_id:
    session["last_activity_at"] = datetime.utcnow().isoformat()
    session.modified = True


Comment:

# Single authoritative update of last_activity_at occurs after the view returns,
# ensuring 4xx/5xx responses still update inactivity without redundant writes.


Rationale:

Reduces duplicate session serialization and Set-Cookie headers.

Ensures inactivity timeout enforcement remains correct.

Aligns with standard industry practice (Google/GitHub).

2. Set minimum session timeout to 5 minutes

Goal: Align MIN_SESSION_TIMEOUT with common industry practice.

In session_security.py:

MIN_SESSION_TIMEOUT_MINUTES = 5  # Minimum 5 minutes


In db/models/user.py (if default min is referenced):

Ensure any UI or default fallback values also respect the new minimum of 5 minutes.

Comment:

# Conservative lower bound for user-configurable session timeout
# Any value below 5 minutes is automatically capped

✅ Notes / Acceptance

After these changes, last_activity_at is only written once per request.

Inactivity timeout enforcement and SPA/API 401 behavior are unchanged.

Session defaults:

Default: 24 hours

Min: 5 minutes

Max: 30 days

Existing long-session warnings / 2FA checks remain unaffected.

This is the final step before fully closing session security hardening.