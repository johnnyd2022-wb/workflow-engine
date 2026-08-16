"""observability: GET /ui/shared/<filename> must log access_denied on its inline 401.

This route enforces auth inside the view (not via @requires_auth, see app_factory.py's
serve_ui_shared docstring) so it doesn't share requires_auth's logging automatically --
regression coverage for that gap (shell review, .agents/reports/shell/observability.md).
"""

import pytest


class _SpyLogger:
    """Stand-in for the structlog handle app_factory.create_app() binds locally.

    create_app() calls get_logger(__name__) itself (not a module-level `logger`, unlike
    every other module in this repo), so there's no module attribute to monkeypatch after
    the fact -- patching get_logger before create_app() runs is the only hook available.
    """

    def __init__(self):
        self.warning_calls = []

    def warning(self, event, **kw):
        self.warning_calls.append((event, kw))

    def __getattr__(self, _name):
        return lambda *a, **kw: None


@pytest.fixture
def flask_app_with_spy_logger(monkeypatch):
    import app.api.app_factory as app_factory_module

    spy = _SpyLogger()
    monkeypatch.setattr(app_factory_module, "get_logger", lambda *a, **kw: spy)

    app = app_factory_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    spy.warning_calls.clear()  # drop create_app()'s own startup warnings (e.g. secret_key_using_insecure_default)
    with app.app_context():
        yield app, spy


def test_unauthenticated_ui_shared_request_logs_access_denied(flask_app_with_spy_logger):
    app, spy = flask_app_with_spy_logger
    client = app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"

    resp = client.get("/ui/shared/sidebar-v2.js")
    # The global 401 errorhandler redirects GET page-shaped requests to "/" rather than
    # returning a bare 401 (app_factory.py's serve_ui_shared docstring); the access_denied
    # log is what makes this otherwise-invisible redirect auditable.
    assert resp.status_code == 302, resp.data

    assert len(spy.warning_calls) == 1
    event, kw = spy.warning_calls[0]
    assert event == "access_denied"
    assert kw["reason"] == "unauthenticated"
    assert kw["path"] == "/ui/shared/sidebar-v2.js"
    assert kw["method"] == "GET"


def test_public_allowlisted_ui_shared_file_does_not_log_access_denied(flask_app_with_spy_logger):
    """password-policy.js is in PUBLIC_UI_SHARED_FILES -- no auth, so no denial to log."""
    app, spy = flask_app_with_spy_logger
    client = app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"

    resp = client.get("/ui/shared/password-policy.js")
    assert resp.status_code == 200, resp.data
    assert spy.warning_calls == []
