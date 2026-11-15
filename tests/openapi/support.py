"""Helpers shared by the OpenAPI tests: walking the document, resolving schemas, validating a response."""

from __future__ import annotations

import copy
from collections.abc import Iterator

from jsonschema import Draft202012Validator, FormatChecker

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

# Keywords whose value is data, not a sub-schema.
_DATA_KEYWORDS = frozenset({"example", "examples", "enum", "const", "default", "required", "type"})
# Keywords whose value maps a name to a sub-schema (the names are not keywords).
_NAMED_SCHEMAS = frozenset({"properties", "patternProperties", "$defs", "definitions", "schemas"})


def operations(doc: dict) -> Iterator[tuple[str, str, dict]]:
    """``(path, METHOD, operation)`` for every operation in the document."""
    for path, item in doc["paths"].items():
        for method in HTTP_METHODS:
            if method in item:
                yield path, method.upper(), item[method]


def by_id(doc: dict) -> dict[str, tuple[str, str, dict]]:
    return {op["operationId"]: (path, method, op) for path, method, op in operations(doc)}


def mcp_operations(doc: dict) -> dict[str, tuple[str, str, dict]]:
    return {oid: row for oid, row in by_id(doc).items() if row[2].get("x-bize", {}).get("mcp") is True}


def response_schema(op: dict, status: str = "200") -> dict | None:
    content = op.get("responses", {}).get(status, {}).get("content", {})
    return content.get("application/json", {}).get("schema")


def response_example(op: dict, status: str = "200"):
    content = op.get("responses", {}).get(status, {}).get("content", {})
    return content.get("application/json", {}).get("example")


def _strict(node):
    """Close every object schema that did not say what extra properties mean.

    The document stays permissive for people integrating (a new field is not a breaking change). The
    test is strict, so a field the route returns that the schema does not describe is a failure: the
    docs cannot fall behind the code without a test saying so.
    """
    if isinstance(node, list):
        return [_strict(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key in _DATA_KEYWORDS:
            out[key] = value
        elif key in _NAMED_SCHEMAS and isinstance(value, dict):
            out[key] = {name: _strict(sub) for name, sub in value.items()}
        else:
            out[key] = _strict(value)
    kind = out.get("type")
    is_object = kind == "object" or (isinstance(kind, list) and "object" in kind)
    if (is_object or "properties" in out) and "additionalProperties" not in out and "unevaluatedProperties" not in out:
        out["additionalProperties"] = False
    return out


def schema_errors(doc: dict, schema: dict, instance, *, strict: bool = True) -> list[str]:
    """Why ``instance`` does not satisfy ``schema`` (which may ``$ref`` the document's components)."""
    body = copy.deepcopy(schema)
    components = copy.deepcopy(doc.get("components", {}))
    if strict:
        body, components = _strict(body), _strict(components)
    wrapper = {**body, "components": components}
    validator = Draft202012Validator(wrapper, format_checker=FormatChecker())
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in validator.iter_errors(instance)]
