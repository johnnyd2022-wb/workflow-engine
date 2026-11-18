"""What the coverage ratchet measures (tests/openapi/test_coverage.py reads these).

Kept next to the generator so the rule for "complete enough for an assistant to call" is written once,
in code, and the tests and the docs say the same thing.
"""

from __future__ import annotations

import re

from app.core.security.access_policy import READ_PERMISSIONS

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
CONCEPT_ID = re.compile(r"^[a-z][a-z_]*\.[a-z][a-z_]*$")
KINDS = ("record", "list", "calculation")
MIN_DESCRIPTION = 60  # characters: a real "when to use this", not a restated title


def _operations(document: dict):
    for path, item in document["paths"].items():
        for method in HTTP_METHODS:
            if method in item:
                yield path, method, item[method]


def operations_missing_summary(document: dict) -> list[str]:
    """Operation ids with no summary: a route with no docstring and no overlay entry."""
    return sorted(op["operationId"] for _p, _m, op in _operations(document) if not (op.get("summary") or "").strip())


def operations_without_schemas(document: dict) -> list[str]:
    """Operation ids whose success response is not described yet (the skeletons the ratchet counts)."""
    return sorted(
        op["operationId"] for _p, _m, op in _operations(document) if op["x-bize"]["schema_status"] != "documented"
    )


def mcp_problems(document: dict) -> dict[str, list[str]]:
    """For each ``x-bize.mcp`` operation, what is missing before an assistant can use it. Empty when complete."""
    ids = {op["operationId"] for _p, _m, op in _operations(document)}
    found: dict[str, list[str]] = {}
    for _path, method, op in _operations(document):
        bize = op["x-bize"]
        if bize.get("mcp") is not True:
            continue
        problems: list[str] = []
        if method != "get":
            problems.append(f"is a {method.upper()}, and only GET operations may be marked for assistants")
        permission = bize["permission"]
        if not READ_PERMISSIONS.intersection(permission if isinstance(permission, list) else [permission]):
            problems.append(f"requires {permission!r}, which names no read permission")
        if bize.get("kind") not in KINDS:
            problems.append(f"x-bize.kind must be one of {KINDS}")
        if len((op.get("description") or "").strip()) < MIN_DESCRIPTION:
            problems.append(f"needs a description of at least {MIN_DESCRIPTION} characters saying when to use it")
        if bize["schema_status"] != "documented":
            problems.append("has no response schema")
        else:
            media = op["responses"]["200"]["content"]["application/json"]
            if "example" not in media:
                problems.append("has no response example")
            if bize.get("kind") == "list":
                if "total_count" not in media["schema"].get("properties", {}):
                    problems.append("list response has no total_count")
                if "total_count" not in media.get("example", {}):
                    problems.append("list example has no total_count")
        if "complete" in bize and not isinstance(bize["complete"], bool):
            problems.append("x-bize.complete must be true or false")
        if bize.get("complete") is True:
            page = bize.get("app_page")
            if (
                not isinstance(page, str)
                or not re.fullmatch(r"/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*", page)
                or page.startswith("/api/")
            ):
                problems.append("a complete response requires x-bize.app_page with an app path")
        for parameter in op.get("parameters", []):
            if not (parameter.get("description") or "").strip():
                problems.append(f"parameter {parameter['name']} has no description")
            if "type" not in parameter.get("schema", {}) and "$ref" not in parameter.get("schema", {}):
                problems.append(f"parameter {parameter['name']} has no schema type")
        concepts = bize.get("concepts") or []
        if not concepts:
            problems.append("names no concepts (x-bize.concepts)")
        problems += [f"concept {c!r} is not a <domain>.<topic> id" for c in concepts if not CONCEPT_ID.match(c)]
        related = bize.get("related_operations") or []
        if not related:
            problems.append("names no related operations")
        problems += [f"related operation {r!r} does not exist" for r in related if r not in ids]
        if {"bearerToken": []} not in op.get("security", []):
            problems.append("is not reachable by an assistant token under the access policy")
        if problems:
            found[op["operationId"]] = problems
    return found
