"""Layer 2: the API catalogue, read from the app's OpenAPI 3.1 document (``GET /api/openapi.json``).

The app is the single source of truth. This module fetches ``?audience=mcp`` with the caller's own
token (the app already returns only the operations that token may call), then applies the
allowlist again here, so a catalogue that ever listed too much still could not widen what runs:

* the operation is a ``GET``;
* its ``x-bize.mcp`` is ``true``;
* its ``x-bize.permission`` is a read permission (see ``READ_PERMISSIONS``) the caller holds;
* its ``x-bize.feature`` (if any) is enabled for the caller's organisation.

The answer is cached for 5 minutes per (organisation, permission set, features).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from bize_mcp import auth
from bize_mcp.auth import Identity
from bize_mcp.client import AppClient

CATALOGUE_PATH = "/api/openapi.json"
CATALOGUE_TTL = 300.0
MAX_CACHED = 256

# Mirrors ``READ_PERMISSIONS`` in the app's access policy. The app is still the authority and
# checks again on every request; this copy only decides what is listed and what may be attempted.
READ_PERMISSIONS = frozenset({"production.view", "inventory.view", "sales.view", "compliance.view", "costs.view"})


@dataclass(frozen=True)
class Param:
    name: str
    where: str  # "path" | "query" (header and cookie parameters are not supported, so such operations are dropped)
    required: bool
    schema: dict[str, Any]
    description: str = ""


@dataclass(frozen=True)
class Operation:
    operation_id: str
    method: str
    path: str
    summary: str
    description: str
    domain: str | None
    kind: str | None
    permissions: tuple[str, ...]
    feature: str | None
    concepts: tuple[str, ...]
    related_operations: tuple[str, ...]
    example: Any
    params: tuple[Param, ...]
    response_schema: dict[str, Any] | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    complete: bool = False
    app_page: str | None = None

    @property
    def required_params(self) -> list[str]:
        return [p.name for p in self.params if p.required]

    def param_schema(self) -> dict[str, Any]:
        """A JSON Schema for the ``params`` object: declared names only, nothing else is accepted."""
        body: dict[str, Any] = {
            "type": "object",
            "properties": {p.name: p.schema or {} for p in self.params},
            "additionalProperties": False,
        }
        if self.required_params:
            body["required"] = self.required_params
        return body

    def allowed_for(self, identity: Identity) -> bool:
        if self.method != "GET" or not self.permissions:
            return False
        if not all(p in READ_PERMISSIONS for p in self.permissions):
            return False
        if not any(p in identity.permissions for p in self.permissions):
            return False
        return identity.has_feature(self.feature)


def _resolve(document: dict, node: Any, depth: int = 0) -> Any:
    """Follow a local ``$ref`` (``#/components/...``) one level at a time; anything else is left as is."""
    while isinstance(node, dict) and isinstance(node.get("$ref"), str) and depth < 8:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return {}
        target: Any = document
        for part in ref[2:].split("/"):
            target = target.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(target, dict) else None
        node, depth = target, depth + 1
    return node if node is not None else {}


def deref(document: dict, node: Any, depth: int = 0, seen: tuple[str, ...] = ()) -> Any:
    """``node`` with every local ``$ref`` replaced by what it points at, so a model reads one schema.

    Bounded: a reference already being expanded (a cycle) or one nested more than 6 deep is left as
    ``{"$ref": ...}``.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref in seen or depth > 6 or not ref.startswith("#/"):
                return {"$ref": ref}
            return deref(document, _resolve(document, node), depth + 1, (*seen, ref))
        return {key: deref(document, value, depth, seen) for key, value in node.items()}
    if isinstance(node, list):
        return [deref(document, item, depth, seen) for item in node]
    return node


def _permissions(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(v for v in value if isinstance(v, str))
    return ()


def _response_schema(document: dict, operation: dict) -> dict | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    ok = _resolve(document, responses.get("200") or responses.get("default") or {})
    content = _resolve(document, ok.get("content", {}).get("application/json", {})) if isinstance(ok, dict) else {}
    schema = content.get("schema") if isinstance(content, dict) else None
    return deref(document, schema) if schema else None


def _response_example(document: dict, operation: dict) -> Any:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    ok = _resolve(document, responses.get("200") or {})
    content = _resolve(document, ok.get("content", {}).get("application/json", {})) if isinstance(ok, dict) else {}
    return content.get("example") if isinstance(content, dict) else None


def parse(document: Any) -> dict[str, Operation]:
    """Every well-formed operation in the document, by operationId. Malformed entries are skipped."""
    found: dict[str, Operation] = {}
    paths = document.get("paths") if isinstance(document, dict) else None
    if not isinstance(paths, dict):
        return found
    for path, item in paths.items():
        item = _resolve(document, item)
        if not isinstance(item, dict) or not isinstance(path, str):
            continue
        shared = item.get("parameters") if isinstance(item.get("parameters"), list) else []
        for method, entry in item.items():
            if method.lower() not in {"get", "head", "post", "put", "patch", "delete"} or not isinstance(entry, dict):
                continue
            operation_id = entry.get("operationId")
            extension = entry.get("x-bize") if isinstance(entry.get("x-bize"), dict) else {}
            if not isinstance(operation_id, str) or not operation_id or extension.get("mcp") is not True:
                continue
            params, supported = [], True
            for raw in [*shared, *(entry.get("parameters") or [])]:
                raw = _resolve(document, raw)
                if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                    continue
                if raw.get("in") not in {"path", "query"}:
                    supported = supported and not raw.get("required")
                    continue
                params.append(
                    Param(
                        name=raw["name"],
                        where=raw["in"],
                        required=bool(raw.get("required")) or raw["in"] == "path",
                        schema=deref(document, raw.get("schema") or {}),
                        description=str(raw.get("description") or ""),
                    )
                )
            if not supported:
                continue
            found[operation_id] = Operation(
                operation_id=operation_id,
                method=method.upper(),
                path=path,
                summary=str(entry.get("summary") or ""),
                description=str(entry.get("description") or ""),
                domain=extension.get("domain") if isinstance(extension.get("domain"), str) else None,
                kind=extension.get("kind") if isinstance(extension.get("kind"), str) else None,
                permissions=_permissions(extension.get("permission")),
                feature=extension.get("feature") if isinstance(extension.get("feature"), str) else None,
                concepts=tuple(c for c in extension.get("concepts", []) if isinstance(c, str)),
                related_operations=tuple(c for c in extension.get("related_operations", []) if isinstance(c, str)),
                example=extension.get("example", _response_example(document, entry)),
                params=tuple(params),
                response_schema=_response_schema(document, entry),
                raw=entry,
                complete=extension.get("complete") is True,
                app_page=extension.get("app_page"),
            )
    return found


class Catalogue:
    def __init__(self, client: AppClient):
        self._client = client
        self._entries: dict[tuple, tuple[float, dict[str, Operation]]] = {}

    async def operations_for(self, token: str, identity: Identity) -> dict[str, Operation]:
        """The operations this caller may execute, by operationId."""
        key = (
            identity.org_id,
            tuple(sorted(identity.permissions)),
            tuple(sorted(identity.features)) if identity.features is not None else None,
        )
        now = auth._now()
        hit = self._entries.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        document = await self._client.get(CATALOGUE_PATH, token, {"audience": "mcp"})
        allowed = {oid: op for oid, op in parse(document).items() if op.allowed_for(identity)}
        if len(self._entries) >= MAX_CACHED:
            self._entries.clear()
        self._entries[key] = (now + CATALOGUE_TTL, allowed)
        return allowed


def example_text(operation: Operation) -> str | None:
    return None if operation.example is None else json.dumps(operation.example, separators=(",", ":"))
