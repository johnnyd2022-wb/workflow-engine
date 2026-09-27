"""Staff roles, permissions, and the one table that says who may call what (plan item 0.4).

How it works:

- A **permission** is a named capability ("sales.view", "production.record", ...).
- A **role** is a fixed set of permissions (``ROLE_PERMISSIONS``). Users have one role.
- ``POLICY`` maps every Flask endpoint to what it requires. The first matching rule wins.
  An endpoint no rule matches is **denied** (and logged): new routes are closed until
  someone decides who should reach them. ``tests/test_access_policy.py`` walks the live URL
  map and fails if any endpoint falls through to that default, so the decision is made in
  review rather than discovered in production.
- ``setup_access_policy`` enforces it in one ``before_request`` hook for signed-in users.
  Unauthenticated requests are left to each route's existing ``@requires_auth``.

The table lives here, keyed on endpoint names, rather than as a decorator on every route:
the feature-slicing carve (plan 5.1) is moving route code between files, and one table
keeps that churn out of the permission model. When a slice gets its own blueprint the
endpoint names change and the coverage test says exactly which rules to update.

The UI hides what a role can't use (``can()`` in templates, ``permissions`` on /auth/me),
but this hook is the source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime
from fnmatch import fnmatchcase

from flask import g, jsonify, redirect, request, session

from app.core.db.models.user import UserRole
from app.observability import get_logger

logger = get_logger(__name__)

# --- permissions -------------------------------------------------------------------------

PERMISSIONS: dict[str, str] = {
    "production.view": "See workflows, batches, steps and production history",
    "production.record": "Start batches, complete steps, attach evidence, manage production tasks",
    "production.design": "Create and change workflows and their steps and documents",
    "inventory.view": "See stock on hand, suppliers and traceability",
    "inventory.adjust": "Receive, edit, adjust and remove stock; manage suppliers",
    "sales.view": "See customers, invoices and revenue",
    "sales.record": "Add customer notes and tasks; create and authorise invoices",
    "sales.manage": "Connect Xero, map products, configure sales traceability",
    "compliance.view": "See compliance checks, evidence and reports",
    "compliance.record": "Log checks, attach evidence and sign off compliance records",
    "compliance.manage": "Configure compliance modules and their rules",
    "users.manage": "Invite and remove people, change roles and organisation details",
    "settings.manage": "Maintenance actions such as initialising or resetting data",
}

_ALL = frozenset(PERMISSIONS)

ROLE_PERMISSIONS: dict[UserRole, frozenset[str]] = {
    UserRole.ADMIN: _ALL,
    # "Staff": exactly what a member could do before roles existed, i.e. everything except
    # the routes that were already admin-only (compliance configuration, users, org).
    UserRole.MEMBER: _ALL - {"users.manage", "settings.manage", "compliance.manage"},
    UserRole.PRODUCTION: frozenset(
        {
            "production.view",
            "production.record",
            "inventory.view",
            "inventory.adjust",
            "compliance.view",
            "compliance.record",  # cleaning logs, checks done on the floor
        }
    ),
    UserRole.COMPLIANCE: frozenset(
        {
            "compliance.view",
            "compliance.record",
            "compliance.manage",
            "production.view",
            "inventory.view",
        }
    ),
    UserRole.SALES: frozenset({"sales.view", "sales.record", "inventory.view"}),
    UserRole.AUDITOR: frozenset({"production.view", "inventory.view", "sales.view", "compliance.view"}),
}

ROLE_LABELS: dict[UserRole, str] = {
    UserRole.ADMIN: "Admin",
    UserRole.MEMBER: "Staff",
    UserRole.PRODUCTION: "Production",
    UserRole.COMPLIANCE: "Compliance",
    UserRole.SALES: "Sales",
    UserRole.AUDITOR: "Auditor",
}

ROLE_DESCRIPTIONS: dict[UserRole, str] = {
    UserRole.ADMIN: "Everything, including people, roles and settings.",
    UserRole.MEMBER: "Everything except people, roles and compliance configuration.",
    UserRole.PRODUCTION: "Record batches, steps, stock and floor checks. No sales or revenue.",
    UserRole.COMPLIANCE: "Run compliance; read-only production and stock. No sales or revenue.",
    UserRole.SALES: "Customers, invoices and finished stock on hand. No recipes or production.",
    UserRole.AUDITOR: "Read-only access to production, stock, sales and compliance, until a set date.",
}


def permissions_for(user) -> frozenset[str]:
    if user is None:
        return frozenset()
    return ROLE_PERMISSIONS.get(getattr(user, "role", None), frozenset())


def has_permission(user, *required: str) -> bool:
    """True if ``user`` holds any of ``required``."""
    held = permissions_for(user)
    return any(p in held for p in required)


def access_expired(user, now: datetime | None = None) -> bool:
    expires = getattr(user, "access_expires_at", None)
    if expires is None:
        return False
    return (now or datetime.now(UTC)) >= expires


# --- the policy table --------------------------------------------------------------------

PUBLIC = "public"  # anyone, signed in or not
SIGNED_IN = "signed_in"  # any signed-in user, whatever their role

_READ = frozenset({"GET", "HEAD", "OPTIONS"})
ANY_WORKSPACE = ("production.view", "inventory.view", "sales.view", "compliance.view")

# (endpoint glob, methods or None for all, requirement). First match wins, so specific
# rules come before the broad ones under them. A requirement is PUBLIC, SIGNED_IN, a
# permission, or a tuple meaning "any of these".
POLICY: list[tuple[str, frozenset[str] | None, object]] = [
    # --- public: landing, static assets, sign-in, telemetry ingest
    ("index", None, PUBLIC),
    ("favicon", None, PUBLIC),
    ("landing_diagram", None, PUBLIC),
    ("healthcheck", None, PUBLIC),
    ("static", None, PUBLIC),
    ("*.static", None, PUBLIC),
    ("serve_*", None, PUBLIC),
    ("*.serve_*", None, PUBLIC),
    ("ingest_faro_telemetry", None, PUBLIC),
    ("ingest_posthog_telemetry", None, PUBLIC),
    ("auth.login", None, PUBLIC),
    ("auth.signup", None, PUBLIC),
    ("auth.verify_two_factor", None, PUBLIC),
    ("auth.get_current_user", None, PUBLIC),
    ("auth.logout", None, PUBLIC),
    ("auth.check_password_policy", None, PUBLIC),
    ("auth.accept_invite", None, PUBLIC),
    ("invite.accept_invite_page", None, PUBLIC),
    # --- your own account, and pages every role lands on
    ("auth.*", None, SIGNED_IN),
    ("dashboard", None, SIGNED_IN),  # /dashboard -> /core/dashboard
    ("core.dashboard", None, SIGNED_IN),
    ("core.get_dashboard_summary", None, SIGNED_IN),  # sections filtered by permission
    ("core.settings", None, SIGNED_IN),
    ("core.get_allowed_units", None, SIGNED_IN),
    ("org.get_current_org", _READ, SIGNED_IN),
    ("org.list_users", _READ, SIGNED_IN),  # assignee pickers on tasks and cases
    ("core.notifications_page", None, ANY_WORKSPACE),
    ("core.list_system_findings", None, ANY_WORKSPACE),
    ("core.get_changes", None, ANY_WORKSPACE),  # live-sync feed used across workspaces
    # --- people, organisation and maintenance
    ("org.*", None, "users.manage"),
    ("people_pages.*", None, "users.manage"),
    ("initialize", None, "settings.manage"),
    # Guarded by the route itself: demo org only, local/test environments only.
    ("core.reset_demo_db_route", None, SIGNED_IN),
    # --- go-live stocktake (plan 1.3)
    ("go_live.set_go_live_date", None, "settings.manage"),  # changes which sales are matched
    ("go_live.create_opening_stock", None, "inventory.adjust"),
    ("go_live.go_live_page", None, "inventory.adjust"),
    ("go_live.get_go_live", None, ("inventory.view", "production.view")),
    # --- process design
    ("core.create_process", None, "production.design"),
    ("core.update_process", None, "production.design"),
    ("core.delete_process", None, "production.design"),
    ("core.add_step", None, "production.design"),
    ("core.update_step", None, "production.design"),
    ("core.delete_step", None, "production.design"),
    ("core.reorder_steps", None, "production.design"),
    ("core.flows_create*", None, "production.design"),
    ("core.process_docs_upload", None, "production.design"),
    ("core.process_docs_inline", None, "production.design"),
    ("core.process_docs_delete", None, "production.design"),
    ("process_templates.process_templates_api.copy_process_template", None, "production.design"),
    ("process_templates.*", _READ, "production.design"),
    # --- recording production
    ("core.create_execution", None, "production.record"),
    ("core.complete_step", None, "production.record"),
    ("core.flows_batches_start", None, "production.record"),
    ("core.evidence_upload", None, "production.record"),
    ("core.evidence_delete", None, "production.record"),
    ("core.record_wastage", None, "production.record"),
    ("core.reconcile_via_*", None, "production.record"),
    ("core.inventory_dispose*", None, "production.record"),
    ("core.*task*", _READ, "production.view"),
    ("core.*task*", None, "production.record"),
    ("operational_cases.*", _READ, "production.view"),
    ("operational_cases.*", None, "production.record"),
    # --- stock
    ("core.create_inventory_item", None, "inventory.adjust"),
    ("core.update_inventory_item", None, "inventory.adjust"),
    ("core.delete_inventory_item", None, "inventory.adjust"),
    ("core.adjust_inventory_item_quantity", None, "inventory.adjust"),
    ("core.csv_validate", None, "inventory.adjust"),
    ("core.csv_commit", None, "inventory.adjust"),
    ("core.consume_final_product_fifo", None, "inventory.adjust"),
    ("core.inventory_add*", None, "inventory.adjust"),
    ("core.get_matching_untracked_for_add", None, "inventory.adjust"),
    ("core.list_core_suppliers", None, "inventory.view"),  # before the write glob below
    ("core.*_core_supplier*", None, "inventory.adjust"),  # create/update/delete/import
    ("core.suppliers_page", None, "inventory.view"),
    ("core.inventory_live_view", None, "inventory.view"),
    ("core.inventory_view", None, "inventory.view"),
    ("core.list_inventory", None, "inventory.view"),
    ("core.barcode_lookup", None, "inventory.view"),
    ("core.decode_barcode", None, "inventory.view"),  # POST, but read-only
    ("core.list_expired_materials", None, "inventory.view"),
    ("core.list_out_of_stock_raw_materials", None, "inventory.view"),
    ("core.list_output_expiry", None, "inventory.view"),
    ("core.list_output_ready_date", None, "inventory.view"),
    ("core.list_untracked_items", None, "inventory.view"),
    ("core.list_wastage", None, "inventory.view"),
    # traceability (includes the customers a batch went to, for recalls)
    ("core.sourcemap", None, "inventory.view"),
    ("core.sourcemap_objects", None, "inventory.view"),
    ("core.sourcemap_trace", None, "inventory.view"),  # POST, but read-only
    ("core.trace_*", None, "inventory.view"),
    # --- reading production
    ("core.get_hub_overview", None, ("production.view", "inventory.view")),
    ("core.core", None, ("production.view", "inventory.view")),
    ("core.*", _READ, "production.view"),
    # --- sales
    ("crm.crm_oauth.xero_status", None, "sales.view"),
    ("crm.crm_oauth.*", None, "sales.manage"),
    ("crm.crm_pages.crm_configuration", None, "sales.manage"),
    ("core.integrations", None, "sales.manage"),
    ("crm.crm_api.*mapping*", _READ, "sales.view"),
    ("crm.crm_api.*mapping*", None, "sales.manage"),
    ("crm.crm_api.*traceability_config", _READ, "sales.view"),
    ("crm.crm_api.*traceability_config", None, "sales.manage"),
    ("crm.*", _READ, "sales.view"),
    ("crm.*", None, "sales.record"),
    # --- compliance
    ("compliant.compliant_api.capture_context", None, ("production.view", "compliance.view")),
    ("compliant.compliant_tools.*", None, ("production.view", "compliance.view")),  # calculators
    ("compliant.compliant_api.update_profile", None, "compliance.manage"),
    ("compliant.compliant_api.update_abv_rules", None, "compliance.manage"),
    ("compliant.compliant_api.update_np3_check_settings", None, "compliance.manage"),
    ("compliant.compliant_api.create_alcohol_product", None, "compliance.manage"),
    ("compliant.compliant_pages.nz_alcohol_configuration", None, "compliance.manage"),
    ("compliant.*", _READ, "compliance.view"),
    ("compliant.*", None, "compliance.record"),
]

DENY = "deny"


def requirement_for(endpoint: str, method: str) -> object:
    """What ``endpoint`` requires for ``method``; ``DENY`` when no rule matches."""
    method = method.upper()
    for pattern, methods, requirement in POLICY:
        if methods is not None and method not in methods:
            continue
        if fnmatchcase(endpoint, pattern):
            return requirement
    return DENY


def allows(user, endpoint: str, method: str) -> bool:
    requirement = requirement_for(endpoint, method)
    if requirement == PUBLIC:
        return True
    if requirement == DENY or user is None:
        return False
    if requirement == SIGNED_IN:
        return True
    required = requirement if isinstance(requirement, tuple) else (requirement,)
    return has_permission(user, *required)


def setup_access_policy(app) -> None:
    """Enforce ``POLICY`` for signed-in users. Register after tenant context."""

    @app.context_processor
    def _inject_can():
        user = getattr(g, "current_user", None)
        return {"can": lambda *perms: has_permission(user, *perms)}

    @app.before_request
    def enforce_access_policy():
        user = getattr(g, "current_user", None)
        endpoint = request.endpoint
        if user is None or not endpoint:
            return None
        if access_expired(user) and requirement_for(endpoint, request.method) != PUBLIC:
            # Time-limited access (e.g. an Auditor) has ended: end the session too.
            logger.info("access_expired_session_ended", user_id=str(user.id))
            session.clear()  # nosemgrep: bize-session-clear-without-rotate
            session.modified = True
            return jsonify({"error": "Your access to this organisation has ended.", "code": "access_expired"}), 401
        if allows(user, endpoint, request.method):
            return None

        requirement = requirement_for(endpoint, request.method)
        if requirement == DENY:
            logger.error("access_policy_unclassified_endpoint", endpoint=endpoint, method=request.method)
        else:
            logger.warning(
                "access_denied",
                reason="missing_permission",
                endpoint=endpoint,
                required=list(requirement) if isinstance(requirement, tuple) else requirement,
                user_role=getattr(user.role, "value", None),
                user_id=str(user.id),
            )
        is_api = request.path.startswith(("/api/", "/auth/", "/org")) or request.is_json
        if request.method == "GET" and not is_api and request.accept_mimetypes.accept_html:
            # A page the role can't use: send them to the dashboard, which every role has.
            return redirect("/core/dashboard?denied=1")
        return jsonify({"error": "You don't have permission to do this.", "code": "permission_denied"}), 403
