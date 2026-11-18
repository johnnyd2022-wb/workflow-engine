"""A thin HTTP client for the Biz-E app. The only place bize_mcp talks to it.

Rules this module keeps (each is pinned by a test):

* the caller's token goes in the ``Authorization`` header of that one call, and nowhere else;
* nothing is shared between callers: no cookies are stored (the app may set some), and a redirect is
  never followed, so a token can't be carried to another host;
* ``X-Forwarded-Proto: https`` is always sent, because the app redirects plain HTTP to HTTPS and a hop
  that is not TLS (a local run, the test harness) would otherwise be bounced;
* only ``GET`` exists here. The MVP reads; it never writes, and nothing is retried.

The app's answers become the spec's tool errors in ``_raise_for``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

import httpx2

from bize_mcp.config import Config
from bize_mcp.errors import (
    NO_PERMISSION,
    NOT_ALLOWED,
    NOT_AVAILABLE,
    PROBLEM,
    READ_ONLY,
    ToolFailureError,
    UnauthorizedError,
)
from bize_mcp.shaping import clip_text

logger = logging.getLogger("bize_mcp.client")

MAX_BODY_BYTES = 4 * 1024 * 1024
MAX_CONCURRENT_CALLS = 32
Params = Iterable[tuple[str, str]] | dict[str, str] | None


def _error_text(response: httpx2.Response) -> tuple[str, str]:
    """(error code, error text) from a JSON error body, both empty when there is none."""
    try:
        body = response.json()
    except ValueError:
        return "", ""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, str):
            return error.strip(), error.strip()
        message = body.get("message")
        return "", message.strip() if isinstance(message, str) else ""
    return "", ""


def _retry_after(response: httpx2.Response) -> int | None:
    raw = response.headers.get("retry-after", "").strip()
    return int(raw) if raw.isdigit() and 0 <= int(raw) <= 86_400 else None


class AppClient:
    def __init__(self, config: Config, transport: httpx2.AsyncBaseTransport | None = None):
        import asyncio

        self._http = httpx2.AsyncClient(
            base_url=config.api_base_url,
            transport=transport,
            verify=config.verify_tls,
            timeout=httpx2.Timeout(config.request_timeout, connect=5.0),
            follow_redirects=False,
            headers={"Accept": "application/json", "X-Forwarded-Proto": "https", "User-Agent": "bize-mcp"},
            limits=httpx2.Limits(max_connections=64, max_keepalive_connections=16),
        )
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

        async def forget_cookies(response: httpx2.Response) -> None:
            # Whatever the app set is dropped before the next request is built: no state between callers.
            self._http.cookies.clear()

        self._http.event_hooks["response"] = [forget_cookies]

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_raw(self, path: str, token: str, params: Params = None) -> httpx2.Response:
        """One GET. Transport trouble becomes a tool error; the response is returned unjudged."""
        started = time.monotonic()
        try:
            async with self._slots:
                response = await self._http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        except httpx2.TimeoutException:
            logger.warning("app_call outcome=timeout")
            raise ToolFailureError("Biz-E took too long to answer. Try again shortly.", kind="timeout") from None
        except (httpx2.HTTPError, ValueError) as error:
            logger.warning("app_call outcome=transport_error type=%s", type(error).__name__)
            raise ToolFailureError(PROBLEM, kind="upstream_error") from None
        logger.info("app_call status=%s ms=%d", response.status_code, (time.monotonic() - started) * 1000)
        return response

    async def ping(self, path: str) -> bool:
        """An unauthenticated GET (the app's health check); True when it answers 2xx."""
        try:
            response = await self._http.get(path)
        except httpx2.HTTPError:
            return False
        return 200 <= response.status_code < 300

    async def get(self, path: str, token: str, params: Params = None, *, by_id: bool = False) -> Any:
        """The parsed JSON of a successful GET, or the spec's tool error / 401."""
        response = await self.get_raw(path, token, params)
        self._raise_for(response, by_id=by_id)
        if len(response.content) > MAX_BODY_BYTES:
            raise ToolFailureError(PROBLEM, kind="response_too_large")
        try:
            return response.json()
        except ValueError:
            logger.warning("app_call outcome=not_json status=%s", response.status_code)
            raise ToolFailureError(PROBLEM, kind="upstream_error") from None

    @staticmethod
    def _raise_for(response: httpx2.Response, *, by_id: bool) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        code, text = _error_text(response)
        if status == 401:
            raise UnauthorizedError()
        if status == 403:
            if code == "mcp_not_allowed":
                raise ToolFailureError(NOT_ALLOWED, kind="not_allowed")
            if code == "insufficient_scope":
                raise ToolFailureError(READ_ONLY, kind="read_only")
            raise ToolFailureError(NO_PERMISSION, kind="forbidden")
        if status == 404:
            if by_id:
                raise ToolFailureError("Not found", kind="not_found")
            raise ToolFailureError(NOT_AVAILABLE, kind="not_available")
        if status == 429:
            wait = _retry_after(response)
            when = f"in {wait} seconds" if wait is not None else "shortly"
            raise ToolFailureError(
                f"Biz-E is limiting how fast this connection can ask. Try again {when}.",
                kind="rate_limited",
                retry_after_seconds=wait,
            )
        if status in {400, 409, 422} and text:
            raise ToolFailureError(f"Biz-E couldn't use that request: {clip_text(text, 300)}", kind="bad_request")
        if 300 <= status < 400:
            logger.warning("app_call outcome=redirect_not_followed status=%s", status)
        raise ToolFailureError(PROBLEM, kind="upstream_error")
