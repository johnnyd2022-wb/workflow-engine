"""Layer 1: business knowledge, one Markdown file per topic in a directory (``docs/knowledge``).

Each file starts with frontmatter between ``---`` lines: ``topic``, ``title``, ``domain``,
``summary``, ``related_topics``, ``related_operations`` and ``features``. The values are plain
``key: value`` lines; a list is ``[a, b]`` or ``- item`` lines. ``overview.md`` is the short
domain overview returned for an empty ``discover`` query. Files are read once, at start-up.

The search is a small keyword ranker (no model, no network): good enough for a catalogue of dozens
of topics and operations, and the same answer every time.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("bize_mcp.knowledge")

_STOP = frozenset(
    "a an and are as at be by can do does for from how i in is it my of on or our so that the this to was what when "
    "where which why with you your".split()
)
_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


def token_match(a: str, b: str) -> bool:
    """Equal, or sharing a long enough stem: ``available`` matches ``availability``, ``lot`` matches ``lots``."""
    if a == b:
        return True
    shorter = min(len(a), len(b))
    if shorter < 4:
        return False
    common = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        common += 1
    return common >= max(4, shorter - 3)


def score_text(query: list[str], text: str, weight: float) -> float:
    words = set(tokens(text))
    return weight * sum(1 for q in query if any(token_match(q, w) for w in words))


@dataclass(frozen=True)
class Topic:
    topic: str
    title: str
    domain: str
    summary: str
    related_topics: tuple[str, ...]
    related_operations: tuple[str, ...]
    features: tuple[str, ...]
    body: str = field(repr=False)
    markdown: str = field(repr=False)

    def available_to(self, features: frozenset[str] | None) -> bool:
        return features is None or not self.features or all(f in features for f in self.features)


def _value(raw: str) -> str | list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [part.strip().strip("'\"") for part in raw[1:-1].split(",") if part.strip()]
    return raw.strip("'\"")


def parse_frontmatter(markdown: str) -> tuple[dict[str, str | list[str]], str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, markdown
    meta: dict[str, str | list[str]] = {}
    key: str | None = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            return meta, "\n".join(lines[index + 1 :]).strip()
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key is not None:
            current = meta.get(key)
            meta[key] = [*(current if isinstance(current, list) else []), item.group(1).strip().strip("'\"")]
            continue
        pair = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if pair:
            key = pair.group(1)
            meta[key] = _value(pair.group(2)) if pair.group(2).strip() else []
    return {}, markdown  # no closing marker: not frontmatter


def _list(value: str | list[str] | None) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(v for v in value if v)
    return (value,) if value else ()


class Knowledge:
    def __init__(self, topics: dict[str, Topic], overview: str):
        self.topics = topics
        self.overview = overview

    @classmethod
    def load(cls, directory: Path) -> Knowledge:
        topics: dict[str, Topic] = {}
        overview = ""
        if not directory.is_dir():
            logger.warning("knowledge_directory_missing")
            return cls(topics, overview)
        for path in sorted(directory.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            if path.stem == "overview":
                overview = body  # the overview is returned for an empty query, not listed as a topic
                continue
            name = meta.get("topic")
            if not isinstance(name, str) or not name:
                logger.warning("knowledge_file_skipped file=%s reason=no_topic", path.name)
                continue
            summary = meta.get("summary")
            topics[name] = Topic(
                topic=name,
                title=str(meta.get("title") or name),
                domain=str(meta.get("domain") or ""),
                summary=summary if isinstance(summary, str) else "",
                related_topics=_list(meta.get("related_topics")),
                related_operations=_list(meta.get("related_operations")),
                features=_list(meta.get("features")),
                body=body,
                markdown=text,
            )
        return cls(topics, overview)

    def visible(self, features: frozenset[str] | None) -> list[Topic]:
        return [t for t in self.topics.values() if t.available_to(features)]

    def get(self, name: str, features: frozenset[str] | None) -> Topic | None:
        topic = self.topics.get(name)
        return topic if topic is not None and topic.available_to(features) else None

    def search(
        self, query: list[str], features: frozenset[str] | None, domain: str | None
    ) -> list[tuple[float, Topic]]:
        scored = []
        for topic in self.visible(features):
            if domain and topic.domain != domain:
                continue
            total = (
                score_text(query, topic.topic.replace(".", " ").replace("_", " "), 4)
                + score_text(query, topic.title, 3)
                + score_text(query, topic.summary, 2)
                + score_text(query, topic.body, 0.5)
            )
            if total > 0:
                scored.append((total, topic))
        return sorted(scored, key=lambda pair: (-pair[0], pair[1].topic))
