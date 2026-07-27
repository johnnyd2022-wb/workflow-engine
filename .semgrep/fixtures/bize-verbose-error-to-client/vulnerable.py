# Fixture: the code the rule bize-verbose-error-to-client must FIRE on.
#
# Real pre-patch shape from app/api/routes/org_routes.py (update_org / list_users /
# delete_user): the exception object is interpolated straight into the JSON error body
# sent back to the API client, leaking whatever the exception's str() happens to contain
# (a raw DB driver message, a file path, a SQL fragment, ...).
from flask import jsonify


def update_org():
    try:
        do_the_update()
    except Exception as e:
        return jsonify({"error": f"Failed to update organisation: {str(e)}"}), 500


def list_users():
    try:
        return jsonify({"users": fetch_users()}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to list users: {str(e)}"}), 500
