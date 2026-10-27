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
import re
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
    """What the browser enforces today: inline blocks and eval still allowed, everything else tight.

    No handler attributes (onclick="..."): step 2 moved every one to app/ui/shared/actions.js.
    """
    return "; ".join(
        [
            *_shared(framable),
            f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {_CF_SCRIPT}",
            "script-src-attr 'none'",
        ]
    )


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


# Paths can carry credentials too (GL-S04): an invite link is /invite/<token>, and any other
# long token-shaped segment (24+ URL-safe characters mixing letters and digits) is treated the
# same way. Record ids (UUIDs) and script names stay, so a report still says which page and
# script were involved.
_INVITE_PATH = re.compile(r"(/invite/)[^/?#\s\"']+", re.IGNORECASE)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_TOKEN_SEGMENT = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])")
_SECRET_PARAM = re.compile(r"([?&](?:token|code|invite|key|secret|password|state)=)[^&#\s\"']*", re.IGNORECASE)
REDACTED = "[redacted]"


def redact_path(text: str) -> str:
    """``text`` with invite tokens, token-shaped path segments and secret parameters removed."""
    text = _INVITE_PATH.sub(r"\1" + REDACTED, text)
    text = _SECRET_PARAM.sub(r"\1" + REDACTED, text)
    return _TOKEN_SEGMENT.sub(_token_or_name, text)


def _token_or_name(match: re.Match) -> str:
    word = match.group(0)
    if _UUID.match(word) or not (re.search(r"[0-9]", word) and re.search(r"[A-Za-z]", word)):
        return word
    return REDACTED


def _origin_only(url: str) -> str:
    """A URL down to what the report needs: no query, no fragment, no token in the path.

    Raises ``ValueError`` for a URL that can't be parsed; the caller drops that report.
    """
    if not url or "://" not in url:
        return redact_path((url or "")[:40])  # keywords such as "inline", "eval"
    parts = urlsplit(url)
    return redact_path(f"{parts.scheme}://{parts.netloc}{parts.path}")[:300]


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

        line = pick("line-number", "lineNumber") or None
        try:
            violation = {
                "directive": str(pick("effective-directive", "effectiveDirective", "violated-directive"))[:60],
                "blocked": _origin_only(str(pick("blocked-uri", "blockedURL"))),
                "page": redact_path(urlsplit(str(pick("document-uri", "documentURL"))).path)[:200],
                "source": _origin_only(str(pick("source-file", "sourceFile"))),
                "line": line if isinstance(line, int) and not isinstance(line, bool) else None,
                # Redacted before it is cut short, so a quoted invite link can't survive half-cut.
                "sample": redact_path(str(pick("script-sample", "sample"))[:200])[:40],
            }
        except ValueError:
            continue  # an unparseable URL: drop this report, keep the rest of the batch
        out.append(violation)
    return out
