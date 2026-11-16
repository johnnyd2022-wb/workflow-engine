"""``discover``: search business knowledge and the operations this caller may run."""

from __future__ import annotations

from typing import Any

from bize_mcp.knowledge import query_tokens, score_text
from bize_mcp.tools.base import Tool, ToolContext
from bize_mcp.validation import schema

DEFAULT_LIMIT = 10
MAX_LIMIT = 20

DESCRIPTION = (
    "Start here. Search Biz-E's business knowledge (what lots, batches, ready dates, holds, costs and "
    "excise mean and how they relate) and the read-only operations you can run for this person. "
    "Returns ranked concept topics and operations. With an empty query it returns a short overview of "
    "how Biz-E models a producer's work and the list of topics. Then call docs for a topic or an "
    "operation, then execute. Prefer an operation marked kind=calculation over doing arithmetic "
    "yourself: Biz-E's own figures are the authoritative ones."
)

INPUT = schema(
    {
        "query": {"type": "string", "maxLength": 300, "description": "What you want to know or find."},
        "kind": {"type": "string", "enum": ["concepts", "operations", "all"], "default": "all"},
        "domain": {"type": "string", "maxLength": 60, "description": "Limit to one domain, e.g. inventory."},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": DEFAULT_LIMIT},
    }
)


def _operation_row(op) -> dict[str, Any]:
    return {
        "operation_id": op.operation_id,
        "summary": op.summary,
        "domain": op.domain,
        "kind": op.kind,
        "permission": op.permissions[0] if len(op.permissions) == 1 else list(op.permissions),
        "required_params": op.required_params,
    }


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    features = ctx.identity.features
    operations = await ctx.operations()
    query_text = (args.get("query") or "").strip()
    kind = args.get("kind", "all")
    domain = args.get("domain")
    limit = args.get("limit", DEFAULT_LIMIT)

    if not query_text:
        topics = ctx.knowledge.visible(features)
        domains: dict[str, int] = {}
        for op in operations.values():
            domains[op.domain or "other"] = domains.get(op.domain or "other", 0) + 1
        return {
            "overview": ctx.knowledge.overview,
            "topics": [{"topic": t.topic, "title": t.title, "domain": t.domain, "summary": t.summary} for t in topics],
            "operation_domains": dict(sorted(domains.items())),
            "message": "Call discover with a question to find topics and operations, docs to read one, then execute.",
        }

    query = query_tokens(query_text)
    concepts: list[dict[str, Any]] = []
    related_ids: set[str] = set()
    if kind in {"concepts", "all"}:
        for _, topic in ctx.knowledge.search(query, features, domain)[:limit]:
            related_ids.update(topic.related_operations)
            concepts.append(
                {
                    "topic": topic.topic,
                    "title": topic.title,
                    "summary": topic.summary,
                    "related": list(topic.related_topics),
                }
            )
    found: list[dict[str, Any]] = []
    if kind in {"operations", "all"}:
        scored = []
        for op in operations.values():
            if domain and op.domain != domain:
                continue
            total = (
                score_text(query, op.operation_id.replace("_", " "), 4)
                + score_text(query, op.summary, 3)
                + score_text(query, " ".join(op.concepts).replace(".", " ").replace("_", " "), 2)
                + score_text(query, op.domain or "", 2)
                + score_text(query, op.description, 1)
                + (2 if op.operation_id in related_ids else 0)
            )
            if total > 0:
                scored.append((total, op))
        scored.sort(key=lambda pair: (-pair[0], pair[1].operation_id))
        found = [_operation_row(op) for _, op in scored[:limit]]
    return {
        "query": query_text,
        "concepts": concepts,
        "operations": found,
        "message": (
            "Read a topic or an operation with docs, then run operations with execute."
            if concepts or found
            else "Nothing matched. Try other words, or discover with an empty query for the overview."
        ),
    }


DISCOVER = Tool("discover", DESCRIPTION, INPUT, run)
