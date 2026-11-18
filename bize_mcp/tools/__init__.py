"""The three model-facing tools: ``discover``, ``docs`` and ``execute``.

Everything the assistant can do goes through these, over the knowledge docs (layer 1) and the app's
OpenAPI catalogue (layers 2 and 3). All three are read only.
"""

from __future__ import annotations

from bize_mcp.tools.base import Tool, ToolContext
from bize_mcp.tools.discover import DISCOVER
from bize_mcp.tools.docs import DOCS
from bize_mcp.tools.execute import EXECUTE

TOOLS: dict[str, Tool] = {tool.name: tool for tool in (DISCOVER, DOCS, EXECUTE)}

__all__ = ["DISCOVER", "DOCS", "EXECUTE", "TOOLS", "Tool", "ToolContext"]
