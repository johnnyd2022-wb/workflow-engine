"""Fixture: the fixed form the rule bize-mass-assignment-from-request must stay SILENT on.

If the rule fires here it over-matches — it would flag correct code and train everyone to
ignore it. The verifier asserts zero findings against this file.
"""

from flask import request

from app.core.db.models.user import User


def create_user():
    data = request.get_json()
    # FIXED: explicit allowlist — the client cannot set org_id, is_admin, or id.
    user = User(email=data["email"], name=data["name"])
    return user
