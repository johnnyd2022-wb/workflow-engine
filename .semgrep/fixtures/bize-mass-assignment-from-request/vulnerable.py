"""Fixture: the vulnerable form the rule bize-mass-assignment-from-request must FIRE on.

Not imported anywhere — this file exists solely so the learning-loop verifier
(scripts/rule_candidates.py) can prove the rule catches the real bug it was born from.
"""

from flask import request

from app.core.db.models.user import User


def create_user():
    # VULNERABLE: the client controls every column, including org_id / is_admin.
    user = User(**request.json)
    return user


def create_user_via_getter():
    # VULNERABLE: same hole through request.get_json().
    org = User(**request.get_json())
    return org
