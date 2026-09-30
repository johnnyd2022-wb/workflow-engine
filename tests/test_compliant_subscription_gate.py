"""The per-org subscription gate on the whole Compliant blueprint.

Covers spec .agents/specs/compliant_tools.md AC3, AC4, AC5, AC6, AC7.
"""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.db.models.user import UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

_PARAM_SAMPLES = {
    "framework_slug": "customs-alcohol",
    "report_id": str(uuid4()),
    "key": "dilution",
    "filename": "compliant.js",
}


@pytest.fixture
def app_ctx():
    from app.api.app_factory import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        yield app


def _mk_user(db, *, role=UserRole.ADMIN, subscribed=True):
    org = OrganisationFactory()
    email = f"gate-{uuid4()}@test.com"
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
    return org, email


def _client(app, email=None):
    c = app.test_client()
    c.environ_base["wsgi.url_scheme"] = "https"
    c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    if email:
        r = c.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
        assert r.status_code == 200
    return c


def _compliant_rules(app):
    for rule in app.url_map.iter_rules():
        if not rule.endpoint.startswith("compliant"):
            continue
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        path = rule.rule
        for arg in rule.arguments:
            path = path.replace(f"<{arg}>", _PARAM_SAMPLES.get(arg, "x")).replace(
                f"<path:{arg}>", _PARAM_SAMPLES.get(arg, "x")
            )
        # remaining converter syntax e.g. <path:filename>
        for arg in rule.arguments:
            path = path.replace(f"<path:{arg}>", _PARAM_SAMPLES.get(arg, "x"))
        yield path, methods


def _cleanup(db, org_ids):
    db.query(FeatureSubscription).filter(FeatureSubscription.org_id.in_(org_ids)).delete(synchronize_session=False)
    db.commit()


# ── AC3 ────────────────────────────────────────────────────────────────────────


def test_ac3_unsubscribed_org_gets_exact_404_on_every_compliant_route(db, app_ctx):
    org, email = _mk_user(db, subscribed=False)
    try:
        client = _client(app_ctx, email)
        checked = 0
        for path, methods in _compliant_rules(app_ctx):
            for method in methods:
                resp = client.open(path, method=method, json={} if method in ("POST", "PUT") else None)
                assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"
                body = resp.get_data(as_text=True).lower()
                for term in ("subscription", "not subscribed", "compliant", "feature", "entitle"):
                    assert term not in body, f"{method} {path} 404 body leaks {term!r}: {body[:120]}"
                checked += 1
        assert checked >= 10
    finally:
        _cleanup(db, [org.id])


def test_ac3_unauthenticated_never_hits_the_404_gate(db, app_ctx):
    client = _client(app_ctx)  # no login
    for path, methods in _compliant_rules(app_ctx):
        for method in methods:
            resp = client.open(path, method=method, json={} if method in ("POST", "PUT") else None)
            assert resp.status_code != 404, f"unauth {method} {path} -> 404 (gate fired before auth)"
            assert resp.status_code in (302, 401), f"unauth {method} {path} -> {resp.status_code}"


# ── AC4 ────────────────────────────────────────────────────────────────────────


def test_ac4_subscribed_org_routes_work_and_role_gate_survives(db, app_ctx):
    admin_org, admin_email = _mk_user(db, role=UserRole.ADMIN, subscribed=True)
    member_org, member_email = _mk_user(db, role=UserRole.MEMBER, subscribed=True)
    try:
        admin = _client(app_ctx, admin_email)
        assert admin.get("/api/compliant/overview").status_code == 200
        assert admin.get("/compliant/tools").status_code == 200
        assert admin.get("/api/compliant/tools").status_code == 200

        member = _client(app_ctx, member_email)
        # subscription gate passed, but BOTH existing ADMIN role gates still apply
        assert member.put("/api/compliant/profile", json={"enabled": True}).status_code == 403
        assert (
            member.post(
                "/api/compliant/alcohol-products",
                json={"inventory_name": "Gin", "product_type": "spirits", "abv_percent": "40"},
            ).status_code
            == 403
        )
        assert member.get("/api/compliant/overview").status_code == 200
        assert member.get("/compliant/tools").status_code == 200  # no role gate on tools
    finally:
        _cleanup(db, [admin_org.id, member_org.id])


def test_ac4_revoking_restores_404_without_restart(db, app_ctx):
    org, email = _mk_user(db, subscribed=True)
    try:
        client = _client(app_ctx, email)
        assert client.get("/api/compliant/overview").status_code == 200
        FeatureSubscriptionRepository(db).revoke(org.id, "compliant")
        db.commit()
        assert client.get("/api/compliant/overview").status_code == 404
    finally:
        _cleanup(db, [org.id])


# ── AC5 ────────────────────────────────────────────────────────────────────────


def test_ac5_refusal_emits_structured_access_denied(db, app_ctx, caplog):
    org, email = _mk_user(db, subscribed=False)
    try:
        client = _client(app_ctx, email)
        with caplog.at_level(logging.WARNING, logger="app.features.compliant.compliant_bp"):
            client.get("/api/compliant/overview")
        msgs = [r.getMessage() for r in caplog.records if "access_denied" in r.getMessage()]
        assert msgs, [r.getMessage() for r in caplog.records]
        m = msgs[0]
        assert "org_not_subscribed" in m
        assert "'feature': 'compliant'" in m
        assert str(org.id) in m
        assert "/api/compliant/overview" in m
    finally:
        _cleanup(db, [org.id])


# ── AC6 ────────────────────────────────────────────────────────────────────────


def test_ac6_deployment_flag_off_removes_the_blueprint(db, monkeypatch):
    from app.utils.config_loader import config

    monkeypatch.setattr(type(config), "compliant_enabled", property(lambda self: False))
    assert config.compliant_enabled is False

    from app.api.app_factory import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        org, email = _mk_user(db, subscribed=True)
        try:
            client = _client(app, email)
            for path in ("/compliant", "/compliant/tools", "/api/compliant/overview", "/api/compliant/tools"):
                assert client.get(path).status_code == 404
            assert not any(r.endpoint.startswith("compliant") for r in app.url_map.iter_rules())
        finally:
            _cleanup(db, [org.id])


# ── AC7 ────────────────────────────────────────────────────────────────────────


def _sidebar_has_compliance(html: str) -> bool:
    return 'href="/compliant"' in html and "Compliance" in html


def test_ac7_nav_item_visibility(db, app_ctx):
    sub_org, sub_email = _mk_user(db, subscribed=True)
    unsub_org, unsub_email = _mk_user(db, subscribed=False)
    try:
        subbed = _client(app_ctx, sub_email).get("/core/dashboard").get_data(as_text=True)
        assert _sidebar_has_compliance(subbed)
        assert 'href="/compliant"' in subbed

        unsubbed = _client(app_ctx, unsub_email).get("/core/dashboard").get_data(as_text=True)
        assert not _sidebar_has_compliance(unsubbed)

        loggedout = _client(app_ctx).get("/", follow_redirects=False).get_data(as_text=True)
        assert not _sidebar_has_compliance(loggedout)
    finally:
        _cleanup(db, [sub_org.id, unsub_org.id])


def test_ac7_nav_state_does_not_leak_across_orgs_in_a_reused_context(db, app_ctx):
    """`g.compliant_subscribed` is tagged with the org it was computed for, so a reused
    Flask app context cannot serve a subscribed org's nav state to an unsubscribed one.
    """
    sub_org, sub_email = _mk_user(db, subscribed=True)
    unsub_org, unsub_email = _mk_user(db, subscribed=False)
    try:
        sub_client = _client(app_ctx, sub_email)
        unsub_client = _client(app_ctx, unsub_email)
        # subscribed org first — visits a /compliant page so before_request caches True on g
        assert sub_client.get("/compliant/tools").status_code == 200
        # then the unsubscribed org renders a non-compliant page in the same app context
        html = unsub_client.get("/core/dashboard").get_data(as_text=True)
        assert not _sidebar_has_compliance(html)
    finally:
        _cleanup(db, [sub_org.id, unsub_org.id])


def test_ac7_nav_hidden_when_deployment_flag_off_even_if_subscribed(db, monkeypatch):
    from app.utils.config_loader import config

    monkeypatch.setattr(type(config), "compliant_enabled", property(lambda self: False))
    from app.api.app_factory import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        org, email = _mk_user(db, subscribed=True)
        try:
            html = _client(app, email).get("/core/dashboard").get_data(as_text=True)
            assert not _sidebar_has_compliance(html)
        finally:
            _cleanup(db, [org.id])


def test_ac7_both_sidebars_drop_dilution_and_gate_compliance_on_subscription():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    for rel in ("app/ui/templates/shared/sidebar-v2.html", "app/ui/shared/sidebar-v2.html"):
        src = (repo / rel).read_text()
        assert "/dilution-calculator" not in src, f"{rel} still links the removed dilution page"
        assert "Dilution Calculator" not in src, f"{rel} still names the removed dilution page"
        assert "compliant_subscribed" in src, f"{rel} does not gate the Compliance item on the subscription"
        assert "{% if compliant_enabled %}" not in src.replace("{% if compliant_subscribed %}", ""), (
            f"{rel} still gates Compliance on the deployment flag alone"
        )
