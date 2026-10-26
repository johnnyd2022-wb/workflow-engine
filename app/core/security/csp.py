"""Content Security Policy for the app's pages (GL-S03).

The enforced policy still allows inline and evaluated script: Alpine's standard build
evaluates its attributes, and about eighty templates use inline ``on*`` handlers. Moving
off both is a migration over several MRs (``docs/csp-migration-plan.md``). Meanwhile:

- every response gets a fresh **nonce**, and every inline ``<script>`` in a template carries
  it (``nonce="{{ csp_nonce() }}"``), so the strict policy can be switched on without
  touching those blocks again;
- the strict target policy is sent as ``Content-Security-Policy-Report-Only``, and the
  browser reports what it would block to ``/csp-report``, which logs it. That log is the
  migration's to-do list, and an empty one is the signal to enforce.
"""

from __future__ import annotations

import json
import secrets
from urllib.parse import urlsplit

from flask import request

REPORT_PATH = "/csp-report"
MAX_REPORT_BYTES = 16 * 1024

# Cloudflare's RUM beacon is injected by the CF proxy on the deployed environments.
_CF_SCRIPT = "https://static.cloudflareinsights.com"
_CF_CONNECT = "https://cloudflareinsights.com"


def csp_nonce() -> str:
    """This response's nonce, made on first use.

    Kept in the request's WSGI environ, not on ``g``: a reused app context can carry ``g``
    from an earlier request, and a nonce seen twice is a nonce an attacker can learn.
    """
    nonce = request.environ.get("biz_e.csp_nonce")
    if nonce is None:
        nonce = request.environ["biz_e.csp_nonce"] = secrets.token_urlsafe(18)
    return nonce


def _frame_ancestors(framable: bool) -> str:
    return "frame-ancestors 'self'" if framable else "frame-ancestors 'none'"


def _shared(framable: bool) -> list[str]:
    """Everything but script: the same in the enforced and the target policy."""
    return [
        "default-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        f"connect-src 'self' {_CF_CONNECT}",
        # PostHog's vendored session-recording bundle starts its rrweb compression worker
        # from a data: URI; without this no recording snapshots are captured.
        "worker-src 'self' data: blob:",
        "object-src 'none'",
        "base-uri 'self'",
        _frame_ancestors(framable),
    ]


def enforced_policy(*, framable: bool = False) -> str:
    """What the browser enforces today: inline and eval still allowed, everything else tight."""
    return "; ".join([*_shared(framable), f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {_CF_SCRIPT}"])


def report_only_policy(nonce: str, *, framable: bool = False) -> str:
    """The target: script only from our own files or a nonce, no handlers in attributes, no eval."""
    return "; ".join(
        [
            *_shared(framable),
            # report-sample: a report carries the first 40 characters of what was blocked.
            f"script-src 'self' 'nonce-{nonce}' 'report-sample' {_CF_SCRIPT}",
            "script-src-attr 'none' 'report-sample'",
            f"report-uri {REPORT_PATH}",
        ]
    )


def _origin_only(url: str) -> str:
    """A URL down to what the report needs: no query, no fragment (they can carry tokens)."""
    if not url or "://" not in url:
        return (url or "")[:40]  # keywords such as "inline", "eval"
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"[:300]


def parse_report(raw: bytes) -> list[dict]:
    """Violations from a report body, in either the ``report-uri`` or the Reporting API shape."""
    if not raw or len(raw) > MAX_REPORT_BYTES:
        return []
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return []
    items = body if isinstance(body, list) else [body]
    out = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        report = item.get("csp-report") or item.get("body") or {}
        if not isinstance(report, dict):
            continue

        def pick(*keys):
            for key in keys:
                value = report.get(key)
                if value not in (None, ""):
                    return value
            return ""

        out.append(
            {
                "directive": str(pick("effective-directive", "effectiveDirective", "violated-directive"))[:60],
                "blocked": _origin_only(str(pick("blocked-uri", "blockedURL"))),
                "page": urlsplit(str(pick("document-uri", "documentURL"))).path[:200],
                "source": _origin_only(str(pick("source-file", "sourceFile"))),
                "line": pick("line-number", "lineNumber") or None,
                "sample": str(pick("script-sample", "sample"))[:40],
            }
        )
    return out
