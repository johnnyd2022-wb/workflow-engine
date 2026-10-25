"""GL-A04 (interim): the sign-in form says how to get back in without self-service recovery."""

from app.app import app as flask_app


def _landing() -> str:
    return flask_app.test_client().get("/", base_url="https://localhost").get_data(as_text=True)


def test_the_sign_in_form_offers_a_way_back_in():
    html = _landing()
    assert 'id="login-help"' in html
    assert "Forgotten your password or locked out?" in html
    assert 'href="mailto:support@biz-e.app' in html


def test_no_help_line_without_a_support_address(monkeypatch):
    from app.utils.config_loader import config

    monkeypatch.setattr(type(config), "support_email", property(lambda self: ""))
    html = _landing()
    assert 'id="login-help"' not in html
