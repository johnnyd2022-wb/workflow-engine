from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import patch

from flask import Flask
from werkzeug.test import EnvironBuilder

from app.api.session_interface import ClockSkewTolerantTestSessionInterface


def _app_and_interface():
    app = Flask(__name__)
    app.secret_key = "test-session-interface-key"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    interface = ClockSkewTolerantTestSessionInterface()
    return app, interface


def _open(interface, app, value):
    request = EnvironBuilder(path="/", headers={"Cookie": f"session={value}"}).get_request()
    return interface.open_session(app, request)


def test_test_session_interface_accepts_a_bounded_backwards_clock_step():
    app, interface = _app_and_interface()
    serializer = interface.get_signing_serializer(app)
    with patch("itsdangerous.timed.time.time", return_value=time.time() + 5):
        cookie = serializer.dumps({"user_id": "still-signed"})

    assert _open(interface, app, cookie)["user_id"] == "still-signed"


def test_test_session_interface_keeps_normally_expired_cookies_expired():
    app, interface = _app_and_interface()
    serializer = interface.get_signing_serializer(app)
    with patch("itsdangerous.timed.time.time", return_value=time.time() - 31 * 24 * 60 * 60):
        cookie = serializer.dumps({"user_id": "expired"})

    assert "user_id" not in _open(interface, app, cookie)
