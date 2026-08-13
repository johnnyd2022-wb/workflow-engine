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
    # Flask's request.blueprint returns the full dot-joined path for a nested
    # blueprint (parent.child), not just the child's own name — e.g. registering
    # api_bp/page_bp under create_dilution_calculator_blueprint()'s parent
    # "dilution_calculator" makes request.blueprint "dilution_calculator.
    # dilution_calculator_api" / "...dilution_calculator_pages", never the bare
    # child name. Map the dotted paths explicitly so these requests land under
    # "dilution_calculator" instead of silently falling through to DEFAULT_FEATURE.
    "dilution_calculator.dilution_calculator_api": "dilution_calculator",
    "dilution_calculator.dilution_calculator_pages": "dilution_calculator",
    # Same nested-blueprint shape for CRM: create_crm_blueprint() registers
    # oauth_bp/api_bp/page_bp under a parent "crm" blueprint, so real requests
    # carry "crm.crm_api" / "crm.crm_oauth" / "crm.crm_pages" — the flat
    # "crm_api"/"crm_oauth"/"crm_pages" keys above never match a real request.
    "crm.crm_api": "crm",
    "crm.crm_oauth": "crm",
    "crm.crm_pages": "crm",
}
DEFAULT_FEATURE = "platform"


def feature_for_request() -> str:
    """Resolve feature label for the current request."""
    if not has_request_context():
        return DEFAULT_FEATURE
    return BLUEPRINT_FEATURE.get(request.blueprint, DEFAULT_FEATURE)
