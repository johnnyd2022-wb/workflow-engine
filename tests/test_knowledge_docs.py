"""Public MCP 8.2g: business knowledge for assistants (`docs/knowledge/*.md`). AC40.

Spec `.agents/specs/public-mcp.md` §"Business knowledge (8.2g)". One Markdown file per topic,
named `<topic>.md`, with a frontmatter block. These tests keep the docs honest:

- every first-set topic exists, with valid frontmatter;
- every `related_topics` link resolves, and every `related_operations` id is a real
  read-only operation (the OpenAPI document once 8.2f has merged, the app's URL map until then);
- the operations a topic's text names are exactly the ones its frontmatter lists;
- every topic says what it means, what the authoritative operation is and what NOT to assume;
- nothing tenant-specific, no real ids, nothing that tells the model to get around permissions.

The frontmatter is a strict subset of YAML (double-quoted strings, block lists), parsed here
without a YAML library so the docs do not force a dependency.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = REPO / "docs" / "knowledge"
OPENAPI_JSON = REPO / "docs" / "openapi.json"

# The first set, by domain (spec §"Business knowledge", "First set"). Topic id = <domain>.<topic>.
# `planning` is not in the spec's list: the planner's cover and batches are layer-3 operations the spec
# names, and 8.2f's overlay already tags them with these two concepts.
SPEC_DOMAINS = {"inventory", "production", "traceability", "compliance", "sales", "costing"}
FIRST_SET = {
    "inventory": [
        "lots",
        "units_and_packs",
        "availability",
        "ready_dates",
        "expiry",
        "holds",
        "untracked_items",
        "sites_and_locations",
        "stocktakes",
    ],
    "production": ["workflows", "steps", "batches", "inputs_and_outputs", "intermediates"],
    "traceability": ["back", "forward", "to_sale"],
    "compliance": ["nz_alcohol_records", "excise_periods", "excise_position", "cca_movements"],
    "sales": ["xero_invoices", "fifo_matching"],
    "costing": [
        "cost_status",
        "readiness",
        "last_known_price",
        "joint_outputs",
        "stock_value",
        "xero_bridge",
        "overheads",
    ],
    "planning": ["stock_cover", "planned_batches"],
}
FIRST_SET_IDS = sorted(f"{domain}.{name}" for domain, names in FIRST_SET.items() for name in names)
ALL_IDS = ["overview", *FIRST_SET_IDS]

FIELDS = ("topic", "title", "domain", "summary", "related_topics", "related_operations", "features")
LIST_FIELDS = ("related_topics", "related_operations", "features")
# Feature keys an org can have or not: the CRM (Sales) pages, Compliant, live costing, several sites.
KNOWN_FEATURES = {"crm", "compliant", "costing", "multi_site"}
SECTIONS = (
    "## What it means",
    "## How the records relate",
    "## Authoritative operations",
    "## Do not assume",
)
TOPIC_ID = re.compile(r"^[a-z]+\.[a-z][a-z0-9_]*$")
OPERATION_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
BACKTICKED = re.compile(r"`([^`\n]+)`")


class FrontmatterError(ValueError):
    pass


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """`---` fenced block of `key: "string"`, `key: []` or `key:` + `  - item` lines, then the body."""
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        raise FrontmatterError("the file must open with a --- fenced frontmatter block")
    end = lines.index("---", 1)
    data: dict = {}
    current: str | None = None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        item = re.fullmatch(r"  - ([a-z0-9_.]+)", raw)
        if item:
            if current is None or not isinstance(data.get(current), list):
                raise FrontmatterError(f"list item with no list: {raw!r}")
            data[current].append(item.group(1))
            continue
        pair = re.fullmatch(r"([a-z_]+):(?: (.*))?", raw)
        if not pair:
            raise FrontmatterError(f"cannot read frontmatter line: {raw!r}")
        key, value = pair.group(1), pair.group(2)
        if key in data:
            raise FrontmatterError(f"duplicate field {key}")
        current = key
        if value is None:
            data[key] = []
        elif value == "[]":
            data[key] = []
        else:
            quoted = re.fullmatch(r'"([^"\\]*)"', value)
            if not quoted:
                raise FrontmatterError(f"{key}: strings must be double-quoted, with no inner quotes: {value!r}")
            data[key] = quoted.group(1)
            current = None
    return data, "\n".join(lines[end + 1 :]).strip("\n")


def _path(topic: str) -> Path:
    return KNOWLEDGE_DIR / f"{topic}.md"


@functools.cache
def _load(topic: str) -> tuple[dict, str]:
    path = _path(topic)
    assert path.is_file(), f"{path.relative_to(REPO)} is missing"
    return parse_frontmatter(path.read_text(encoding="utf-8"))


@functools.cache
def _all_operations() -> dict[str, str]:
    """operationId -> HTTP method, for every API operation. OpenAPI document if present, else the URL map."""
    if OPENAPI_JSON.is_file():
        paths = json.loads(OPENAPI_JSON.read_text(encoding="utf-8")).get("paths", {})
        return {
            op["operationId"]: method.upper()
            for item in paths.values()
            for method, op in item.items()
            if isinstance(op, dict) and "operationId" in op
        }
    import app.app as app_module

    found: dict[str, str] = {}
    for rule in app_module.app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            found.setdefault(rule.endpoint.replace(".", "_"), method)
            if method == "GET":
                found[rule.endpoint.replace(".", "_")] = "GET"
    return found


@functools.cache
def _openapi_operations() -> list[dict]:
    paths = json.loads(OPENAPI_JSON.read_text(encoding="utf-8")).get("paths", {})
    return [op for item in paths.values() for op in item.values() if isinstance(op, dict) and "operationId" in op]


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’-]+", text))


# --- the first set exists ----------------------------------------------------------------------------------


def test_ac40_first_set_topics_exist():
    missing = [topic for topic in ALL_IDS if not _path(topic).is_file()]
    assert missing == []


def test_ac40_first_set_covers_every_spec_domain():
    assert set(FIRST_SET) == SPEC_DOMAINS | {"planning"}


def test_ac40_the_knowledge_dir_holds_only_markdown_topics():
    stray = sorted(p.name for p in KNOWLEDGE_DIR.iterdir() if p.suffix != ".md")
    assert stray == []


def test_ac40_overview_is_about_300_words():
    _, body = _load("overview")
    assert 250 <= _words(body) <= 400, _words(body)


# --- frontmatter -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("topic", ALL_IDS)
def test_ac40_frontmatter_is_valid(topic):
    data, body = _load(topic)
    assert list(data) == list(FIELDS), f"fields must be exactly {FIELDS} in that order, got {list(data)}"
    assert data["topic"] == topic, "the topic must equal the file name"
    if topic != "overview":
        assert TOPIC_ID.match(topic)
        assert data["domain"] == topic.split(".")[0]
    else:
        assert data["domain"] == "overview"
    for field in ("title", "summary"):
        assert isinstance(data[field], str) and data[field].strip() == data[field] and data[field], field
    assert len(data["title"]) <= 80
    assert 20 <= len(data["summary"]) <= 220, "the summary is one line a model can rank on"
    for field in LIST_FIELDS:
        assert isinstance(data[field], list)
        assert len(set(data[field])) == len(data[field]), f"{field} has duplicates"
    assert set(data["features"]) <= KNOWN_FEATURES, set(data["features"]) - KNOWN_FEATURES
    assert body.startswith("# "), "the body opens with a title heading"


@pytest.mark.parametrize("topic", FIRST_SET_IDS)
def test_ac40_every_topic_has_the_sections_an_assistant_needs(topic):
    _, body = _load(topic)
    headings = [line for line in body.split("\n") if line.startswith("## ")]
    assert headings[: len(SECTIONS)] == list(SECTIONS), headings
    assert 120 <= _words(body) <= 900, f"{topic} is {_words(body)} words: short and factual, not a manual"


def test_ac40_the_frontmatter_parser_rejects_what_it_should():
    with pytest.raises(FrontmatterError):
        parse_frontmatter("no fence here")
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\ntopic: unquoted\n---\nbody")
    with pytest.raises(FrontmatterError):
        parse_frontmatter('---\ntopic: "a"\ntopic: "b"\n---\nbody')
    data, body = parse_frontmatter('---\ntopic: "a.b"\nrelated_topics:\n  - c.d\nfeatures: []\n---\n# T\n')
    assert data == {"topic": "a.b", "related_topics": ["c.d"], "features": []}
    assert body == "# T"


# --- links resolve -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("topic", ALL_IDS)
def test_ac40_related_topics_resolve(topic):
    data, _ = _load(topic)
    for target in data["related_topics"]:
        assert target != topic, "a topic does not link to itself"
        assert TOPIC_ID.match(target), target
        assert _path(target).is_file(), f"{topic} links to {target}, which has no file"


@pytest.mark.parametrize("topic", ALL_IDS)
def test_ac40_related_operations_exist_and_are_read_only(topic):
    data, _ = _load(topic)
    operations = _all_operations()
    for op in data["related_operations"]:
        assert OPERATION_ID.match(op), op
        assert op in operations, f"{topic} names {op}, which is not an operation of the app"
        assert operations[op] == "GET", f"{topic} names {op}: an assistant can only run GET operations"


@pytest.mark.parametrize("topic", FIRST_SET_IDS)
def test_ac40_a_topic_names_exactly_the_operations_it_lists(topic):
    """The text and the frontmatter must not drift: a named operation is listed, a listed one is explained."""
    data, body = _load(topic)
    operations = _all_operations()
    in_text = {token for token in BACKTICKED.findall(body) if token in operations}
    listed = set(data["related_operations"])
    assert in_text == listed, f"in text only: {sorted(in_text - listed)}; listed only: {sorted(listed - in_text)}"


@pytest.mark.parametrize("topic", FIRST_SET_IDS)
def test_ac40_the_authoritative_section_names_an_operation_or_says_there_is_none(topic):
    data, body = _load(topic)
    section = body.split("## Authoritative operations", 1)[1].split("\n## ", 1)[0]
    named = [token for token in BACKTICKED.findall(section) if token in _all_operations()]
    assert named or "No operation" in section, f"{topic}: name the operation to ask, or say 'No operation'"
    if not data["related_operations"]:
        assert "No operation" in section


@pytest.mark.parametrize("topic", FIRST_SET_IDS)
def test_ac40_every_topic_is_linked_from_somewhere(topic):
    """A topic nothing links to is one `discover` can only find by luck."""
    linked = {target for t in ALL_IDS for target in _load(t)[0]["related_topics"]}
    assert topic in linked, f"{topic} is not in any related_topics"


def test_ac40_the_overview_reaches_every_domain():
    data, _ = _load("overview")
    assert {t.split(".")[0] for t in data["related_topics"]} == set(FIRST_SET)


_NO_OPENAPI = "docs/openapi.json is not on this branch yet (8.2f, MR !722): checked against the app's URL map instead"


@pytest.mark.skipif(not OPENAPI_JSON.is_file(), reason=_NO_OPENAPI)
def test_ac40_every_x_bize_concept_has_a_topic():
    concepts = {c for op in _openapi_operations() for c in op.get("x-bize", {}).get("concepts", [])}
    assert concepts, "the OpenAPI document tags no operation with a concept"
    topics = {p.stem for p in KNOWLEDGE_DIR.glob("*.md")}
    assert sorted(concepts - topics) == []


@pytest.mark.skipif(not OPENAPI_JSON.is_file(), reason=_NO_OPENAPI)
@pytest.mark.parametrize("topic", FIRST_SET_IDS)
def test_ac40_related_operations_are_ones_an_assistant_may_run(topic):
    """Pointing an assistant at an operation its allowlist refuses would only waste its calls."""
    data, _ = _load(topic)
    allowed = {op["operationId"] for op in _openapi_operations() if op.get("x-bize", {}).get("mcp")}
    assert sorted(set(data["related_operations"]) - allowed) == []


@pytest.mark.skipif(not OPENAPI_JSON.is_file(), reason=_NO_OPENAPI)
@pytest.mark.parametrize("topic", FIRST_SET_IDS)
def test_ac40_a_topic_lists_the_operations_that_are_tagged_with_it(topic):
    """The OpenAPI document says which operations belong to a concept; the topic must list them."""
    data, _ = _load(topic)
    tagged = {op["operationId"] for op in _openapi_operations() if topic in op.get("x-bize", {}).get("concepts", [])}
    assert sorted(tagged - set(data["related_operations"])) == []


# --- what must never be in these docs ----------------------------------------------------------------------

# Written for every tenant: no tenant name, no recipe or ingredient examples from a real producer, no
# real ids or addresses, and nothing that tells a model to get around what the caller may see.
FORBIDDEN = (
    "whistlebird",
    "orris",
    "juniper",
    "botanical",
    "bypass",
    "ignore the permission",
    "ignore permission",
    "ignore previous",
    "disregard",
)
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@pytest.mark.parametrize("topic", ALL_IDS)
def test_ac40_no_tenant_data_no_ids_no_permission_workarounds(topic):
    text = _path(topic).read_text(encoding="utf-8")
    lowered = text.lower()
    assert [word for word in FORBIDDEN if word in lowered] == []
    assert UUID_RE.findall(text) == []
    assert EMAIL_RE.findall(text) == []


@pytest.mark.parametrize("topic", ALL_IDS)
def test_ac40_an_assumption_is_marked_inline_and_says_what_is_assumed(topic):
    text = _path(topic).read_text(encoding="utf-8")
    for line in text.split("\n"):
        if "ASSUMPTION" in line:
            assert re.search(r"ASSUMPTION: \S.{20,}", line), f"an ASSUMPTION needs its text on the same line: {line!r}"
