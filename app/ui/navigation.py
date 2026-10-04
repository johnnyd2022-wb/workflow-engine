"""Which main tab and sub-nav tab a request belongs to, and what the sub-nav shows.

Everything comes from `app.ui.page_registry`; templates only render what this returns
(`shared/sidebar-v2.html`, `shared/section_tabs.html`). See docs/ux-overhaul-plan.md (2.1, 2.2).
"""

from __future__ import annotations

from flask import g, has_request_context, request

from app.core.security.access_policy import has_permission
from app.ui.page_registry import PAGES, SECTION_LABELS, SECTION_TABS, WORKSPACE_TAB_GROUPS, Tab

_BY_PATH = {page.path: page for page in PAGES}


def resolve(path: str) -> tuple[str | None, str | None]:
    """``(section, tab)`` for a URL path: the page itself, else its nearest registered ancestor."""
    path = (path or "/").rstrip("/") or "/"
    page = _BY_PATH.get(path)
    if page is None:
        parts = path.split("/")
        while len(parts) > 2 and page is None:
            parts.pop()
            page = _BY_PATH.get("/".join(parts))
    if page is not None:
        return page.section, page.tab
    return None, None


def _normal(path: str) -> str:
    return (path or "/").rstrip("/") or "/"


def _nearest_page(path: str):
    path = _normal(path)
    parts = path.split("/")
    page = _BY_PATH.get(path)
    while page is None and len(parts) > 2:
        parts.pop()
        page = _BY_PATH.get("/".join(parts))
    return page


def breadcrumbs(path: str, leaf: str | None = None, extra: list[dict] | None = None) -> list[dict]:
    """The trail for a page: its main tab, its sub-nav tab, registered parents, then the page itself.

    Empty for a page that is a main tab or a sub-nav tab's own page (the tabs already say where you
    are). For an unregistered detail URL (an order, a customer, a case) the nearest registered ancestor
    is a link and ``leaf`` names the page; ``extra`` adds links between them (an order above its
    portal-sharing page). Each crumb is ``{"label", "href"}``; the last has ``href`` None.
    """
    path = _normal(path)
    page = _nearest_page(path)
    if page is None:
        return []
    exact = page.path == path
    section = page.section
    tab = next((t for t in SECTION_TABS.get(section, ()) if t.key == page.tab), None)
    if exact and (
        path == _HOME.get(section)
        or (
            tab is not None
            and tab.path == path
            and tab.key in {group[0] for group in WORKSPACE_TAB_GROUPS.get(section, ())}
        )
    ):
        return []
    crumbs = [{"label": SECTION_LABELS[section], "href": _HOME[section]}]
    if tab is not None and tab.path not in {path, crumbs[-1]["href"]}:
        crumbs.append({"label": tab.label, "href": tab.path})
    chain = []
    parent = page.parent if exact else page.path
    while parent:
        found = _BY_PATH.get(parent)
        if found is None:
            break
        chain.append(found)
        parent = found.parent
    for found in reversed(chain):
        if found.path not in {crumb["href"] for crumb in crumbs}:
            crumbs.append({"label": found.title, "href": found.path})
    if exact:
        crumbs.append({"label": page.title, "href": None})
    else:
        crumbs.extend({"label": item["label"], "href": item.get("href")} for item in (extra or []))
        crumbs.append({"label": leaf or "Details", "href": None})
    return crumbs


def _conditions() -> dict[str, bool]:
    """Setup-dependent tabs, read once per request (compliance pages only)."""
    # Cached on the request's own environ: `g` can outlive a request when an app context is reused.
    cached = request.environ.get("bize.nav_conditions")
    if cached is not None:
        return cached
    from uuid import UUID

    from app.core.db import db_session
    from app.features.compliant.routes.page_routes import _food_safety_programme
    from app.features.compliant.service import ComplianceService

    org_id = getattr(g, "org_id", None)
    settings: dict = {}
    if org_id:
        profile = ComplianceService(db_session()).get_profile(UUID(str(org_id)))
        settings = (profile.settings if profile else {}) or {}
    programme = _food_safety_programme(settings)
    conditions = {
        "food_safety": programme != "none",
        "licensing": bool(settings.get("liquor_licence_types")),
        "programme": programme,
    }
    request.environ["bize.nav_conditions"] = conditions
    return conditions


def _permitted(tab: Tab, user) -> bool:
    return not tab.requires or has_permission(user, *tab.requires)


def _hidden(tab: Tab, conditions: dict[str, bool]) -> bool:
    """A setup-dependent tab stays in the page, hidden, so the configuration page can reveal it live."""
    return tab.when is not None and not conditions.get(tab.when)


def section_tabs(section: str | None, user) -> list[Tab]:
    """At most four permitted primary destinations, with role-aware fallbacks."""
    available = {tab.key: tab for tab in SECTION_TABS.get(section or "", ()) if _permitted(tab, user)}
    groups = WORKSPACE_TAB_GROUPS.get(section or "")
    if groups is None:
        return list(available.values())
    tabs = []
    for group in groups:
        key = next((key for key in group if key in available), None)
        if key:
            tabs.append(available[key])
    return tabs


def _primary_key(section: str | None, key: str | None, tabs: list[Tab]) -> str | None:
    for group in WORKSPACE_TAB_GROUPS.get(section or "", ()):
        if key in group:
            return next((tab.key for tab in tabs if tab.key in group), None)
    return key


def _workspace_links(section: str | None, key: str | None, user, conditions: dict) -> list[dict]:
    """Secondary actions on workspace pages, filtered by the same permissions as tabs."""
    all_tabs = SECTION_TABS.get(section or "", ())
    if user is None or request.path not in {tab.path for tab in all_tabs} | {"/compliant"}:
        return []
    groups = WORKSPACE_TAB_GROUPS.get(section or "", ())
    primary_keys = {group[0] for group in groups}
    primary = next((group[0] for group in groups if key in group), key)
    related = {secondary for group in groups if primary == "overview" or primary == group[0] for secondary in group[1:]}
    links = [
        {
            "key": tab.key,
            "label": tab.label,
            "href": tab.path,
            "hidden": _hidden(tab, conditions),
            "food_safety": tab.when == "food_safety",
        }
        for tab in all_tabs
        if tab.key not in primary_keys and tab.key in related and tab.path != request.path and _permitted(tab, user)
    ]
    if section == "production" and primary == "overview" and has_permission(user, "production.view"):
        links.append({"key": "tasks", "label": "Production tasks", "href": "/core/tasks", "hidden": False})
    return links


_HOME = {
    "dashboard": "/core/dashboard",
    "production": "/core",
    "compliance": "/compliant",
    "sales": "/crm",
    "settings": "/core/settings",
}


def section_home(section: str, user) -> str:
    """Where the sidebar sends someone for ``section``: its home page, or the first tab they may open
    when the home page is not theirs to see (a sales-only user's Production starts at Contract orders)."""
    tabs = section_tabs(section, user)
    if not tabs or any(tab.key == "overview" for tab in tabs):
        return _HOME.get(section, "/core/dashboard")
    return tabs[0].path


def nav_context() -> dict:
    """Template variables for the sidebar and the shared sub-nav."""
    if not has_request_context():
        return {}
    user = getattr(g, "current_user", None)
    section, tab_key = resolve(request.path)
    if request.path == "/core" and request.args.get("tab") in {"inventory", "workflows"}:
        tab_key = request.args["tab"]
    tabs = section_tabs(section, user) if user is not None else []
    conditions = _conditions() if section == "compliance" and user is not None else {}
    primary_key = _primary_key(section, tab_key, tabs)
    items = []
    for tab in tabs:
        label = tab.label
        if tab.key == "np3" and conditions.get("programme"):
            label = conditions["programme"].upper()
        items.append(
            {
                "key": tab.key,
                "label": label,
                "href": tab.path,
                "active": tab.key == primary_key,
                "hidden": _hidden(tab, conditions),
                "food_safety": tab.key == "np3",
            }
        )
    return {
        "active_section": section,
        "active_tab": tab_key,
        "section_tabs": items,
        "workspace_links": _workspace_links(section, tab_key, user, conditions),
        "section_label": SECTION_LABELS.get(section or ""),
        "section_home": lambda name: section_home(name, user),
        "nav_breadcrumbs": lambda leaf=None, extra=None: breadcrumbs(request.path, leaf, extra),
    }
