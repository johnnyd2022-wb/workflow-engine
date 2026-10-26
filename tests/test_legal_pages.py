"""GL-C01, GL-C02: pricing, terms and privacy are public pages, linked where people sign up and
from inside the app, and each sign-up records which version of the terms it agreed to."""

import re
from uuid import uuid4

import pytest

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User
from app.ui.legal import TERMS_VERSION
from tests.test_auth_password_session import PASSWORD
from tests.test_auth_password_session import account as _account  # noqa: F401 -- fixture re-export


@pytest.fixture
def anonymous(_account):  # noqa: F811
    return _account["make_client"]()


@pytest.mark.parametrize(
    "path, heading",
    [("/pricing", "Pricing"), ("/terms", "Terms of service"), ("/privacy", "Privacy policy")],
)
def test_each_page_is_public_and_says_it_is_a_placeholder(anonymous, path, heading):
    resp = anonymous.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert f"<h1>{heading}</h1>" in html
    assert "data-legal-draft" in html, "until reviewed, the page must say it is a placeholder"
    # Every page links to the other two.
    for other in ("/pricing", "/terms", "/privacy"):
        assert f'href="{other}"' in html


def test_pricing_shows_the_founders_price_and_what_is_not_included(anonymous):
    html = anonymous.get("/pricing").get_data(as_text=True)
    assert "Compliance (NZ Alcohol)" in html
    assert "NZD 250" in html and "a month + GST" in html
    # GL-P07: the offer says what it doesn't do rather than implying a planner or multi-site system.
    assert "Not included yet" in html
    assert "Material planning" in html


def test_terms_and_privacy_carry_the_version_recorded_at_sign_up(anonymous):
    for path in ("/terms", "/privacy"):
        assert TERMS_VERSION in anonymous.get(path).get_data(as_text=True)


def test_the_sign_up_form_links_the_terms_and_privacy_policy():
    from app.api.app_factory import create_app
    from app.app import index  # the landing page lives on app.app, outside the factory

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.add_url_rule("/", "index", index)
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    html = client.get("/").get_data(as_text=True)
    form = html[html.index('id="signupForm"') : html.index("</form>", html.index('id="signupForm"'))]
    assert 'href="/terms"' in form and 'href="/privacy"' in form
    assert "By creating an account you agree" in form
    assert re.search(r'<a href="/pricing"[^>]*>Pricing</a>', html), "the landing page links Pricing"


def test_settings_links_the_legal_pages_outside_boosted_navigation(_account):  # noqa: F811
    html = _account["make_client"](PASSWORD).get("/core/settings").get_data(as_text=True)
    links = re.search(r'<p class="settings-legal-links"([^>]*)>(.*?)</p>', html, re.S)
    assert links, "Settings has the legal links"
    # They are standalone pages, not app pages: a boosted swap would find no #page-content.
    assert 'hx-boost="false"' in links.group(1)
    for path in ("/pricing", "/terms", "/privacy"):
        assert f'href="{path}"' in links.group(2)


def test_a_sign_up_records_the_terms_version_it_agreed_to(anonymous, db):
    org_name = f"Terms Test {uuid4()}"
    resp = anonymous.post(
        "/auth/signup",
        json={
            "org_name": org_name,
            "email": f"terms_{uuid4()}@test.com",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
        },
    )
    assert resp.status_code in (200, 201), resp.data
    db.expire_all()
    org = db.query(Organisation).filter(Organisation.name == org_name).one()
    try:
        entry = db.query(AuditLog).filter(AuditLog.org_id == org.id, AuditLog.action == "signup").one()
        assert entry.meta_data["terms_version"] == TERMS_VERSION
    finally:
        db.rollback()
        db.query(AuditLog).filter(AuditLog.org_id == org.id).delete(synchronize_session=False)
        db.query(User).filter(User.org_id == org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


@pytest.mark.parametrize("path", ["/pricing", "/terms", "/privacy"])
def test_an_expired_session_still_reads_the_public_pages(_account, path):  # noqa: F811
    """Review of !579: a stale cookie from an old visit must not turn a public page into a 401."""
    from datetime import UTC, datetime, timedelta

    client = _account["make_client"](PASSWORD)
    with client.session_transaction() as browser_session:
        browser_session["session_timeout_minutes"] = 5
        browser_session["last_activity_at"] = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    resp = client.get(path)
    assert resp.status_code == 200
    assert "data-legal-draft" in resp.get_data(as_text=True)
    # The app itself still enforces the timeout.
    assert client.get("/core/settings").status_code in (302, 401)
