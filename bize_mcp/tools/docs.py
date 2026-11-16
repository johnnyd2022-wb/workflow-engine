"""``docs``: one concept's full document, or one operation's full contract."""

from __future__ import annotations

from typing import Any

from bize_mcp.catalogue import Operation
from bize_mcp.errors import ToolFailureError
from bize_mcp.shaping import clip
from bize_mcp.tools.base import Tool, ToolContext
from bize_mcp.validation import schema

MAX_DOC_TEXT = 20_000

DESCRIPTION = (
    "Read the full document for one business concept (topic, e.g. inventory.availability) or the full "
    "contract of one operation (operation_id: its parameters, response schema, related operations and a "
    "worked example). Give exactly one of topic or operation_id, both taken from discover. Read the "
    "concept before answering questions about stock, batches, costs or compliance: it says what to "
    "assume and what not to."
)

INPUT = schema(
    {
        "topic": {
            "type": "string",
            "maxLength": 120,
            "description": "A topic from discover, e.g. inventory.availability.",
        },
        "operation_id": {"type": "string", "maxLength": 120, "description": "An operation_id from discover."},
    }
)


def _operation_doc(op: Operation, allowed: dict[str, Operation], topics: set[str]) -> dict[str, Any]:
    return {
        "operation_id": op.operation_id,
        "summary": op.summary,
        "description": op.description,
        "method": op.method,
        "domain": op.domain,
        "kind": op.kind,
        "permission": op.permissions[0] if len(op.permissions) == 1 else list(op.permissions),
        "parameters": [
            {"name": p.name, "in": p.where, "required": p.required, "schema": p.schema, "description": p.description}
            for p in op.params
        ],
        "response_schema": op.response_schema,
        "concepts": list(op.concepts),
        "concept_topics": [c for c in op.concepts if c in topics],
        "related_operations": [r for r in op.related_operations if r in allowed],
        "example": op.example,
    }


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    topic_name, operation_id = args.get("topic"), args.get("operation_id")
    if bool(topic_name) == bool(operation_id):
        raise ToolFailureError("Give exactly one of topic or operation_id.", kind="invalid_input")
    allowed = await ctx.operations()
    features = ctx.identity.features
    if topic_name:
        topic = ctx.knowledge.get(topic_name, features)
        if topic is None:
            raise ToolFailureError("Not found", kind="not_found")
        return clip(
            {
                "topic": topic.topic,
                "title": topic.title,
                "domain": topic.domain,
                "summary": topic.summary,
                "related_topics": [t for t in topic.related_topics if ctx.knowledge.get(t, features)],
                "related_operations": [o for o in topic.related_operations if o in allowed],
                "features": list(topic.features),
                "markdown": topic.markdown,
            },
            MAX_DOC_TEXT,
        )
    op = allowed.get(operation_id)
    if op is None:
        raise ToolFailureError("Not found", kind="not_found")
    return clip(_operation_doc(op, allowed, set(ctx.knowledge.topics)), MAX_DOC_TEXT)


DOCS = Tool("docs", DESCRIPTION, INPUT, run)
