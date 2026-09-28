"""Dated area coverage, tenancy and database-level licence boundaries."""

from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.stock_location import StockLocation
from app.core.db.models.user import User, UserRole
from app.core.security.tenant_scope import unscoped
from app.features.compliant.models.customs_premises import CustomsCoverage, CustomsLicence
from app.features.compliant.modules.nz_alcohol import premises
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- shared app fixture


@pytest.fixture
def world(db):
    orgs = [Organisation(id=uuid4(), name=f"CCA tenant {uuid4()}") for _ in range(2)]
    db.add_all(orgs)
    db.flush()
    sites = [Site(id=uuid4(), org_id=org.id, name="Main", is_default=True, is_active=True) for org in orgs]
    extra = Site(id=uuid4(), org_id=orgs[0].id, name="Bond store", kind="storage", is_default=False, is_active=True)
    db.add_all([*sites, extra])
    db.flush()
    shop = StockLocation(
        id=uuid4(), org_id=orgs[0].id, site_id=sites[0].id, name="Cellar door", inside_licensed_area=False
    )
    db.add(shop)
    db.flush()
    try:
        yield orgs, sites, extra, shop
    finally:
        db.rollback()


def licence_data(**changes):
    return {
        "number": "CCA-123",
        "name": "Distillery",
        "kind": "lma",
        "legal_entity_reference": "NZBN-123",
        "valid_from": "2026-01-01",
        "valid_until": None,
        "evidence_reference": "Licence PDF 123",
        **changes,
    }


def coverage_data(licence, site, **changes):
    return {
        "licence_id": str(licence.id),
        "site_id": str(site.id),
        "location_id": None,
        "valid_from": "2026-01-01",
        "valid_until": None,
        "evidence_reference": "Approved floor plan",
        **changes,
    }


def test_one_licence_can_cover_several_sites_without_licensing_outside_areas(db, world):
    orgs, sites, extra, shop = world
    licence = premises.add_licence(db, orgs[0].id, licence_data())
    premises.add_coverage(db, orgs[0].id, coverage_data(licence, sites[0]))
    premises.add_coverage(db, orgs[0].id, coverage_data(licence, extra))
    on = date(2026, 9, 29)
    assert premises.licence_for_area(db, orgs[0].id, sites[0].id, None, on).id == licence.id
    assert premises.licence_for_area(db, orgs[0].id, extra.id, None, on).id == licence.id
    assert premises.licence_for_area(db, orgs[0].id, sites[0].id, shop.id, on) is None
    assert not shop.inside_licensed_area
    assert premises.licence_for_area(db, orgs[1].id, sites[0].id, None, on) is None


def test_multiple_licences_at_one_site_have_explicit_nonoverlapping_areas(db, world):
    orgs, sites, _, shop = world
    first = premises.add_licence(db, orgs[0].id, licence_data())
    second = premises.add_licence(db, orgs[0].id, licence_data(number="CCA-456", kind="oss"))
    premises.add_coverage(db, orgs[0].id, coverage_data(first, sites[0]))
    premises.add_coverage(db, orgs[0].id, coverage_data(second, sites[0], location_id=str(shop.id)))
    assert premises.licence_for_area(db, orgs[0].id, sites[0].id, shop.id, date(2026, 9, 29)).id == second.id


def test_dates_are_inclusive_and_coverage_can_change_without_overlap(db, world):
    orgs, sites, _, _ = world
    first = premises.add_licence(db, orgs[0].id, licence_data(valid_until="2026-06-30"))
    second = premises.add_licence(db, orgs[0].id, licence_data(number="CCA-456", valid_from="2026-07-01"))
    premises.add_coverage(db, orgs[0].id, coverage_data(first, sites[0], valid_until="2026-06-30"))
    premises.add_coverage(db, orgs[0].id, coverage_data(second, sites[0], valid_from="2026-07-01"))
    assert premises.licence_for_area(db, orgs[0].id, sites[0].id, None, date(2026, 6, 30)).id == first.id
    assert premises.licence_for_area(db, orgs[0].id, sites[0].id, None, date(2026, 7, 1)).id == second.id
    assert premises.licence_for_area(db, orgs[0].id, sites[0].id, None, date(2025, 12, 31)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"number": ""},
        {"number": "x" * 101},
        {"name": True},
        {"kind": "anything"},
        {"kind": []},
        {"legal_entity_reference": " "},
        {"evidence_reference": None},
        {"valid_from": "not a date"},
        {"valid_from": None},
        {"valid_until": "2025-12-31"},
        {"valid_until": False},
        {"valid_until": ""},
        {"org_id": str(uuid4())},
    ],
)
def test_invalid_licence_fields_are_controlled_errors(db, world, changes):
    orgs, _, _, _ = world
    with pytest.raises(ValueError):
        premises.add_licence(db, orgs[0].id, licence_data(**changes))
    assert db.query(CustomsLicence).count() == 0


def test_service_refuses_foreign_site_and_licence_or_wrong_location(db, world):
    orgs, sites, extra, shop = world
    first = premises.add_licence(db, orgs[0].id, licence_data())
    foreign = premises.add_licence(db, orgs[1].id, licence_data())
    for data in (
        coverage_data(first, sites[1]),
        coverage_data(foreign, sites[0]),
        coverage_data(first, extra, location_id=str(shop.id)),
    ):
        with pytest.raises(ValueError):
            premises.add_coverage(db, orgs[0].id, data)
    assert db.query(CustomsCoverage).count() == 0


def test_service_refuses_overlap_and_coverage_outside_licence_dates(db, world):
    orgs, sites, _, _ = world
    licence = premises.add_licence(db, orgs[0].id, licence_data(valid_until="2026-12-31"))
    for changes in ({"valid_from": "2025-12-31"}, {}, {"valid_until": "2027-01-01"}):
        with pytest.raises(ValueError, match="valid dates"):
            premises.add_coverage(db, orgs[0].id, coverage_data(licence, sites[0], **changes))
    premises.add_coverage(db, orgs[0].id, coverage_data(licence, sites[0], valid_until="2026-12-31"))
    with pytest.raises(ValueError, match="already has"):
        premises.add_coverage(db, orgs[0].id, coverage_data(licence, sites[0], valid_until="2026-12-31"))


@pytest.mark.parametrize("named_area", [False, True])
def test_database_exclusion_refuses_overlap_even_with_service_bypass(db, world, named_area):
    orgs, sites, _, shop = world
    licence = premises.add_licence(db, orgs[0].id, licence_data())
    location = shop.id if named_area else None
    premises.add_coverage(
        db, orgs[0].id, coverage_data(licence, sites[0], location_id=str(location) if location else None)
    )
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                CustomsCoverage(
                    org_id=orgs[0].id,
                    licence_id=licence.id,
                    site_id=sites[0].id,
                    location_id=location,
                    valid_from=date(2026, 9, 29),
                    evidence_reference="Bad duplicate",
                )
            )
            db.flush()


def test_database_composite_foreign_keys_refuse_cross_org_coverage(db, world):
    orgs, sites, _, _ = world
    licence = premises.add_licence(db, orgs[0].id, licence_data())
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                CustomsCoverage(
                    org_id=orgs[1].id,
                    licence_id=licence.id,
                    site_id=sites[1].id,
                    valid_from=date(2026, 1, 1),
                    evidence_reference="Foreign licence",
                )
            )
            db.flush()


@pytest.fixture
def clients(db, flask_app):  # noqa: F811
    first, admin = _admin_client(db, flask_app)
    second, neighbour = _admin_client(db, flask_app)
    ids = (first.id, second.id)
    try:
        yield first, admin, second, neighbour
    finally:
        db.rollback()
        with unscoped():
            db.query(CustomsCoverage).filter(CustomsCoverage.org_id.in_(ids)).delete(synchronize_session=False)
            db.query(CustomsLicence).filter(CustomsLicence.org_id.in_(ids)).delete(synchronize_session=False)
            db.query(Organisation).filter(Organisation.id.in_(ids)).delete(synchronize_session=False)
            db.commit()


def test_api_coverage_is_tenant_scoped_and_managing_requires_permission(db, clients):
    org, admin, _, neighbour = clients
    licence = admin.post("/api/compliant/nz-alcohol/cca-licences", json=licence_data())
    assert licence.status_code == 201
    own = admin.get("/api/compliant/nz-alcohol/premises").get_json()
    assert len(own["licences"]) == 1
    assert neighbour.get("/api/compliant/nz-alcohol/premises").get_json()["licences"] == []
    assert (
        neighbour.post(
            "/api/compliant/nz-alcohol/cca-coverage",
            json={
                **coverage_data(
                    type("Row", (), {"id": licence.get_json()["id"]}), type("Row", (), {"id": own["sites"][0]["id"]})
                ),
            },
        ).status_code
        == 400
    )
    with unscoped():
        user = db.query(User).filter(User.org_id == org.id).one()
        user.role = UserRole.PRODUCTION
        db.commit()
    assert admin.get("/api/compliant/nz-alcohol/premises").status_code == 200
    assert (
        admin.post("/api/compliant/nz-alcohol/cca-licences", json=licence_data(number="CCA-OTHER")).status_code == 403
    )


def test_phone_licence_and_area_forms_render_safe_text_and_fit(clients, browser):
    _, client, _, _ = clients
    page = browser.new_page(viewport={"width": 390, "height": 844})

    def proxy(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != "premises.test":
            route.abort()
            return
        response = client.open(
            parsed.path,
            method=request.method,
            data=request.post_data,
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
        route.fulfill(status=response.status_code, body=response.data, headers={"Content-Type": response.content_type})

    page.route("**/*", proxy)
    try:
        page.goto("https://premises.test/compliant/nz-alcohol/premises")
        form = page.locator("[data-licence-form]")
        for name, value in licence_data(name="Distillery <img src=x onerror=alert(1)>").items():
            if value is None:
                continue
            if name == "kind":
                form.locator(f'[name="{name}"]').select_option(value)
            else:
                form.locator(f'[name="{name}"]').fill(value)
        form.get_by_role("button", name="Register licence").click()
        page.get_by_role("heading", name="CCA-123 · Distillery <img src=x onerror=alert(1)>").wait_for()
        assert page.locator("[data-licences] img").count() == 0
        area = page.locator("[data-coverage-form]")
        area.locator('[name="licence_id"]').select_option(index=1)
        area.locator('[name="site_id"]').select_option(index=1)
        area.locator('[name="valid_from"]').fill("2026-01-01")
        area.locator('[name="evidence_reference"]').fill("Approved main area plan")
        area.get_by_role("button", name="Assign area").click()
        page.locator("[data-coverage]").get_by_text("Approved main area plan").wait_for()
        assert page.locator("[data-premises-root] input, [data-premises-root] select").evaluate_all(
            "elements => elements.every(el => { const r = el.getBoundingClientRect(); "
            "return r.left >= 0 && r.right <= window.innerWidth; })"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        page.close()


def test_licence_post_requires_real_csrf_token(clients, flask_app):  # noqa: F811
    class TokenParser(HTMLParser):
        token = None

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "meta" and values.get("name") == "csrf-token":
                self.token = values.get("content")

    _, client, _, _ = clients
    previous = flask_app.config["WTF_CSRF_ENABLED"]
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        endpoint = "/api/compliant/nz-alcohol/cca-licences"
        assert client.post(endpoint, json=licence_data()).status_code == 400
        parser = TokenParser()
        parser.feed(client.get("/compliant/nz-alcohol/premises").get_data(as_text=True))
        assert parser.token
        response = client.post(
            endpoint,
            json=licence_data(),
            headers={"X-CSRFToken": parser.token, "Referer": "https://localhost/compliant/nz-alcohol/premises"},
        )
        assert response.status_code == 201
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = previous
