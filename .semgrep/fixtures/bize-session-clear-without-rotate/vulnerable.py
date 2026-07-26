# Fixture: the code the rule bize-session-clear-without-rotate must FIRE on.
#
# Real shape this was found in: app/api/routes/auth_routes.py's change_password() before
# the auth security audit (F2). It hand-rolled session.clear() + a manual key-by-key
# restore instead of calling the shared rotate_session() helper. session.clear() wipes
# every key, including the internal `_permanent` key that backs `session.permanent`, so
# the persistent (30-day) session cookie silently downgrades to a browser-session-only
# cookie after this runs — a functional/security regression nothing else in the diff
# would catch.

from flask import session


def change_password(auth_service, updated_user):
    new_session_data = auth_service.generate_session(updated_user)
    session.clear()
    for key, value in new_session_data.items():
        session[key] = value
    return {"message": "Password updated successfully"}
