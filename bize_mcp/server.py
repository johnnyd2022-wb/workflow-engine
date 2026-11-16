"""The ASGI app: MCP over Streamable HTTP at ``/mcp``, ``/healthz`` and the protected-resource metadata.

Stateless: every request stands alone (no session ids, nothing kept between requests except a
60-second identity cache and a 5-minute catalogue cache, both keyed by hashes). Run it with
``uvicorn bize_mcp.server:app``; configuration comes from the environment (see ``config.py``).

Authentication is the app's job. This server only insists on a bearer token being present
(``401`` with the RFC 9728 ``resource_metadata`` pointer otherwise), forwards it in the outbound
``Authorization`` header, and turns the app's own 401 into a 401 of its own so the assistant signs in
again.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import MCPError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bize_mcp.auth import IdentityCache, token_key
from bize_mcp.catalogue import Catalogue
from bize_mcp.client import AppClient
from bize_mcp.config import METADATA_PATH, Config, ConfigError
from bize_mcp.errors import ToolFailureError, UnauthorizedError
from bize_mcp.knowledge import Knowledge
from bize_mcp.logging_setup import configure_logging, install_redaction, redact, redact_value
from bize_mcp.ratelimit import Window
from bize_mcp.shaping import clip_text
from bize_mcp.tools import TOOLS, ToolContext
from bize_mcp.tools.execute import new_window
from bize_mcp.validation import check_arguments

logger = logging.getLogger("bize_mcp.server")

INSTRUCTIONS = (
    "Biz-E is a manufacturing and inventory system for small producers. Work in four steps: "
    "discover (find the concept and the operations), docs (read them), execute (run read-only "
    "operations, up to 5 at a time), then explain using the actual records. Never assume physically "
    "present stock is usable, and never treat a null cost as zero."
)

# The request's token and whether the app refused it, visible to the tool handlers the SDK runs.
_current: contextvars.ContextVar[_RequestState | None] = contextvars.ContextVar("bize_request", default=None)


@dataclass
class _RequestState:
    token: str = field(repr=False)
    unauthorized: bool = False


_TOKEN_SYNTAX = re.compile(r"[A-Za-z0-9\-._~+/]+=*")


def _bearer(request_headers) -> str | None:
    value = request_headers.get("authorization", "")
    if value[:7].lower() != "bearer ":
        return None
    token = value[7:].strip()
    # A bearer token is plain printable ASCII; anything else cannot be one of ours, so it is a 401.
    return token if token and len(token) <= 512 and _TOKEN_SYNTAX.fullmatch(token) else None


def build_server(config: Config, client: AppClient, knowledge: Knowledge) -> tuple[Server, IdentityCache]:
    identities = IdentityCache(client)
    calls = Window(120, 60.0)  # every tool call, per caller: discover and docs are cheap, not free
    executes = new_window()
    catalogue = Catalogue(client)

    def listed() -> list[types.Tool]:
        return [
            types.Tool(
                name=tool.name,
                description=tool.full_description,
                input_schema=tool.input_schema,
                annotations=types.ToolAnnotations(read_only_hint=True, open_world_hint=False),
            )
            for tool in TOOLS.values()
        ]

    def state() -> _RequestState:
        current = _current.get()
        if current is None:  # only possible if the handler is reached without going through the endpoint
            raise MCPError(types.INVALID_REQUEST, "Not signed in.")
        return current

    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        current = state()
        try:
            await identities.identity_for(current.token)  # a bad token is a 401 here, not at the first call
        except UnauthorizedError:
            current.unauthorized = True
            return types.ListToolsResult(tools=[])
        except ToolFailureError as failure:
            raise MCPError(types.INVALID_REQUEST, failure.message) from None
        return types.ListToolsResult(tools=listed())

    async def on_call_tool(ctx, params) -> types.CallToolResult:
        current = state()
        started = time.monotonic()
        tool = TOOLS.get(params.name)
        if tool is None:
            raise MCPError(types.INVALID_PARAMS, "Unknown tool. The tools are discover, docs and execute.")
        try:
            arguments = check_arguments(tool.name, tool.input_schema, params.arguments)
            identity = await identities.identity_for(current.token)
            wait = calls.hit(identity.grant_id or token_key(current.token), time.monotonic())
            if wait is not None:
                raise ToolFailureError(
                    f"Too many requests this minute. Try again in {wait} seconds.",
                    kind="rate_limited",
                    retry_after_seconds=wait,
                )
            tool_context = ToolContext(client, current.token, identity, catalogue, knowledge, executes)
            structured = await tool.handler(tool_context, arguments)
        except UnauthorizedError:
            current.unauthorized = True
            return _failure("Your Biz-E sign-in is no longer valid.", {"error": {"kind": "unauthorized"}})
        except ToolFailureError as failure:
            logger.info("tool_call tool=%s outcome=%s", tool.name, failure.kind)
            return _failure(failure.message, failure.as_data())
        logger.info("tool_call tool=%s outcome=ok ms=%d", tool.name, (time.monotonic() - started) * 1000)
        return _success(structured)

    server = Server(
        "bize-mcp",
        version="1.0",
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    return server, identities


def _scrub(structured: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The result as JSON text and as an object, with anything shaped like a token removed.

    A token can only get here if the model typed it into an argument that is echoed back; this keeps
    "no token in any output" true whatever the input was.
    """
    clean = redact_value(structured)
    return json.dumps(clean, separators=(",", ":"), ensure_ascii=False), clean


def _success(structured: dict[str, Any]) -> types.CallToolResult:
    text, data = _scrub(structured)
    # ``execute`` reports ``ok: false`` when any of its calls failed: the results are still all there.
    failed = data.get("ok") is False
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], structured_content=data, is_error=failed
    )


def _failure(message: str, data: dict[str, Any]) -> types.CallToolResult:
    _, data = _scrub(data)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=redact(clip_text(message, 500)))],
        structured_content=data,
        is_error=True,
    )


class McpEndpoint:
    """``/mcp``: demand a bearer token, run the SDK, and turn the app's 401 into a real HTTP 401."""

    def __init__(self, config: Config, manager: StreamableHTTPSessionManager):
        self.config, self.manager = config, manager

    def challenge(self, error: bool = False) -> dict[str, str]:
        parts = ['error="invalid_token"'] if error else []
        parts.append(f'resource_metadata="{self.config.metadata_url}"')
        return {"WWW-Authenticate": "Bearer " + ", ".join(parts)}

    async def __call__(self, scope, receive, send) -> None:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        token = _bearer(headers)
        if token is None:
            await JSONResponse({"error": "unauthorized"}, status_code=401, headers=self.challenge())(
                scope, receive, send
            )
            return
        current = _RequestState(token)
        reset = _current.set(current)
        refused = False

        async def guarded_send(message) -> None:
            nonlocal refused
            if not current.unauthorized:
                await send(message)
                return
            if message["type"] == "http.response.start" and not refused:
                refused = True
                reply = JSONResponse({"error": "invalid_token"}, status_code=401, headers=self.challenge(error=True))
                await reply(scope, receive, send)

        try:
            await self.manager.asgi_app(scope, receive, guarded_send)
        finally:
            _current.reset(reset)


def create_app(
    config: Config, *, transport: httpx2.AsyncBaseTransport | None = None, knowledge: Knowledge | None = None
):
    install_redaction()
    client = AppClient(config, transport=transport)
    knowledge = knowledge or Knowledge.load(Path(config.knowledge_dir))
    if not knowledge.topics:
        raise ConfigError(f"No knowledge topics found in {config.knowledge_dir!r}: set BIZE_KNOWLEDGE_DIR.")
    mcp_server, _ = build_server(config, client, knowledge)
    manager = StreamableHTTPSessionManager(app=mcp_server, json_response=True, stateless=True)
    endpoint = McpEndpoint(config, manager)

    async def metadata(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "resource": config.public_url,
                "authorization_servers": [config.issuer_url],
                "scopes_supported": ["bize.read"],
                "bearer_methods_supported": ["header"],
            }
        )

    async def healthz(request: Request) -> JSONResponse:
        if request.query_params.get("deep"):
            if await client.ping("/healthcheck"):
                return JSONResponse({"ok": True, "app": "ok"})
            return JSONResponse({"ok": False, "app": "unreachable"}, status_code=503)
        return JSONResponse({"ok": True})

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            try:
                yield
            finally:
                await client.aclose()

    path = httpx2.URL(config.public_url).path.rstrip("/") or "/mcp"
    routes = [
        Route(path, endpoint=endpoint),
        Route(path + "/", endpoint=endpoint),
        Route(METADATA_PATH, metadata, methods=["GET"]),
        Route(f"{METADATA_PATH}{path}", metadata, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
    ]
    return Starlette(routes=routes, lifespan=lifespan)


class _LazyApp:
    """``uvicorn bize_mcp.server:app``: built from the environment on first use, so importing never fails."""

    def __init__(self) -> None:
        self._app: Starlette | None = None

    async def __call__(self, scope, receive, send) -> None:
        if self._app is None:
            configure_logging()
            self._app = create_app(Config.from_env())
        await self._app(scope, receive, send)


app = _LazyApp()
