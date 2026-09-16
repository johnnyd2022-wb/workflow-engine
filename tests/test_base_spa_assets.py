"""Regression coverage for CRM availability in shipped environments."""

from configparser import ConfigParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_shared_spa_uses_the_crm_static_endpoint():
    base_spa = (REPO_ROOT / "app/core/frontend/shared/base_spa.html").read_text(encoding="utf-8")

    assert "url_for('crm.serve_crm_css', filename='crm.css')" in base_spa


def test_crm_is_enabled_in_every_shipped_environment_config():
    for name in ("local.ini", "local.ini.template", "prod.ini", "prod.ini.template", "test.ini", "test.ini.template"):
        parser = ConfigParser()
        parser.read(REPO_ROOT / "app" / "config" / name)

        assert parser.getboolean("features", "crm_enabled") is True, name


def test_crm_stylesheet_is_served_as_css():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True

    response = app.test_client().get("/crm/static/css/crm.css")

    assert response.status_code == 200
    assert response.mimetype == "text/css"
