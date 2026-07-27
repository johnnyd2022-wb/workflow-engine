# Fixture: the code the rule bize-session-clear-without-rotate must stay SILENT on.
#
# Fixed shape: re-establishing an authenticated session goes through the shared
# rotate_session() helper (which clears the session AND re-sets session.permanent = True)
# instead of a bare session.clear() + manual restore. This is the same pattern already
# used by login/signup/verify-2fa, so there's one place that owns "how do we rotate a
# session safely" instead of every call site re-deriving it (and forgetting a bit).

from flask import session


def rotate_session():
    session.clear()
    session.permanent = True


def change_password(auth_service, updated_user):
    new_session_data = auth_service.generate_session(updated_user)
    rotate_session()
    session.update(new_session_data)
    return {"message": "Password updated successfully"}
