"""bize_mcp's one deploy setting beyond the three addresses: whether to verify the app's certificate.

Public MCP 8.2d. The app serves a self-signed certificate under a name that is not its container's, so
the container deployed by scripts/run_mcp.sh sets ``BIZE_API_VERIFY_TLS=false`` for the hop to the app
on the private Docker network. Everywhere else the default stays strict: an unset or empty value
verifies, and an unrecognised one is refused, so a typo can never switch verification off.
"""

from __future__ import annotations

import http.server
import ssl
import threading
from pathlib import Path

import pytest

from bize_mcp.client import AppClient
from bize_mcp.config import Config, ConfigError
from tests.mcp_server.support import make_config, run_coroutine

ROOT = Path(__file__).resolve().parents[2]

ENV = {
    "BIZE_API_BASE_URL": "https://workflow-engine-test:8001",
    "MCP_PUBLIC_URL": "https://mcp-test.biz-e.app/mcp",
    "BIZE_ISSUER_URL": "https://test.biz-e.app",
}


def test_certificates_are_verified_by_default():
    assert Config.from_env(ENV).verify_tls is True
    assert make_config().verify_tls is True


@pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "off", " false "])
def test_the_explicit_opt_out_turns_verification_off(value):
    assert Config.from_env({**ENV, "BIZE_API_VERIFY_TLS": value}).verify_tls is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", ""])
def test_the_explicit_opt_in_or_an_empty_value_verifies(value):
    assert Config.from_env({**ENV, "BIZE_API_VERIFY_TLS": value}).verify_tls is True


@pytest.mark.parametrize("value", ["flase", "disable", "none", "2"])
def test_an_unrecognised_value_is_refused_rather_than_guessed(value):
    with pytest.raises(ConfigError, match="BIZE_API_VERIFY_TLS"):
        Config.from_env({**ENV, "BIZE_API_VERIFY_TLS": value})


@pytest.fixture
def tls_app():
    """A server that answers over TLS with the app's own self-signed certificate (a name it doesn't cover)."""
    cert, key = ROOT / "app/tls/app_cert.pem", ROOT / "app/tls/app_cert.key"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _ping(base_url: str, **overrides) -> bool:
    async def run() -> bool:
        client = AppClient(make_config(api_base_url=base_url, **overrides))
        try:
            return await client.ping("/healthcheck")
        finally:
            await client.aclose()

    return run_coroutine(run())


def test_the_client_refuses_a_self_signed_app_by_default(tls_app):
    assert _ping(tls_app) is False


def test_the_client_reaches_a_self_signed_app_only_when_told_not_to_verify(tls_app):
    assert _ping(tls_app, verify_tls=False) is True
