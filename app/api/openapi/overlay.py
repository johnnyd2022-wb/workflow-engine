"""The hand-written half of the OpenAPI document: ``overlay/<domain>.yaml``.

The generator (``generator.py``) knows a route's path, method, permission and docstring. It cannot know
what the query string accepts or what the body looks like, so those live here, keyed by ``operationId``:

.. code-block:: yaml

    operations:
      core_list_inventory:
        summary: ...            # replaces the docstring's first line
        description: ...        # replaces the docstring's body
        parameters:             # OpenAPI parameter objects; a path parameter merges onto the derived one
          - {name: item_type, in: query, description: ..., schema: {type: string}}
        response:               # the 200 body
          description: ...
          schema: {...}         # inline, or {$ref: '#/components/schemas/Name'}
          example: {...}
        errors: [400, 404]      # extra documented failures (the 401 and 403 are added to every route)
        request_body: {...}     # {description, required, schema, example}
        x-bize:
          kind: list            # record | list | calculation
          mcp: true             # an assistant may call it
          concepts: [inventory.availability]
          related_operations: [core_get_process]
          domain: inventory     # only to override what the generator derives
    schemas:                    # shared by every file; component names are global
      InventoryLot: {...}

A key the loader does not know, a repeated key, or a name defined twice is an error at load time, so a
typo cannot quietly leave a route undocumented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

OVERLAY_DIR = Path(__file__).parent / "overlay"

OPERATION_KEYS = frozenset({"summary", "description", "parameters", "response", "errors", "request_body", "x-bize"})
XBIZE_KEYS = frozenset({"kind", "mcp", "concepts", "related_operations", "domain", "complete", "app_page"})
KINDS = frozenset({"record", "list", "calculation"})
FILE_KEYS = frozenset({"operations", "schemas"})


class OverlayError(ValueError):
    """The overlay files are malformed. The message names the file and the key."""


class _Loader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """``safe_load`` that also refuses a repeated mapping key (PyYAML silently keeps the last one)."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _parse(text: str):
    loader = _Loader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


@dataclass(frozen=True)
class Overlay:
    operations: dict[str, dict]
    schemas: dict[str, dict]


# Keys whose value may genuinely be null inside a schema or a parameter.
_NULLABLE_KEYS = frozenset({"example", "default", "const", "x-example"})


def _stray_flow_keys(node, where: str) -> None:
    """A comma in an unquoted flow-mapping value (``{type: string, description: a, b}``) splits it, and
    PyYAML keeps the tail as a key with no value. Refuse that instead of publishing a broken schema."""
    if isinstance(node, dict):
        for key in node:
            if not isinstance(key, str):  # YAML 1.1 reads a bare on/off/yes/no as a boolean: quote it
                raise OverlayError(
                    f"{where}: key {key!r} is not text; quote it (on, off, yes, no and numbers need quotes)"
                )
        if isinstance(node.get("description"), str) or isinstance(node.get("type"), (str, list)):
            for key, value in node.items():
                if value is None and isinstance(key, str) and key not in _NULLABLE_KEYS:
                    raise OverlayError(f"{where}: {key!r} looks like part of a description cut at a comma; quote it")
        for key, value in node.items():
            if key not in ("example", "examples", "default", "const", "enum"):  # data, not schema
                _stray_flow_keys(value, where)
    elif isinstance(node, list):
        for value in node:
            _stray_flow_keys(value, where)


def _check_operation(name: str, where: str, entry) -> None:
    if not isinstance(entry, dict):
        raise OverlayError(f"{where}: {name} must be a mapping")
    unknown = sorted(set(entry) - OPERATION_KEYS)
    if unknown:
        raise OverlayError(f"{where}: {name} has unknown keys {unknown}; allowed: {sorted(OPERATION_KEYS)}")
    xbize = entry.get("x-bize") or {}
    if not isinstance(xbize, dict):
        raise OverlayError(f"{where}: {name} x-bize must be a mapping")
    unknown = sorted(set(xbize) - XBIZE_KEYS)
    if unknown:
        raise OverlayError(f"{where}: {name} x-bize has unknown keys {unknown}; allowed: {sorted(XBIZE_KEYS)}")
    if "kind" in xbize and xbize["kind"] not in KINDS:
        raise OverlayError(f"{where}: {name} x-bize.kind must be one of {sorted(KINDS)}")
    if "mcp" in xbize and not isinstance(xbize["mcp"], bool):
        raise OverlayError(f"{where}: {name} x-bize.mcp must be true or false")
    response = entry.get("response")
    if response is not None and not (isinstance(response, dict) and "schema" in response):
        raise OverlayError(f"{where}: {name} response needs a schema")
    for parameter in entry.get("parameters", []):
        if not isinstance(parameter, dict) or not {"name", "in"} <= set(parameter):
            raise OverlayError(f"{where}: {name} has a parameter with no name or no 'in'")


def load_overlay(directory: Path = OVERLAY_DIR) -> Overlay:
    operations: dict[str, dict] = {}
    schemas: dict[str, dict] = {}
    for path in sorted(directory.glob("*.yaml")):
        where = path.name
        try:
            data = _parse(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise OverlayError(f"{where}: {exc}") from exc
        try:
            json.dumps(data)
        except TypeError as exc:  # an unquoted date or timestamp in an example, say
            raise OverlayError(f"{where}: a value is not plain JSON ({exc}); quote dates and timestamps") from exc
        _stray_flow_keys(data, where)
        unknown = sorted(set(data) - FILE_KEYS)
        if unknown:
            raise OverlayError(f"{where}: unknown top-level keys {unknown}; allowed: {sorted(FILE_KEYS)}")
        for name, entry in (data.get("operations") or {}).items():
            _check_operation(name, where, entry)
            if name in operations:
                raise OverlayError(f"{where}: {name} is also described in another overlay file")
            operations[name] = entry
        for name, schema in (data.get("schemas") or {}).items():
            if name in schemas:
                raise OverlayError(f"{where}: schema {name} is also defined in another overlay file")
            schemas[name] = schema
    return Overlay(operations=operations, schemas=schemas)


@lru_cache(maxsize=1)
def get_overlay() -> Overlay:
    """The checked-in overlay, parsed once per process. Treat it as read-only: copy before embedding."""
    return load_overlay()
