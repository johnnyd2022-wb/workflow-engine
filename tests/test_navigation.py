"""The five-tab sidebar and the shared section sub-nav (docs/ux-overhaul-plan.md 2.1, 2.2)."""

import re
from uuid import uuid4

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.user import UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.ui.navigation import resolve
from app.ui.page_registry import PAGES, SECTION_TABS
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory
from tests.test_compliant_routes import flask_app  # noqa: F401 -- fixture re-export


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/core/dashboard", ("dashboard", None)),
        ("/core", ("production", "overview")),
        ("/core/planner/board", ("production", "planner")),
        ("/core/contracts/4b1d0000-0000-0000-0000-000000000000", ("production", "contracts")),
        ("/core/contracts/4b1d0000-0000-0000-0000-000000000000/portal-sharing", ("production", "contracts")),
        ("/core/cases/abc", ("production", "overview")),
        ("/core/flows/batches/start", ("production", "workflows")),
        ("/crm/customers/123", ("sales", "customers")),
        ("/compliant/nz-alcohol/np3-audit/check/recall-policy", ("compliance", "np3")),
        ("/compliant/nz-alcohol/food-safety", ("compliance", "np3")),
        ("/compliant/nz-alcohol/evidence", ("compliance", "customs")),
        ("/core/people", ("settings", "people")),
        ("/elsewhere", (None, None)),
    ],
)
def test_resolve_finds_the_page_or_its_nearest_registered_ancestor(path, expected):
    assert resolve(path) == expected


def test_every_registered_tab_belongs_to_a_registered_page_in_its_section():
    by_path = {page.path: page for page in PAGES}
    for section, tabs in SECTION_TABS.items():
        for tab in tabs:
            page = by_path.get(tab.path)
            assert page is not None, f"{section}/{tab.key}: {tab.path} is not in the registry"
            assert (page.section, page.tab) == (section, tab.key), f"{tab.path} is filed under another tab"


def _client(flask_app, db, role, subscribed=True):  # noqa: F811
    org = OrganisationFactory()
    email = f"nav-{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    if subscribed:
        FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    return org, client


def _sidebar_labels(html: str) -> list[str]:
    return re.findall(r'<span class="nav-link-text">([^<]+)</span>', html)


def _tabs(html: str) -> list[tuple[str, bool]]:
    return [
        (key, 'aria-selected="true"' in attrs)
        for key, attrs in re.findall(r'data-section-tab="([a-z0-9-]+)"([^>]*)>', html)
        if " hidden" not in attrs
    ]


def test_admin_sees_exactly_five_main_tabs_and_the_production_sub_nav(db, flask_app):  # noqa: F811
    org, client = _client(flask_app, db, UserRole.ADMIN)
    try:
        html = client.get("/core/planner").get_data(as_text=True)
        assert _sidebar_labels(html) == ["Dashboard", "Production", "Compliance", "Sales", "Settings"]
        assert 'href="/core/planner"' in html  # a sub-nav tab, not a sidebar item
        assert re.search(r'class="nav-link active"[^>]*>\s*<div[^>]*>.*?Production', html, re.S) or "active" in html
        tabs = _tabs(html)
        assert [key for key, _ in tabs] == [t.key for t in SECTION_TABS["production"]]
        assert [key for key, active in tabs if active] == ["planner"]
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_sub_nav_shows_only_the_tabs_a_role_may_open(db, flask_app):  # noqa: F811
    org, client = _client(flask_app, db, UserRole.SALES)
    try:
        html = client.get("/core/contracts").get_data(as_text=True)
        assert "Production" in _sidebar_labels(html)
        keys = [key for key, _ in _tabs(html)]
        assert "contracts" in keys and "inventory" in keys
        assert not {"planner", "batches", "workflows"} & set(keys)  # need production.view
        assert [key for key, _ in _tabs(client.get("/crm").get_data(as_text=True))] == [
            t.key
            for t in SECTION_TABS["sales"]
            if t.key != "configuration"  # needs sales.manage
        ]
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_section_home_falls_back_to_the_first_tab_the_user_may_open(monkeypatch):
    from app.ui import navigation

    monkeypatch.setattr(navigation, "has_permission", lambda user, *perms: "sales.view" in perms)
    assert navigation.section_home("production", object()) == "/core/contracts"
    assert navigation.section_home("sales", object()) == "/crm"
    assert navigation.section_home("settings", object()) == "/core/settings"


def test_sub_nav_follows_the_organisation_setup_and_hides_unconfigured_tabs(db, flask_app):  # noqa: F811
    org, client = _client(flask_app, db, UserRole.ADMIN)
    try:
        client.put(
            "/api/compliant/profile",
            json={"enabled": True, "settings": {"food_control_programme": "none", "liquor_licence_types": []}},
        )
        html = client.get("/compliant/nz-alcohol/customs").get_data(as_text=True)
        keys = [key for key, _ in _tabs(html)]
        assert "np3" not in keys and "licensing" not in keys and "customs" in keys
        assert re.search(r"data-food-safety-tab hidden", html)  # present but hidden, for the configuration page

        saved = client.put(
            "/api/compliant/profile",
            json={"enabled": True, "settings": {"food_control_programme": "np2", "liquor_licence_types": ["on"]}},
        )
        assert saved.status_code == 200, saved.get_json()
        html = client.get("/compliant/nz-alcohol/customs").get_data(as_text=True)
        assert [key for key, _ in _tabs(html)][:4] == ["overview", "np3", "customs", "licensing"]
        assert ">NP2<" in html
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_focused_flows_and_the_dashboard_have_no_sub_nav(db, flask_app):  # noqa: F811
    org, client = _client(flask_app, db, UserRole.ADMIN)
    try:
        assert _tabs(client.get("/core/dashboard").get_data(as_text=True)) == []
        assert _tabs(client.get("/core/flows/create/start").get_data(as_text=True)) != []
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


# --- breadcrumbs and the back arrow (plan 2.3) ---------------------------------------------------

from app.ui.navigation import breadcrumbs  # noqa: E402


def _trail(path, **kw):
    return [(c["label"], c["href"]) for c in breadcrumbs(path, **kw)]


def test_a_tab_page_has_no_trail_and_so_no_back_arrow():
    assert breadcrumbs("/core") == []
    assert breadcrumbs("/core/planner") == []
    assert breadcrumbs("/core/dashboard") == []
    assert breadcrumbs("/compliant") == []
    assert breadcrumbs("/compliant/nz-alcohol/customs") == []


def test_registered_child_pages_list_their_tab_and_parents():
    assert _trail("/core/planner/board") == [
        ("Production", "/core"),
        ("Planner", "/core/planner"),
        ("Production board", None),
    ]
    assert _trail("/core/inventory/add/manual") == [
        ("Production", "/core"),
        ("Inventory", "/core/inventory/view"),
        ("Add to inventory", "/core/inventory/add"),
        ("Add inventory manually", None),
    ]
    assert _trail("/core/go-live") == [("Dashboard", "/core/dashboard"), ("Go live", None)]
    assert _trail("/core/people") == [("Settings", "/core/settings"), ("People and roles", None)]


def test_a_detail_page_hangs_off_its_registered_ancestor():
    assert _trail("/core/contracts/abc", leaf="CO-12") == [
        ("Production", "/core"),
        ("Contract orders", "/core/contracts"),
        ("CO-12", None),
    ]
    assert _trail(
        "/core/contracts/abc/portal-sharing",
        leaf="Portal sharing",
        extra=[{"label": "CO-12", "href": "/core/contracts/abc"}],
    ) == [
        ("Production", "/core"),
        ("Contract orders", "/core/contracts"),
        ("CO-12", "/core/contracts/abc"),
        ("Portal sharing", None),
    ]
    assert _trail("/compliant/nz-alcohol/np3-audit/check/recall-policy", leaf="Check")[-2:] == [
        ("Food safety", "/compliant/nz-alcohol/np3-audit"),
        ("Check", None),
    ]
    assert _trail("/crm/customers/7")[-1] == ("Details", None)


def test_every_registered_page_is_reachable_up_the_trail_to_its_section():
    for page in PAGES:
        crumbs = breadcrumbs(page.path)
        for crumb in crumbs[:-1]:
            assert crumb["href"], f"{page.path}: {crumb}"
        if crumbs:
            assert crumbs[0]["label"].lower().startswith(page.section[:4]), page.path


def test_rendered_pages_tell_the_back_arrow_where_up_is(db, flask_app):  # noqa: F811
    org, client = _client(flask_app, db, UserRole.ADMIN)
    try:
        html = client.get("/core/planner/board").get_data(as_text=True)
        assert 'data-nav-back="/core/planner"' in html and "Production board" in html
        root = client.get("/core/planner").get_data(as_text=True)
        assert 'data-nav-back=""' in root
        wizard = client.get("/core/flows/create/step/1").get_data(as_text=True)
        assert "data-nav-back" not in wizard  # keeps the wizard's own back handling
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()
