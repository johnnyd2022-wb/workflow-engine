# Fixture: the code the rule bize-verbose-error-to-client must stay SILENT on.
#
# Post-patch shape: the exception is logged server-side only (logger.exception captures the
# full traceback for operators); the client gets a fixed, generic message with no exception
# detail in it.
from flask import jsonify

from app.observability import get_logger

logger = get_logger(__name__)


def update_org():
    try:
        do_the_update()
    except Exception:
        logger.exception("Error updating organisation")
        return jsonify({"error": "Failed to update organisation"}), 500


def list_users():
    try:
        return jsonify({"users": fetch_users()}), 200
    except Exception:
        logger.exception("Error listing users")
        return jsonify({"error": "Failed to list users"}), 500
