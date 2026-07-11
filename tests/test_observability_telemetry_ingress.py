"""Integration tests for constrained browser telemetry ingestion."""

from __future__ import annotations

import logging

from requests import Response


def _upstream_response(status_code: int = 202, content: bytes = b'"accepted"') -> Response:
    response = Response()
    response.status_code = status_code
    response._content = content
    response.headers["Content-Type"] = "application/json"
    response.headers["Set-Cookie"] = "collector-session=should-not-be-forwarded"
    return response


def _build_app(monkeypatch, captured_requests, *, grafana_data_enabled=True, posthog_data_enabled=True):
    # Earlier capsys-based logging tests intentionally replace the root stream
    # with a capture object that pytest then closes. Start this app integration
    # test with a clean root logger before importing the app/config modules.
    logging.getLogger().handlers.clear()

    import app.api.app_factory as app_factory
    from app.utils.config_loader import Config

    monkeypatch.setattr(Config, "rum_enabled", property(lambda _self: True))
    monkeypatch.setattr(Config, "grafana_data_enabled", property(lambda _self: grafana_data_enabled))
    monkeypatch.setattr(Config, "posthog_data_enabled", property(lambda _self: posthog_data_enabled))
    monkeypatch.setattr(Config, "rum_faro_upstream", property(lambda _self: "http://faro.test"))
    monkeypatch.setattr(Config, "rum_posthog_upstream", property(lambda _self: "http://posthog.test"))
    monkeypatch.setattr(Config, "rum_posthog_capture_upstream", property(lambda _self: "http://capture.test"))
    monkeypatch.setattr(Config, "rum_posthog_replay_upstream", property(lambda _self: "http://replay.test"))
    monkeypatch.setattr(Config, "rum_posthog_feature_flags_upstream", property(lambda _self: "http://flags.test"))

    def fake_request(**kwargs):
        captured_requests.append(kwargs)
        return _upstream_response()

    monkeypatch.setattr(app_factory.requests, "request", fake_request)
    app = app_factory.create_app()
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    return app


def test_faro_ingest_is_csrf_exempt_and_forwards_only_to_collect(monkeypatch):
    captured_requests = []
    app = _build_app(monkeypatch, captured_requests)

    with app.test_client() as client:
        response = client.post(
            "/telemetry",
            data=b'{"logs":[]} ',
            content_type="application/json",
            headers={"X-Forwarded-Proto": "https"},
        )

    assert response.status_code == 202
    assert response.get_json() == "accepted"
    assert response.headers.get("Set-Cookie") is None
    assert captured_requests[0]["method"] == "POST"
    assert captured_requests[0]["url"] == "http://faro.test/collect"


def test_posthog_ingest_allows_only_known_sdk_paths(monkeypatch):
    captured_requests = []
    app = _build_app(monkeypatch, captured_requests)

    with app.test_client() as client:
        headers = {"X-Forwarded-Proto": "https"}
        allowed = client.post("/telemetry/posthog/e/?ip=1", data=b"{}", content_type="application/json", headers=headers)
        rejected = client.post("/telemetry/posthog/http://metadata.internal/latest", data=b"{}", headers=headers)

    assert allowed.status_code == 202
    assert captured_requests[0]["url"] == "http://capture.test/e/?ip=1"
    assert rejected.status_code == 404
    assert len(captured_requests) == 1


def test_telemetry_ingest_respects_independent_destination_toggles(monkeypatch):
    captured_requests = []
    app = _build_app(monkeypatch, captured_requests, grafana_data_enabled=False, posthog_data_enabled=False)

    with app.test_client() as client:
        headers = {"X-Forwarded-Proto": "https"}
        faro = client.post("/telemetry", data=b"{}", headers=headers)
        posthog = client.post("/telemetry/posthog/e/", data=b"{}", headers=headers)

    assert faro.status_code == 404
    assert posthog.status_code == 404
    assert captured_requests == []
