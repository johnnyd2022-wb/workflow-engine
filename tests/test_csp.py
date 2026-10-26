"""GL-S03: the CSP's first step. Pages carry a per-response nonce on every inline script, the
strict target policy is sent report-only, and the browser's reports are logged without the
query strings or fragments that can carry tokens."""

import io
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


# --- review of !578: tokens in paths, malformed URLs, the body read ----------------------------


@pytest.mark.parametrize("shape", ["report-uri", "reporting-api"])
def test_an_invite_token_in_a_path_never_reaches_the_log(_account, shape):  # noqa: F811
    token = "Ab3" * 10  # token-shaped (letters and digits), but not a real-looking secret
    invite = f"https://biz-e.app/invite/{token}"
    if shape == "report-uri":
        body = {
            "csp-report": {
                "document-uri": invite,
                "effective-directive": "script-src-elem",
                "blocked-uri": f"https://evil.example/invite/{token}/x.js",
                "source-file": invite,
                "script-sample": f"location='/invite/{token}'",
            }
        }
    else:
        body = [
            {
                "type": "csp-violation",
                "body": {
                    "documentURL": invite,
                    "effectiveDirective": "script-src-elem",
                    "blockedURL": f"https://evil.example/invite/{token}/x.js",
                    "sourceFile": invite,
                    "sample": f"location='/invite/{token}'",
                },
            }
        ]
    with capture_logs() as logs:
        resp = _account["make_client"]().post(
            "/csp-report", data=json.dumps(body), content_type="application/csp-report"
        )
    assert resp.status_code == 204
    (entry,) = [e for e in logs if e["event"] == "csp_violation"]
    assert token not in json.dumps(entry) and token[:12] not in json.dumps(entry)
    # The route and directive survive, so the report is still worth reading.
    assert entry["page"] == "/invite/[redacted]"
    assert entry["directive"] == "script-src-elem"


def test_script_names_and_record_ids_are_kept():
    assert csp.redact_path("https://biz-e.app/static/process-flow-next-steps-steps.js").endswith("steps-steps.js")
    record = "/core/executions/0ceaf801-31e3-47dd-a56c-c04832a50a38"
    assert csp.redact_path(record) == record


def test_a_malformed_url_is_dropped_and_the_rest_of_the_batch_kept(_account):  # noqa: F811
    batch = [
        {"type": "csp-violation", "body": {"effectiveDirective": "script-src", "blockedURL": "https://["}},
        {"type": "csp-violation", "body": {"effectiveDirective": "script-src", "documentURL": "http://[::1"}},
        {"type": "csp-violation", "body": {"effectiveDirective": "style-src", "documentURL": "https://biz-e.app/core"}},
    ]
    with capture_logs() as logs:
        resp = _account["make_client"]().post(
            "/csp-report", data=json.dumps(batch), content_type="application/reports+json"
        )
    assert resp.status_code == 204
    assert [e["directive"] for e in logs if e["event"] == "csp_violation"] == ["style-src"]


def test_an_oversized_report_is_refused_without_being_read(_account, monkeypatch):  # noqa: F811
    seen = []
    real = csp.parse_report
    monkeypatch.setattr(csp, "parse_report", lambda raw: seen.append(len(raw)) or real(raw))
    client = _account["make_client"]()
    big = b"x" * (1024 * 1024)
    declared = client.post("/csp-report", data=big, content_type="application/csp-report")
    assert declared.status_code == 413 and seen == []

    # No Content-Length (a chunked upload): the read itself must stop.
    streamed = client.post(
        "/csp-report",
        input_stream=io.BytesIO(big),
        content_type="application/reports+json",
        environ_overrides={"wsgi.input_terminated": True, "CONTENT_LENGTH": ""},
    )
    assert streamed.status_code == 204
    assert seen == [csp.MAX_REPORT_BYTES + 1]


# --- step 2: no handler attributes ---------------------------------------------------------------

_HANDLER_ATTR = re.compile(r"""\son[a-z]+\s*=\s*\\?["']""")
_VENDOR = ("faro-web-sdk", "posthog-array", "htmx.min", ".min.js")


def test_no_template_or_script_writes_an_inline_handler():
    """Ratchet: an on*="" attribute is blocked by script-src-attr 'none'. Use data-action instead."""
    found = []
    for path in [*APP.rglob("*.html"), *APP.rglob("*.js")]:
        if path.name in OWN_POLICY or any(v in path.name for v in _VENDOR):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _HANDLER_ATTR.search(line):
                found.append(f"{path.relative_to(APP)}:{number}: {line.strip()[:100]}")
    assert not found, "move these to data-action (app/ui/shared/actions.js):\n" + "\n".join(found)


def test_the_enforced_policy_now_forbids_handler_attributes(signed_in):
    enforced = _directives(signed_in.get("/core/dashboard").headers["Content-Security-Policy"])
    assert enforced["script-src-attr"] == "'none'"
