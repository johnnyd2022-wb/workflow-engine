"""Design review S4: bize_mcp's own windows (every tool call, and execute) can live in Valkey.

The server keeps its 120-a-minute tool-call window and its 30-a-minute execute window in process
memory. That is right for one process; any second process (a restart overlap, a second replica) gets a
fresh budget. With ``BIZE_RATELIMIT_URI`` (and the ``VALKEY_PASSWORD`` it is told separately) both
windows live in the shared store. Without it nothing changes.
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlsplit

import pytest

from bize_mcp.config import Config, ConfigError
from bize_mcp.errors import ToolFailureError
from bize_mcp.ratelimit import SharedStore, Window
from tests.mcp_server.support import Mcp, json_response, make_config, stub_app
from tests.valkey_support import valkey_uri  # noqa: F401  (fixture)

HOLDS = "/api/core/holds"
ENV = {
    "BIZE_API_BASE_URL": "https://workflow-engine-test:8001",
    "MCP_PUBLIC_URL": "https://mcp-test.biz-e.app/mcp",
    "BIZE_ISSUER_URL": "https://test.biz-e.app",
}


def _split(uri: str) -> tuple[str, str]:
    """``redis://:pw@host:port/db`` -> (``redis://host:port/db``, ``pw``): how run_mcp.sh passes them."""
    parts = urlsplit(uri)
    return f"redis://{parts.hostname}:{parts.port}{parts.path}", parts.password or ""


# --- config ------------------------------------------------------------------------------------


def test_s4_no_uri_means_in_process_windows():
    config = Config.from_env(ENV)
    assert config.ratelimit_uri is None
    assert SharedStore.from_config(config) is None


def test_s4_the_uri_and_password_are_read_and_the_password_never_shows():
    config = Config.from_env({**ENV, "BIZE_RATELIMIT_URI": "redis://valkey-test:6379/0", "VALKEY_PASSWORD": "s3cr3t"})
    assert config.ratelimit_uri == "redis://valkey-test:6379/0"
    assert config.ratelimit_password == "s3cr3t"
    assert "s3cr3t" not in repr(config)


@pytest.mark.parametrize(
    "uri",
    ["http://valkey-test:6379/0", "redis://:pw@valkey-test:6379/0", "redis://user:pw@valkey-test:6379/0", "redis://"],
)
def test_s4_a_wrong_uri_is_refused(uri):
    with pytest.raises(ConfigError, match="BIZE_RATELIMIT_URI"):
        Config.from_env({**ENV, "BIZE_RATELIMIT_URI": uri, "VALKEY_PASSWORD": "pw"})


def test_s4_a_uri_without_its_password_is_refused():
    with pytest.raises(ConfigError, match="VALKEY_PASSWORD"):
        Config.from_env({**ENV, "BIZE_RATELIMIT_URI": "redis://valkey-test:6379/0"})


# --- the window --------------------------------------------------------------------------------


def test_s4_two_processes_share_one_window_in_valkey(valkey_uri):  # noqa: F811
    uri, password = _split(valkey_uri)
    config = make_config(ratelimit_uri=uri, ratelimit_password=password)
    first, second = (Window(3, 60.0, store=SharedStore.from_config(config), name="t") for _ in range(2))
    key = f"grant-{uuid.uuid4()}"
    results = [(first if i % 2 == 0 else second).hit(key, 0.0) for i in range(5)]
    assert results[:3] == [None, None, None]
    assert all(isinstance(r, int) and 1 <= r <= 61 for r in results[3:]), results


def test_s4_one_callers_window_is_not_anothers(valkey_uri):  # noqa: F811
    uri, password = _split(valkey_uri)
    window = Window(1, 60.0, store=SharedStore.from_config(make_config(ratelimit_uri=uri, ratelimit_password=password)))
    assert window.hit(f"a-{uuid.uuid4()}", 0.0) is None
    assert window.hit(f"b-{uuid.uuid4()}", 0.0) is None


def test_s4_an_unreachable_store_refuses_the_call_rather_than_counting_nothing():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    store = SharedStore.from_config(make_config(ratelimit_uri=f"redis://127.0.0.1:{port}/0", ratelimit_password="x"))
    with pytest.raises(ToolFailureError) as failure:
        Window(30, 60.0, store=store).hit("grant-1", 0.0)
    assert failure.value.kind == "unavailable"
    assert failure.value.retry_after_seconds and failure.value.retry_after_seconds >= 1


# --- end to end: two servers, one execute budget -------------------------------------------------


def test_s4_two_servers_on_one_store_share_the_execute_budget(valkey_uri):  # noqa: F811
    uri, password = _split(valkey_uri)
    config = make_config(ratelimit_uri=uri, ratelimit_password=password)
    token = f"bza_{uuid.uuid4().hex}"
    holds = {HOLDS: json_response(200, {"holds": []})}
    call = {"id": "a", "operation_id": "list_open_holds"}
    with Mcp(stub_app(holds, grant_per_token=True), config) as first:
        results = [first.execute(token, call) for _ in range(30)]
    with Mcp(stub_app(holds, grant_per_token=True), config) as second:
        refused = second.execute(token, call)
    assert not any(r.is_error for r in results)
    assert refused.is_error and refused.data["error"]["kind"] == "rate_limited"
