"""Liquor licences attach only to explicitly chosen premises in the same tenant."""

from html.parser import HTMLParser
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.features.compliant.models.licensing import LiquorLicence
from app.features.compliant.modules.nz_alcohol import licensing
from tests.test_licensing import _licence, flask_app, world  # noqa: F401


def extra_site(world):  # noqa: F811
    org, db = world["org"], world["db"]
    org.multiple_sites_enabled = True
    site = Site(org_id=org.id, name="Cellar door <img src=x>", kind="retail", is_default=False, is_active=True)
    db.add(site)
    db.commit()
    return site


def test_legacy_licences_are_not_assumed_to_cover_the_default_site(world):  # noqa: F811
    response = _licence(world["client"])
    assert response.status_code == 201
    assert response.get_json()["licences"][0]["site_id"] is None
    assert response.get_json()["multiple_sites_enabled"] is False


def test_multi_site_licence_requires_explicit_same_tenant_site(world):  # noqa: F811
    site = extra_site(world)
    client = world["client"]
    assert _licence(client).status_code == 400
    assert _licence(client, site_id=str(uuid4())).status_code == 400
    response = _licence(client, site_id=str(site.id))
    assert response.status_code == 201
    record = response.get_json()["licences"][0]
    assert record["site_id"] == str(site.id)
    assert record["site_name"] == site.name
    site.is_active = False
    world["db"].commit()
    assert _licence(client, site_id=str(site.id), licence_number="Other").status_code == 400


def test_foreign_site_rejected_by_service_and_database(world):  # noqa: F811
    db, org = world["db"], world["org"]
    foreign = Organisation(name=f"Foreign {uuid4()}")
    db.add(foreign)
    db.flush()
    site = Site(org_id=foreign.id, name="Foreign", is_default=True, is_active=True)
    db.add(site)
    db.flush()
    licence = LiquorLicence(org_id=org.id, kind="off", endorsements=[])
    with pytest.raises(ValueError, match="belonging"):
        licensing.assign_licence_site(db, licence, {"site_id": str(site.id)})
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(LiquorLicence(org_id=org.id, kind="off", site_id=site.id, endorsements=[]))
            db.flush()
    db.rollback()


def test_existing_licence_can_be_assigned_without_losing_registration_fields(world):  # noqa: F811
    client = world["client"]
    old = _licence(client).get_json()["licences"][0]
    site = extra_site(world)
    response = client.put(f"/api/compliant/licensing/licences/{old['id']}", json={"site_id": str(site.id)})
    assert response.status_code == 200
    row = response.get_json()["licences"][0]
    assert row["site_id"] == str(site.id)
    assert row["premises"] == old["premises"]
    assert row["expires_on"] == old["expires_on"]
    assert client.put(f"/api/compliant/licensing/licences/{old['id']}", json={"site_id": None}).status_code == 400


def test_site_assignment_keeps_real_csrf_protection(world, flask_app):  # noqa: F811
    class TokenParser(HTMLParser):
        token = None

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "meta" and values.get("name") == "csrf-token":
                self.token = values.get("content")

    client = world["client"]
    old = _licence(client).get_json()["licences"][0]
    site = extra_site(world)
    endpoint = f"/api/compliant/licensing/licences/{old['id']}"
    previous = flask_app.config["WTF_CSRF_ENABLED"]
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        assert client.put(endpoint, json={"site_id": str(site.id)}).status_code == 400
        parser = TokenParser()
        parser.feed(client.get("/compliant/nz-alcohol/licensing").get_data(as_text=True))
        assert parser.token
        response = client.put(
            endpoint,
            json={"site_id": str(site.id)},
            headers={"X-CSRFToken": parser.token, "Referer": "https://localhost/compliant/nz-alcohol/licensing"},
        )
        assert response.status_code == 200
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = previous
