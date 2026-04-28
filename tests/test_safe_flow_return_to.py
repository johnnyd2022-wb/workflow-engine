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
        "data:text/html,<html></html>",
        "vbscript:msgbox(1)",
        "core/flows",
        "?tab=1",
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
    ],
)
def test_relative_app_paths_pass_through(value, expected):
    assert _safe_flow_return_to(value, PROCESS_ID) == expected
