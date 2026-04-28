"""Unit tests for open-redirect guard used by execute-step / flow return URLs."""

import pytest

from app.core.backend.backend import _safe_flow_return_to

PROCESS_ID = "3e4e9666-2536-4545-821b-fb4945b54872"
EXPECTED_DEFAULT = f"/core/flows?id={PROCESS_ID}"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "https://evil.com/phish",
        "http://localhost/foo",
        "//evil.com/path",
        "javascript:alert(1)",
        "Javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<html></html>",
        "vbscript:msgbox(1)",
        "core/flows",
        "?tab=1",
        # Path traversal & internal route escape
        "/core/flows/../../admin",
        # Outside /core/flows namespace
        "/core/inventory",
        "/admin",
        # Encoded bypass attempts
        "%2F%2Fevil.com",
        "/%2F%2Fevil.com",
        "%68%74%74%70%3A%2F%2Fexample.com",
        # urlparse / slash quirks (must not become external redirect)
        "/\\evil.com",
        "/evil.com:80",
        # Dangerous fragment on otherwise-valid path
        "/core/flows#//evil.com",
        "/core/flows#https://evil.com",
    ],
)
def test_unsafe_or_empty_returns_process_workspace_default(value):
    assert _safe_flow_return_to(value, PROCESS_ID) == EXPECTED_DEFAULT


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/core/flows", "/core/flows"),
        ("/core/flows?id=abc", "/core/flows?id=abc"),
        ("/core/flows/batches/start?draft=1", "/core/flows/batches/start?draft=1"),
        ("  /core/flows  ", "/core/flows"),
        ("/core/flows   ", "/core/flows"),
        ("/core/flows\n", "/core/flows"),
        ("/core/flows\t", "/core/flows"),
        # Query embedding // is path-safe string match only (browser may still interpret); kept as pass if path ok
        ("/core/flows?next=//evil.com", "/core/flows?next=//evil.com"),
    ],
)
def test_flows_workspace_paths_pass_through(value, expected):
    assert _safe_flow_return_to(value, PROCESS_ID) == expected
