"""GL-S03: the CSP's first step. Pages carry a per-response nonce on every inline script, the
strict target policy is sent report-only, and the browser's reports are logged without the
query strings or fragments that can carry tokens."""

import json
import re
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.core.security import csp
from tests.test_auth_password_session import PASSWORD
from tests.test_auth_password_session import account as _account  # noqa: F401 -- fixture re-export

APP = Path(__file__).resolve().parents[1] / "app"
# Its own bundled page with its own policy (app_factory: /landing-diagram).
OWN_POLICY = {"biz-e-diagram-landing.html"}


def _directives(header: str) -> dict[str, str]:
    return {part.split(" ", 1)[0]: part.split(" ", 1)[1] if " " in part else "" for part in header.split("; ")}


@pytest.fixture
def signed_in(_account):  # noqa: F811
    return _account["make_client"](PASSWORD)


def test_a_page_carries_one_nonce_on_every_inline_script_and_in_the_report_only_policy(signed_in):
    resp = signed_in.get("/core/dashboard")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    target = _directives(resp.headers["Content-Security-Policy-Report-Only"])
    nonce = re.fullmatch(r"'self' 'nonce-([\w-]+)' 'report-sample' \S+", target["script-src"]).group(1)

    inline = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", html)
    assert inline, "the dashboard has inline scripts to check"
    for attrs in inline:
        if 'type="application/json"' in attrs:
            continue
        assert f'nonce="{nonce}"' in attrs, f"inline script without this response's nonce: <script{attrs}>"
    # htmx gives the same nonce to inline scripts it runs after a boosted swap.
    assert f'"inlineScriptNonce":"{nonce}"' in html
    assert target["script-src-attr"] == "'none' 'report-sample'"
    assert target["report-uri"] == "/csp-report"


def test_every_response_gets_a_fresh_nonce(signed_in):
    first = signed_in.get("/core/dashboard").headers["Content-Security-Policy-Report-Only"]
    second = signed_in.get("/core/dashboard").headers["Content-Security-Policy-Report-Only"]
    assert first != second


def test_the_enforced_policy_closes_plugins_base_tags_and_framing(signed_in):
    resp = signed_in.get("/core/dashboard")
    enforced = _directives(resp.headers["Content-Security-Policy"])
    assert enforced["object-src"] == "'none'"
    assert enforced["base-uri"] == "'self'"
    assert enforced["frame-ancestors"] == "'none'"
    assert "unpkg.com" not in resp.headers["Content-Security-Policy"]


def test_the_landing_page_may_frame_its_diagram_and_nothing_else_may(signed_in):
    resp = signed_in.get("/landing-diagram")
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    page = signed_in.get("/")
    assert _directives(page.headers["Content-Security-Policy"])["frame-ancestors"] == "'none'"


def test_json_responses_get_no_report_only_policy(signed_in):
    resp = signed_in.get("/api/core/getting-started")
    assert resp.mimetype == "application/json"
    assert "Content-Security-Policy-Report-Only" not in resp.headers


def test_a_report_is_logged_without_query_strings_and_needs_no_session(_account):  # noqa: F811
    anonymous = _account["make_client"]()
    report = {
        "csp-report": {
            "document-uri": "https://biz-e.app/auth/accept-invite?token=SECRET#frag",
            "effective-directive": "script-src-attr",
            "blocked-uri": "inline",
            "source-file": "https://biz-e.app/core/inventory?token=SECRET",
            "line-number": 12,
            "script-sample": "openModal('x')",
        }
    }
    with capture_logs() as logs:
        resp = anonymous.post("/csp-report", data=json.dumps(report), content_type="application/csp-report")
    assert resp.status_code == 204
    (entry,) = [e for e in logs if e["event"] == "csp_violation"]
    assert entry["directive"] == "script-src-attr"
    assert entry["page"] == "/auth/accept-invite"
    assert entry["source"] == "https://biz-e.app/core/inventory"
    assert entry["line"] == 12
    assert "SECRET" not in json.dumps(entry)


def test_reporting_api_batches_are_read_too():
    raw = json.dumps(
        [
            {
                "type": "csp-violation",
                "body": {
                    "documentURL": "https://biz-e.app/core/dashboard",
                    "effectiveDirective": "script-src-elem",
                    "blockedURL": "https://evil.example/x.js?k=1",
                    "sample": "",
                },
            }
        ]
    ).encode()
    (violation,) = csp.parse_report(raw)
    assert violation == {
        "directive": "script-src-elem",
        "blocked": "https://evil.example/x.js",
        "page": "/core/dashboard",
        "source": "",
        "line": None,
        "sample": "",
    }


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1, 2]", json.dumps({"csp-report": "x"}).encode()])
def test_malformed_reports_are_ignored(raw):
    assert csp.parse_report(raw) == []


def test_an_oversized_report_is_ignored():
    raw = json.dumps({"csp-report": {"effective-directive": "script-src", "script-sample": "x" * csp.MAX_REPORT_BYTES}})
    assert csp.parse_report(raw.encode()) == []


def test_every_inline_script_in_a_template_carries_the_nonce():
    """A new inline <script> without the nonce would be blocked once the policy is enforced."""
    missing = []
    for path in APP.rglob("*.html"):
        if path.name in OWN_POLICY:
            continue
        for match in re.finditer(r"<script(?![^>]*\bsrc=)([^>]*)>", path.read_text(encoding="utf-8")):
            attrs = match.group(1)
            if "application/json" in attrs or "csp_nonce()" in attrs:
                continue
            missing.append(f"{path.relative_to(APP)}: <script{attrs}>")
    assert not missing, 'add nonce="{{ csp_nonce() }}":\n' + "\n".join(missing)
