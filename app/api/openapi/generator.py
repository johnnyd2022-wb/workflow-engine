"""Describe every ``/api/`` operation the app serves, from the Flask URL map and the policy table.

What comes from the code, never written twice:

- the path and its path parameters (from the rule),
- the ``operationId`` (the endpoint name, dots to underscores),
- ``summary`` and ``description`` (from the view function's docstring),
- ``x-bize.permission`` (from ``access_policy.requirement_for``, the table the app enforces),
- ``x-bize.domain`` and ``x-bize.feature`` (from the blueprint and the URL).

What cannot be derived (query parameters, response bodies, concepts, an example) comes from the overlay
(``overlay.py``). The output is deterministic: it depends on the code and the overlay only, never on the
time, the environment or the iteration order of a set.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass

from app.core.security.access_policy import requirement_for

API_PREFIX = "/api/"

# A Flask rule argument: <name>, <converter:name>, <converter(arg=1):name>.
_RULE_ARGUMENT = re.compile(r"<(?:(?P<converter>[a-zA-Z_]\w*)(?:\([^)]*\))?:)?(?P<name>[a-zA-Z_]\w*)>")

_CONVERTER_SCHEMA: dict[str, dict] = {
    "string": {"type": "string"},
    "uuid": {"type": "string", "format": "uuid"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "path": {"type": "string"},
}

# URL prefix -> domain, most specific first. A route whose prefix is not here falls back to its
# blueprint's domain, then to "platform". The overlay may set ``x-bize.domain`` to override either.
_PREFIX_DOMAIN: tuple[tuple[str, str], ...] = (
    ("/api/core/inventory/trace", "traceability"),
    ("/api/core/sourcemap", "traceability"),
    ("/api/core/inventory", "inventory"),
    ("/api/core/stock", "inventory"),
    ("/api/core/holds", "inventory"),
    ("/api/core/suppliers", "inventory"),
    ("/api/core/config/units", "inventory"),
    ("/api/core/processes", "production"),
    ("/api/core/executions", "production"),
    ("/api/core/execution-metadata", "production"),
    ("/api/core/process-docs", "production"),
    ("/api/core/process-templates", "production"),
    ("/api/core/evidence", "production"),
    ("/api/core/record-options", "production"),
    ("/api/core/tasks", "production"),
    ("/api/core/flows", "production"),
    ("/api/core/cases", "production"),
    ("/api/core/recalls", "traceability"),
    ("/api/core/contract-", "contracts"),
    ("/api/core/export", "account"),
    ("/api/core/mcp", "account"),
    ("/api/openapi", "account"),
)
_BLUEPRINT_DOMAIN: dict[str, str] = {
    "compliant": "compliance",
    "crm": "sales",
    "tastings": "sales",
    "costing": "costing",
    "planning": "planning",
    "stocktake": "inventory",
    "stock_locations": "inventory",
    "lot_holds": "inventory",
    "go_live": "inventory",
    "sites": "inventory",
    "site_transfers": "inventory",
    "contracts": "contracts",
    "recalls": "traceability",
    "operational_cases": "production",
    "process_templates": "production",
    "record_step": "production",
    "data_export": "account",
    "mcp": "account",
    "org": "account",
    "openapi": "account",
}
# Product areas an organisation may not have. The blueprint's first segment names the product.
_BLUEPRINT_FEATURE: dict[str, str] = {"crm": "crm", "tastings": "crm", "compliant": "compliant", "costing": "costing"}

DOMAINS: dict[str, str] = {
    "inventory": "Stock on hand, lots, holds, sites, locations and stocktakes.",
    "production": "Workflows, steps, batches (executions), evidence and production tasks.",
    "traceability": "Tracing a lot back to its sources and forward to the customers it reached.",
    "compliance": "Compliance records, checks, excise and the regulatory registers.",
    "sales": "Customers, Xero invoices, sales analytics and returns.",
    "costing": "Cost per lot and batch, readiness, margins, stock value and the cost settings.",
    "planning": "Stock cover, the planner's batches, capacity and demand.",
    "contracts": "Contract manufacturing: customers, orders, materials and dispatches.",
    "account": "The organisation, people, exports and assistant access.",
    "platform": "The dashboard, the change feed and the cross-cutting findings.",
}


@dataclass(frozen=True)
class Operation:
    """One method on one path, as the code and the policy table describe it."""

    operation_id: str
    endpoint: str
    method: str  # upper case
    rule: str  # the Flask rule
    path: str  # the OpenAPI path
    path_parameters: tuple[dict, ...]
    requirement: object  # PUBLIC, SIGNED_IN, a permission, a tuple of permissions (any of) or DENY
    domain: str
    feature: str | None
    summary: str | None  # from the docstring; the overlay may replace it
    description: str | None


def openapi_path(rule: str) -> tuple[str, tuple[dict, ...]]:
    """``/api/x/<uuid:item_id>/<path:key>`` -> (``/api/x/{item_id}/{key}``, its path parameters)."""
    parameters = []
    for match in _RULE_ARGUMENT.finditer(rule):
        converter = match.group("converter") or "string"
        parameters.append(
            {
                "name": match.group("name"),
                "in": "path",
                "required": True,
                "schema": dict(_CONVERTER_SCHEMA.get(converter, _CONVERTER_SCHEMA["string"])),
            }
        )
    return _RULE_ARGUMENT.sub(lambda m: "{" + m.group("name") + "}", rule), tuple(parameters)


# Internal tracking ids developers put in docstrings ("GL-P01b: ...", "8.1f-2: ...", "(GL-P07 B5)"): not for callers.
_LEADING_ID = re.compile(r"^(?:GL-[A-Z]+\d+[a-z]?|\d+\.\d+[a-z]?(?:-\d+)?|AC\d+)\s*:\s*")
_PAREN_ID = re.compile(r"\s*\((?:GL-[A-Z]+\d+[a-z]?|AC\d+)[^)]*\)")


def _clean(text: str | None) -> str | None:
    if not text:
        return text
    return _PAREN_ID.sub("", _LEADING_ID.sub("", text.strip())).strip() or None


def docstring_parts(function) -> tuple[str | None, str | None]:
    """(summary, description) from a docstring.

    The summary is the first line. When that line stops mid-sentence (a wrapped first sentence), the
    summary is the whole first paragraph on one line, so it is never a fragment. The description is
    whatever follows.
    """
    text = inspect.cleandoc(getattr(function, "__doc__", None) or "")
    if not text:
        return None, None
    paragraphs = re.split(r"\n\s*\n", text, maxsplit=1)
    first = paragraphs[0].strip()
    rest = paragraphs[1].strip() if len(paragraphs) > 1 else ""
    lines = first.splitlines()
    if len(lines) > 1 and not lines[0].rstrip().endswith((".", "?", "!", ":", ")")):
        return _clean(" ".join(part.strip() for part in lines)), rest or None
    tail = "\n".join(lines[1:]).strip()
    description = "\n\n".join(part for part in (tail, rest) if part)
    return _clean(lines[0]), description or None


def domain_for(endpoint: str, rule: str) -> str:
    for prefix, domain in _PREFIX_DOMAIN:
        if rule.startswith(prefix):
            return domain
    return _BLUEPRINT_DOMAIN.get(endpoint.split(".", 1)[0], "platform")


def feature_for(endpoint: str) -> str | None:
    return _BLUEPRINT_FEATURE.get(endpoint.split(".", 1)[0])


def _unique_ids(rows: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], str]:
    """operationId per (endpoint, method, rule): the endpoint name, with ``_<method>`` only where a
    plain name would repeat (an endpoint serving several methods or several rules)."""
    base = {row: row[0].replace(".", "_") for row in rows}
    counts: dict[str, int] = {}
    for oid in base.values():
        counts[oid] = counts.get(oid, 0) + 1
    ids: dict[tuple[str, str, str], str] = {}
    taken: set[str] = set()
    for row in sorted(rows, key=lambda r: (r[2], r[1], r[0])):
        oid = base[row]
        if counts[oid] > 1:
            oid = f"{oid}_{row[1].lower()}"
        candidate, n = oid, 1
        while candidate in taken:
            n += 1
            candidate = f"{oid}_{n}"
        taken.add(candidate)
        ids[row] = candidate
    return ids


def collect_operations(app) -> list[Operation]:
    """Every ``/api/`` rule and method on ``app``, sorted by path then method."""
    rows = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith(API_PREFIX):
            continue
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            rows.append((rule.endpoint, method, rule.rule))
    ids = _unique_ids(rows)

    operations = []
    for endpoint, method, rule in sorted(rows, key=lambda r: (r[2], r[1], r[0])):
        path, path_parameters = openapi_path(rule)
        summary, description = docstring_parts(app.view_functions[endpoint])
        operations.append(
            Operation(
                operation_id=ids[(endpoint, method, rule)],
                endpoint=endpoint,
                method=method,
                rule=rule,
                path=path,
                path_parameters=path_parameters,
                requirement=requirement_for(endpoint, method),
                domain=domain_for(endpoint, rule),
                feature=feature_for(endpoint),
                summary=summary,
                description=description,
            )
        )
    return operations
