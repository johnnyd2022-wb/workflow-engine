"""Assemble the OpenAPI 3.1 document, and narrow it to what one caller may reach.

``build`` is the whole document: every ``/api/`` operation, generated from the code (``generator.py``)
and the hand-written overlay (``overlay.py``). It is what ``docs/openapi.json`` holds.

``narrow`` is what a caller is shown. The document is the catalogue an assistant plans from, so it must
name nothing the caller could not call: operations their permissions do not reach are dropped, and so
are the schemas, tags and ``related_operations`` entries that only those operations used.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

from app.api.openapi.generator import DOMAINS, Operation, collect_operations
from app.api.openapi.overlay import Overlay, get_overlay
from app.core.security.access_policy import PUBLIC, allows, token_access, token_scope_includes

OPENAPI_VERSION = "3.1.0"
DOCUMENT_VERSION = "1.0.0"
COMMITTED_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"

INFO_DESCRIPTION = """\
The Biz-E JSON API: production, stock, traceability, compliance, sales and cost.

**Signing in.** A browser session uses the `session` cookie. An AI assistant uses an access token
(`Authorization: Bearer bza_...`) with the read-only scope `bize.read`, which reaches only the GET
operations marked `x-bize.mcp`. Every operation lists the schemes that work for it under `security`.

**Who may call what.** `x-bize.permission` is the permission the route requires: one name, or a list
meaning "any of these". `signed_in` means any signed-in person, `public` anyone. This document shows a
caller only the operations their own permissions reach.

**Reading the `x-bize` fields.** `domain` groups operations; `feature` is set when the operation exists
only for an organisation that has that product area (`crm`, `compliant`, `costing`); `kind` is `record`, `list` or
`calculation` (a figure Biz-E computes authoritatively, which should be read, not recomputed);
`mcp` marks the operations an assistant may call; `concepts` name the business-knowledge topics that
explain the fields; `related_operations` are the operations usually read next. `schema_status` is
`documented` when the response is described and `skeleton` when only the summary and permission are.

**Costs.** A cost that is not known is `null` beside a status that says why. It is never `0`.
"""

_RESPONSES = {
    "BadRequest": {"description": "The request was not understood: a parameter is missing or invalid."},
    "Unauthorized": {"description": "Not signed in, or the access token is invalid, expired or revoked."},
    "Forbidden": {"description": "Signed in, but the person's role does not hold the required permission."},
    "NotFound": {"description": "No such record in this organisation."},
}
_ERROR_RESPONSES = {400: "BadRequest", 401: "Unauthorized", 403: "Forbidden", 404: "NotFound"}

_ERROR_SCHEMA = {
    "type": "object",
    "description": "Every failure carries a short `error`; some also carry a stable `code` and a `message`.",
    "properties": {
        "error": {"type": "string", "description": "What went wrong, in a sentence."},
        "code": {"type": "string", "description": "A stable identifier for the failure, when there is one."},
        "message": {"type": "string", "description": "More detail, when there is any."},
    },
    "required": ["error"],
}

_SECURITY_SCHEMES = {
    "sessionCookie": {
        "type": "apiKey",
        "in": "cookie",
        "name": "session",
        "description": "The browser session set by signing in. Writes also need a CSRF token.",
    },
    "bearerToken": {
        "type": "http",
        "scheme": "bearer",
        "description": (
            "An AI assistant's access token. Read-only: the x-bize.mcp GET operations a person's role may read."
        ),
    },
}


@dataclass(frozen=True)
class BuiltDocument:
    """The whole document, plus which Flask endpoint and method each ``operationId`` is."""

    document: dict
    endpoints: dict[str, tuple[str, str]]


def _security(op: Operation, mcp: bool) -> list[dict]:
    if op.requirement == PUBLIC:
        return []
    schemes = [{"sessionCookie": []}]
    if token_scope_includes(op.endpoint, op.method, mcp=mcp):
        schemes.append({"bearerToken": []})
    return schemes


def _permission(requirement):
    return list(requirement) if isinstance(requirement, tuple) else requirement


def _parameters(op: Operation, entry: dict) -> list[dict]:
    """The route's path parameters (named by the rule), described by the overlay, then its query parameters."""
    extra = {p["name"]: p for p in entry.get("parameters", []) if p["in"] == "path"}
    unknown = sorted(set(extra) - {p["name"] for p in op.path_parameters})
    if unknown:
        raise ValueError(f"{op.operation_id}: the overlay describes path parameters the route does not have: {unknown}")
    merged = []
    for derived in op.path_parameters:
        parameter = copy.deepcopy(derived)
        over = extra.get(parameter["name"], {})
        if "description" in over:
            parameter["description"] = over["description"]
        if "schema" in over:
            parameter["schema"] = copy.deepcopy(over["schema"])
        merged.append(parameter)
    merged += [copy.deepcopy(p) for p in entry.get("parameters", []) if p["in"] != "path"]
    return merged


def _responses(op: Operation, entry: dict) -> dict:
    responses: dict[str, dict] = {}
    described = entry.get("response")
    if described:
        media = {"schema": copy.deepcopy(described["schema"])}
        if "example" in described:
            media["example"] = copy.deepcopy(described["example"])
        responses["200"] = {
            "description": described.get("description", "The request succeeded."),
            "content": {"application/json": media},
        }
    else:
        responses["200"] = {"description": "The request succeeded. The response body is not described yet."}
    codes = set(entry.get("errors", []))
    if op.requirement != PUBLIC:
        codes |= {401, 403}
    for code in sorted(codes):
        responses[str(code)] = {"$ref": f"#/components/responses/{_ERROR_RESPONSES[code]}"}
    return responses


def _operation(op: Operation, entry: dict) -> dict:
    over = entry.get("x-bize", {})
    result: dict = {
        "operationId": op.operation_id,
        "summary": entry.get("summary") or op.summary or "",
        "tags": [over.get("domain", op.domain)],
        "parameters": _parameters(op, entry),
        "responses": _responses(op, entry),
        "security": _security(op, bool(over.get("mcp", False))),
    }
    description = entry.get("description") or op.description
    if description:
        result["description"] = description.strip()
    if "request_body" in entry:
        body = entry["request_body"]
        media = {"schema": copy.deepcopy(body["schema"])}
        if "example" in body:
            media["example"] = copy.deepcopy(body["example"])
        request_body = {"required": bool(body.get("required", True)), "content": {"application/json": media}}
        if "description" in body:
            request_body["description"] = body["description"]
        result["requestBody"] = request_body
    bize: dict = {
        "permission": _permission(op.requirement),
        "domain": over.get("domain", op.domain),
        "mcp": bool(over.get("mcp", False)),
        "schema_status": "documented" if entry.get("response") else "skeleton",
    }
    if op.feature:
        bize["feature"] = op.feature
    for key in ("kind", "concepts", "related_operations"):
        if key in over:
            bize[key] = copy.deepcopy(over[key])
    result["x-bize"] = bize
    return result


def _refs(node, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.add(ref)
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)


def prune(document: dict) -> dict:
    """Drop the tags, components and responses no remaining operation reaches. Mutates and returns it."""
    used_tags = {tag for item in document["paths"].values() for op in item.values() for tag in op.get("tags", [])}
    document["tags"] = [tag for tag in document["tags"] if tag["name"] in used_tags]
    components = document["components"]
    reached: set[str] = set()
    pending: set[str] = set()
    _refs(document["paths"], pending)
    while pending:
        ref = pending.pop()
        if ref in reached:
            continue
        reached.add(ref)
        parts = ref.split("/")  # "#/components/<kind>/<name>"
        if len(parts) == 4 and parts[:2] == ["#", "components"]:
            target = components.get(parts[2], {}).get(parts[3])
            if target is not None:
                _refs(target, pending)
    for kind in ("schemas", "responses"):
        components[kind] = {
            name: value for name, value in components.get(kind, {}).items() if f"#/components/{kind}/{name}" in reached
        }
    return document


def build(app, overlay: Overlay | None = None) -> BuiltDocument:
    """The whole document for ``app``: every ``/api/`` operation, in every caller's terms."""
    overlay = overlay or get_overlay()
    operations = collect_operations(app)
    paths: dict[str, dict] = {}
    endpoints: dict[str, tuple[str, str]] = {}
    for op in operations:
        item = paths.setdefault(op.path, {})
        if op.method.lower() in item:
            raise ValueError(
                f"{op.method} {op.path} is served by two rules (second: {op.endpoint}); the document needs one operation"
            )
        item[op.method.lower()] = _operation(op, overlay.operations.get(op.operation_id, {}))
        endpoints[op.operation_id] = (op.endpoint, op.method)
    document = {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "Biz-E API",
            "version": DOCUMENT_VERSION,
            "summary": "Production, stock, traceability, compliance, sales and cost for a small producer.",
            "description": INFO_DESCRIPTION,
        },
        "servers": [{"url": "/", "description": "The Biz-E host this document was fetched from."}],
        "tags": [{"name": name, "description": text} for name, text in sorted(DOMAINS.items())],
        "paths": paths,
        "components": {
            "securitySchemes": copy.deepcopy(_SECURITY_SCHEMES),
            "responses": copy.deepcopy(_RESPONSES),
            "schemas": {"Error": copy.deepcopy(_ERROR_SCHEMA), **copy.deepcopy(overlay.schemas)},
        },
    }
    return BuiltDocument(document=prune(document), endpoints=endpoints)


def build_document(app, overlay: Overlay | None = None) -> dict:
    return build(app, overlay).document


def mcp_operations(app, overlay: Overlay | None = None) -> frozenset[tuple[str, str, str]]:
    """(endpoint, Flask rule, method) of every operation the overlay marks ``x-bize.mcp: true``.

    The app's token rule reads this (``access_policy.in_mcp_catalogue``), so the allowlist the MCP
    server plans from and the one the app enforces are the same overlay flags. Operations are
    resolved exactly as ``build`` resolves them, from ``collect_operations``. The rule is part of
    the key because an operation is one method on one URL rule: a second rule added to a catalogue
    endpoint is not in the catalogue until the overlay says so.
    """
    overlay = overlay or get_overlay()
    return frozenset(
        (op.endpoint, op.rule, op.method)
        for op in collect_operations(app)
        if overlay.operations.get(op.operation_id, {}).get("x-bize", {}).get("mcp") is True
    )


def narrow(built: BuiltDocument, user, *, via_token: bool = False, audience: str | None = None) -> dict:
    """The document as ``user`` may see it.

    A session sees what its role may call. A token (``via_token``), or anyone asking for
    ``audience="mcp"``, sees what an assistant token of that person could call: the GET operations
    marked ``x-bize.mcp`` whose view permission they hold, plus (without ``audience="mcp"``) the
    token's own identity and this document.
    """
    document = copy.deepcopy(built.document)
    as_token = via_token or audience == "mcp"
    kept: set[str] = set()
    for path in list(document["paths"]):
        item = document["paths"][path]
        for method in list(item):
            op = item[method]
            endpoint, http_method = built.endpoints[op["operationId"]]
            if as_token:
                reachable = token_access(user, endpoint, http_method, mcp=op["x-bize"]["mcp"] is True) == "ok"
            else:
                reachable = allows(user, endpoint, http_method)
            if audience == "mcp":
                reachable = reachable and op["x-bize"]["mcp"] is True
            if reachable:
                kept.add(op["operationId"])
            else:
                del item[method]
        if not item:
            del document["paths"][path]
    for item in document["paths"].values():
        for op in item.values():
            related = op["x-bize"].get("related_operations")
            if related is not None:
                op["x-bize"]["related_operations"] = [oid for oid in related if oid in kept]
    return prune(document)


def canonical_json(document: dict) -> str:
    """The one serialisation ``docs/openapi.json`` is written in: sorted keys, two-space indent, UTF-8, a final newline."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
