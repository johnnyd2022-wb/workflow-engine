"""Request-scoped observability context helpers."""

from __future__ import annotations

from flask import has_request_context, request

BLUEPRINT_FEATURE = {
    "auth": "auth",
    "org": "org",
    "core": "core",
    "crm": "crm",
    "crm_api": "crm",
    "crm_oauth": "crm",
    "crm_pages": "crm",
    "workflow_engine": "workflow_engine",
}
DEFAULT_FEATURE = "platform"


def feature_for_request() -> str:
    """Resolve feature label for the current request."""
    if not has_request_context():
        return DEFAULT_FEATURE
    return BLUEPRINT_FEATURE.get(request.blueprint, DEFAULT_FEATURE)
