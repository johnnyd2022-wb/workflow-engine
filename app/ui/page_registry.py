"""The one list of in-app pages: where each lives in the navigation and what it needs.

The sidebar, section sub-navs, breadcrumbs and the boosted-navigation e2e test all read this,
so none of them can drift from the others (docs/ux-overhaul-plan.md). The permission a page
needs is not repeated here: `requirement()` asks `access_policy`, the same source the
request gate uses.
"""

from __future__ import annotations

from dataclasses import dataclass

SECTIONS = ("dashboard", "production", "compliance", "sales", "settings")


@dataclass(frozen=True)
class Page:
    path: str
    section: str  # one of SECTIONS: the sidebar tab this page belongs to
    tab: str | None  # the section sub-nav tab it is shown under; None for a section root or a page with no tab
    title: str
    parent: str | None = None  # path of the page a breadcrumb leads back to; None for a tab's own page
    feature: str | None = None  # feature flag/subscription the page needs: "crm" or "compliant"


PAGES: tuple[Page, ...] = (
    Page("/core/dashboard", "dashboard", None, "Dashboard", None, None),
    Page("/core/go-live", "dashboard", None, "Go live", None, None),
    Page("/core", "production", "overview", "Production overview", None, None),
    Page("/core/cases", "production", "overview", "Cases", None, None),
    Page("/core/cases/new", "production", "overview", "New case", "/core/cases", None),
    Page("/core/tasks", "production", "overview", "Tasks", None, None),
    Page("/core/planner", "production", "planner", "Production demand", None, None),
    Page("/core/planner/board", "production", "planner", "Production board", "/core/planner", None),
    Page("/core/executions/live", "production", "batches", "Batches", None, None),
    Page("/core/processes", "production", "workflows", "Product workflows", None, None),
    Page("/core/flows", "production", "workflows", "Workflow editor", "/core/processes", None),
    Page("/core/flows/create/start", "production", "workflows", "Create a workflow", "/core/processes", None),
    Page(
        "/core/flows/create/template-catalog",
        "production",
        "workflows",
        "Start from a template",
        "/core/processes",
        None,
    ),
    Page("/core/inventory/view", "production", "inventory", "Inventory", None, None),
    Page("/core/inventory/live", "production", "inventory", "Live inventory", "/core/inventory/view", None),
    Page("/core/inventory/add", "production", "inventory", "Add to inventory", "/core/inventory/view", None),
    Page(
        "/core/inventory/add/manual", "production", "inventory", "Add inventory manually", "/core/inventory/add", None
    ),
    Page(
        "/core/inventory/add/barcode",
        "production",
        "inventory",
        "Add inventory by barcode",
        "/core/inventory/add",
        None,
    ),
    Page(
        "/core/inventory/add/csv", "production", "inventory", "Add inventory from a file", "/core/inventory/add", None
    ),
    Page("/core/inventory/dispose", "production", "inventory", "Record disposal", "/core/inventory/view", None),
    Page("/core/stocktake", "production", "inventory", "Stocktake", "/core/inventory/view", None),
    Page("/core/sourcemap", "production", "inventory", "Trace and recall", "/core/inventory/view", None),
    Page("/core/site-transfers", "production", "inventory", "Stock transfers", "/core/inventory/view", None),
    Page("/core/contracts", "production", "contracts", "Contract orders", None, None),
    Page("/core/contracts/materials", "production", "contracts", "Customer materials", "/core/contracts", None),
    Page("/core/suppliers", "production", "suppliers", "Suppliers", None, None),
    Page("/compliant", "compliance", "overview", "Compliance", None, "compliant"),
    Page("/compliant/nz-alcohol", "compliance", "overview", "NZ alcohol", None, "compliant"),
    Page("/compliant/nz-alcohol/np3-audit", "compliance", "np3", "NP3 food safety", None, "compliant"),
    Page(
        "/compliant/nz-alcohol/food-safety",
        "compliance",
        "np3",
        "NP3 food safety",
        "/compliant/nz-alcohol/np3-audit",
        "compliant",
    ),
    Page("/compliant/nz-alcohol/customs", "compliance", "customs", "Customs", None, "compliant"),
    Page(
        "/compliant/nz-alcohol/evidence",
        "compliance",
        "customs",
        "Customs",
        "/compliant/nz-alcohol/customs",
        "compliant",
    ),
    Page("/compliant/nz-alcohol/licensing", "compliance", "licensing", "Licensing", None, "compliant"),
    Page("/compliant/nz-alcohol/premises", "compliance", "premises", "Premises", None, "compliant"),
    Page(
        "/compliant/nz-alcohol/food-registrations",
        "compliance",
        "food-registrations",
        "Food registrations",
        None,
        "compliant",
    ),
    Page("/compliant/tools", "compliance", "tools", "Tools", None, "compliant"),
    Page(
        "/compliant/nz-alcohol/configuration", "compliance", "configuration", "Compliance settings", None, "compliant"
    ),
    Page("/crm", "sales", "overview", "Sales overview", None, "crm"),
    Page("/crm/customers", "sales", "customers", "Customers", None, "crm"),
    Page("/crm/tasks", "sales", "tasks", "Sales tasks", None, "crm"),
    Page("/crm/matching", "sales", "matching", "Batch matching", None, "crm"),
    Page("/crm/analytics", "sales", "analytics", "Analytics", None, "crm"),
    Page("/core/settings", "settings", "account", "My account", None, None),
    Page("/core/people", "settings", "people", "People and roles", None, None),
    Page("/core/sites", "settings", "sites", "Sites", None, None),
    Page("/core/integrations", "settings", "integrations", "Integrations", None, None),
    Page("/crm/configuration", "sales", "configuration", "Sales settings", None, "crm"),
    Page("/core/notifications", "settings", "notifications", "Notifications", None, None),
    Page("/core/tasks/configuration", "settings", "section-settings", "Task settings", None, None),
)


def page_for(path: str) -> Page | None:
    return next((page for page in PAGES if page.path == path), None)


def requirement(page: Page, app, method: str = "GET"):
    """What `access_policy` requires to open ``page``: a permission, a tuple of alternatives, or a sentinel."""
    from app.core.security.access_policy import requirement_for

    endpoint, _ = app.url_map.bind("localhost").match(page.path, method=method)
    return requirement_for(endpoint, method)


@dataclass(frozen=True)
class Tab:
    """One entry of a section's sub-nav. ``requires`` is any-of (empty = everyone); ``when`` names a
    condition in `app.ui.navigation` (for tabs that depend on the organisation's setup)."""

    key: str
    label: str
    path: str
    requires: tuple[str, ...] = ()
    when: str | None = None


SECTION_LABELS = {
    "dashboard": "Dashboard",
    "production": "Production",
    "compliance": "Compliance",
    "sales": "Sales",
    "settings": "Settings",
}

SECTION_TABS: dict[str, tuple[Tab, ...]] = {
    "production": (
        Tab("overview", "Overview", "/core", ("production.view", "inventory.view")),
        Tab("planner", "Planner", "/core/planner", ("production.view",)),
        Tab("batches", "Batches", "/core/executions/live", ("production.view",)),
        Tab("workflows", "Workflows", "/core/processes", ("production.view",)),
        Tab("inventory", "Inventory", "/core/inventory/view", ("inventory.view",)),
        Tab("contracts", "Contract orders", "/core/contracts", ("sales.view", "production.view")),
        Tab("suppliers", "Suppliers", "/core/suppliers", ("inventory.view",)),
    ),
    "compliance": (
        Tab("overview", "Overview", "/compliant/nz-alcohol", ("compliance.view",)),
        Tab("np3", "Food safety", "/compliant/nz-alcohol/np3-audit", ("compliance.view",), when="food_safety"),
        Tab("customs", "Customs", "/compliant/nz-alcohol/customs", ("compliance.view",)),
        Tab("licensing", "Licensing", "/compliant/nz-alcohol/licensing", ("compliance.view",), when="licensing"),
        Tab("premises", "Premises", "/compliant/nz-alcohol/premises", ("compliance.view",)),
        Tab(
            "food-registrations",
            "Food registrations",
            "/compliant/nz-alcohol/food-registrations",
            ("compliance.view",),
            when="food_safety",
        ),
        Tab("tools", "Tools", "/compliant/tools", ("production.view", "compliance.view")),
        # Secondary workspace action; plan 2.5 also links it from Settings.
        Tab("configuration", "Configuration", "/compliant/nz-alcohol/configuration", ("compliance.manage",)),
    ),
    "sales": (
        Tab("overview", "Overview", "/crm", ("sales.view",)),
        Tab("customers", "Customers", "/crm/customers", ("sales.view",)),
        Tab("tasks", "Tasks", "/crm/tasks", ("sales.view",)),
        Tab("matching", "Batch matching", "/crm/matching", ("sales.view",)),
        Tab("analytics", "Analytics", "/crm/analytics", ("sales.view",)),
        # Secondary workspace action; plan 2.5 moves Xero into Settings > Integrations.
        Tab("configuration", "Configuration", "/crm/configuration", ("sales.manage",)),
    ),
}

# Four primary destinations per workspace. Secondary pages retain their registry
# entries, URLs and permissions; a permitted secondary can stand in for a primary
# that a restricted role cannot open.
WORKSPACE_TAB_GROUPS = {
    "production": (
        ("overview",),
        ("planner", "contracts"),
        ("workflows", "batches"),
        ("inventory", "suppliers"),
    ),
    "compliance": (
        ("overview", "premises", "tools", "configuration"),
        ("np3", "food-registrations"),
        ("customs",),
        ("licensing",),
    ),
    "sales": (("overview", "configuration"), ("customers",), ("tasks",), ("analytics", "matching")),
}
