"""Regression coverage for CRM availability in shipped environments."""

from configparser import ConfigParser
from pathlib import Path
from uuid import uuid4

import pytest
from flask import g, render_template

from app.features.compliant import compliant_bp
from app.features.crm import crm_bp
from app.features.operational_cases import operational_cases_bp

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_shared_spa_uses_the_crm_static_endpoint():
    base_spa = (REPO_ROOT / "app/core/frontend/shared/base_spa.html").read_text(encoding="utf-8")

    assert "url_for('crm.serve_crm_css', filename='crm.css')" in base_spa
    for filename in (
        "crm-api.js",
        "overview.js",
        "customers.js",
        "customer-detail.js",
        "tasks-calendar.js",
        "configuration.js",
        "integrations.js",
    ):
        assert f"url_for('crm.serve_crm_js', filename='{filename}')" in base_spa
    assert base_spa.count("{% if crm_enabled %}") >= 2


def test_crm_is_enabled_in_every_shipped_environment_config():
    for name in ("local.ini", "local.ini.template", "prod.ini", "prod.ini.template", "test.ini", "test.ini.template"):
        parser = ConfigParser()
        parser.read(REPO_ROOT / "app" / "config" / name)

        assert parser.getboolean("features", "crm_enabled") is True, name


def test_crm_stylesheet_is_served_as_css():
    from app.api.app_factory import create_app

    app = create_app()

    response = app.test_client().get("/crm/static/css/crm.css")

    assert response.status_code == 200
    assert response.mimetype == "text/css"


@pytest.mark.parametrize(
    ("feature", "factory_name", "workspace_href"),
    (
        ("crm", "create_crm_blueprint", "/crm/"),
        ("compliant", "create_compliant_blueprint", 'href="/compliant"'),
    ),
)
def test_core_shell_degrades_when_optional_product_registration_fails(
    monkeypatch, feature, factory_name, workspace_href
):
    from app.api.app_factory import create_app

    def fail_registration():
        raise RuntimeError(f"simulated optional {feature} failure")

    module = crm_bp if feature == "crm" else compliant_bp
    monkeypatch.setattr(module, factory_name, fail_registration)
    app = create_app()

    assert app.extensions["product_availability"][feature] is False
    with app.test_request_context("/core"):
        html = render_template("dashboard/dashboard.html", active_page="dashboard")

    assert workspace_href not in html


def test_integrations_page_degrades_when_crm_registration_fails(monkeypatch):
    from app.api.app_factory import create_app
    from app.core.backend.backend import integrations

    def fail_registration():
        raise RuntimeError("simulated optional CRM failure")

    monkeypatch.setattr(crm_bp, "create_crm_blueprint", fail_registration)
    app = create_app()

    with app.test_request_context("/core/integrations"):
        html = integrations.__wrapped__()

    assert "CRM is unavailable in this environment." in html
    assert "/crm/configuration" not in html


def test_unsubscribed_org_loads_core_without_compliant_workspace(monkeypatch):
    import app.core.security.entitlements as entitlements
    from app.api.app_factory import create_app

    monkeypatch.setattr(entitlements, "org_has_feature", lambda *_args, **_kwargs: False)
    app = create_app()

    with app.test_request_context("/core/dashboard"):
        g.current_org_id = uuid4()
        html = render_template("dashboard/dashboard.html", active_page="dashboard")

    assert 'href="/compliant"' not in html
    assert "Compliant is not enabled for this organisation." in html


def test_core_shell_marks_cases_unavailable_when_cases_registration_fails(monkeypatch):
    from app.api.app_factory import create_app

    def fail_registration():
        raise RuntimeError("simulated optional cases failure")

    monkeypatch.setattr(operational_cases_bp, "create_operational_cases_blueprint", fail_registration)
    app = create_app()

    assert app.extensions["product_availability"]["operational_cases"] is False
    with app.test_request_context("/core/dashboard"):
        g.current_org_id = uuid4()
        html = render_template("dashboard/dashboard.html", active_page="dashboard")

    assert 'name="operational-cases-enabled" content="false"' in html
