"""OpenAPI 3.1 for the whole API (public MCP 8.2f; spec .agents/specs/public-mcp.md).

``generator`` walks the Flask URL map, ``overlay`` holds what the code cannot say, ``document`` puts them
together and narrows the result per caller, ``routes`` serves it at ``GET /api/openapi.json``, and
``coverage`` is what the ratchet test measures. ``docs/openapi.json`` is the committed copy; CI fails
when it is stale (``scripts/check_openapi.py``).
"""

from app.api.openapi.document import COMMITTED_PATH, build, build_document, canonical_json, narrow

__all__ = ["COMMITTED_PATH", "build", "build_document", "canonical_json", "narrow"]
