"""Inventory page copy and its mobile review surface from Jinja templates.

Writes pages, text and relation CSV files for the work-board PostgreSQL index.
No application or customer data is read. Run with --output DIR, then load with
``python scripts/mobile_copy_work_load.py DIR``. The schema is in
``scripts/mobile_copy_work_schema.sql``.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import re
import subprocess
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOTS = (
    ROOT / "app/core/frontend",
    ROOT / "app/features",
    ROOT / "app/admin_site/templates",
    ROOT / "app/ui/templates",
    ROOT / "app/ui/shared",
)
JINJA_CONTROL = re.compile(r"\{[%#].*?[%#]\}", re.DOTALL)
JINJA_VALUE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
SPACE = re.compile(r"\s+")
TEMPLATE_REFERENCE = re.compile(r"\{%\s*(include|extends)\s+['\"]([^'\"]+\.html)['\"]")
CONTAINER_TAGS = {"section", "article", "dialog", "form", "fieldset", "main", "aside", "nav"}
CONTAINER_CLASSES = ("card", "panel", "banner", "intro", "hero", "notice", "summary", "drawer", "sheet", "modal")
TEXT_ATTRIBUTES = ("aria-label", "placeholder", "title", "alt")
DYNAMIC_ATTRIBUTES = ("x-text", "x-html")
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def clean(value: str) -> str:
    return SPACE.sub(" ", JINJA_VALUE.sub("[dynamic]", value)).strip()


def template_name(path: Path) -> str:
    for part in ("templates", "frontend"):
        if part in path.parts:
            i = len(path.parts) - 1 - path.parts[::-1].index(part)
            return "/".join(path.parts[i + 1 :])
    return path.relative_to(ROOT).as_posix()


def serves_get(call: ast.Call, method: str) -> bool:
    if method == "post":
        return False
    methods = next((kw.value for kw in call.keywords if kw.arg == "methods"), None)
    if isinstance(methods, (ast.List, ast.Tuple)):
        values = {item.value for item in methods.elts if isinstance(item, ast.Constant)}
        return "GET" in values
    return True


def route_templates() -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for path in (ROOT / "app").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        prefixes = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if not isinstance(call.func, ast.Name) or call.func.id != "Blueprint":
                continue
            prefix = next(
                (
                    kw.value.value
                    for kw in call.keywords
                    if kw.arg == "url_prefix" and isinstance(kw.value, ast.Constant)
                ),
                "",
            )
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix
        registered: dict[str, set[str]] = defaultdict(set)
        for call in ast.walk(tree):
            if (
                not isinstance(call, ast.Call)
                or not isinstance(call.func, ast.Attribute)
                or call.func.attr != "add_url_rule"
                or not serves_get(call, "add_url_rule")
            ):
                continue
            view = next((keyword.value for keyword in call.keywords if keyword.arg == "view_func"), None)
            if (
                call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
                and isinstance(view, ast.Name)
            ):
                owner = call.func.value.id if isinstance(call.func.value, ast.Name) else ""
                registered[view.id].add(prefixes.get(owner, "").rstrip("/") + call.args[0].value)
        functions = {
            node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        direct_templates: dict[str, set[str]] = defaultdict(set)
        calls: dict[str, set[str]] = defaultdict(set)
        route_functions: dict[str, list[str]] = {}
        for function in functions.values():
            routes = list(registered.get(function.name, ()))
            for decorator in function.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if (
                    decorator.func.attr not in {"route", "get", "post"}
                    or not decorator.args
                    or not serves_get(decorator, decorator.func.attr)
                ):
                    continue
                if isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                    owner = decorator.func.value.id if isinstance(decorator.func.value, ast.Name) else ""
                    routes.append(prefixes.get(owner, "").rstrip("/") + decorator.args[0].value)
            if routes:
                route_functions[function.name] = routes
            for call in ast.walk(function):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                    continue
                if (
                    call.func.id == "render_template"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                ):
                    direct_templates[function.name].add(call.args[0].value)
                elif call.func.id in functions:
                    calls[function.name].add(call.func.id)
        for name, function_routes in route_functions.items():
            pending = [name]
            seen = set()
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                for template in direct_templates[current]:
                    found[template].update(function_routes)
                pending.extend(calls[current] - seen)
    return found


class CopyParser(HTMLParser):
    def __init__(self, page_key: str):
        super().__init__(convert_charrefs=True)
        self.page_key = page_key
        self.stack: list[dict] = []
        self.rows: list[dict] = []
        self.counts: dict[str, int] = defaultdict(int)
        self.locator_counts: dict[str, int] = defaultdict(int)
        self.first_heading = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        line = self.getpos()[0]
        classes = attributes.get("class") or ""
        identity = attributes.get("id") or (classes.split()[0] if classes else tag)
        locator_base = f"{tag}#{identity}"
        self.locator_counts[locator_base] += 1
        locator = f"{locator_base}:{self.locator_counts[locator_base]}"
        is_container = tag in CONTAINER_TAGS or any(part in classes for part in CONTAINER_CLASSES)
        inherited = self.stack[-1]["container"] if self.stack else "page"
        container = locator if is_container else inherited
        self.stack.append({"tag": tag, "locator": locator, "container": container, "line": line})
        if tag in {"script", "style"}:
            return
        for name in TEXT_ATTRIBUTES + DYNAMIC_ATTRIBUTES:
            value = attributes.get(name)
            if value:
                self.add_text(value, line, tag, container, name)
        if tag in VOID_TAGS:
            self.stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if not self.stack or any(item["tag"] in {"script", "style"} for item in self.stack):
            return
        item = self.stack[-1]
        self.add_text(data, self.getpos()[0], item["tag"], item["container"], "visible")
        if item["tag"] == "h1" and not self.first_heading:
            self.first_heading = clean(data)

    def add_text(self, raw: str, line: int, tag: str, container: str, source: str) -> None:
        value = clean(raw)
        if not value or (value == "[dynamic]" and source == "visible"):
            return
        if source == "visible" and not any(char.isalnum() for char in value):
            return
        base = f"{tag}:{source}:{container}:{value}"
        self.counts[base] += 1
        key = hashlib.sha1(f"{base}:{self.counts[base]}".encode()).hexdigest()[:16]
        words = len(value.split())
        suggestion = (
            "review"
            if source in DYNAMIC_ATTRIBUTES or "[dynamic]" in value
            else ("collapse" if words >= 55 else "shorten" if words >= 24 else "keep")
        )
        self.rows.append(
            dict(
                page_key=self.page_key,
                node_key=key,
                container_key=container,
                source_line=line,
                element_tag=tag,
                text_source=source,
                desktop_text=value,
                word_count=words,
                suggested_mobile_treatment=suggestion,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="Directory for pages.csv and text.csv")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    routes = route_templates()
    pages = []
    texts = []
    relations = []
    relation_keys = set()
    paths = sorted({path for root in TEMPLATE_ROOTS for path in root.rglob("*.html")})
    by_name: dict[str, list[Path]] = defaultdict(list)
    for path in paths:
        by_name[template_name(path)].append(path)
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        name = template_name(path)
        source = path.read_text()
        parsed = CopyParser(relative)
        parsed.feed(JINJA_CONTROL.sub(lambda match: "\n" * match.group().count("\n"), source))
        title_match = re.search(r"\{%\s*block title\s*%\}(.*?)\{%\s*endblock", source, re.DOTALL)
        title = clean(title_match.group(1)) if title_match else parsed.first_heading
        page_routes = sorted(routes.get(name, []))
        standalone = "{% extends" in source or "<!doctype" in source.lower()
        kind = "routed" if page_routes else "page_route_unmapped" if standalone else "shared"
        pages.append(
            dict(
                page_key=relative,
                template_name=name,
                route_patterns=" | ".join(page_routes),
                page_kind=kind,
                page_title=title,
                source_commit=commit,
            )
        )
        for row in parsed.rows:
            row["source_commit"] = commit
        texts.extend(parsed.rows)
        for relation, target in TEMPLATE_REFERENCE.findall(source):
            matches = by_name.get(target, [])
            if not matches:
                continue
            chosen = min(
                matches, key=lambda candidate: ("/app/ui/templates/" not in candidate.as_posix(), candidate.as_posix())
            )
            included = chosen.relative_to(ROOT).as_posix()
            key = (relative, included, relation)
            if key not in relation_keys:
                relation_keys.add(key)
                relations.append(
                    dict(page_key=relative, included_page_key=included, relation=relation, source_commit=commit)
                )
    for filename, rows in (("pages.csv", pages), ("text.csv", texts), ("relations.csv", relations)):
        with (args.output / filename).open("w", newline="") as stream:
            fieldnames = list(rows[0]) if rows else ["page_key", "included_page_key", "relation", "source_commit"]
            writer = csv.DictWriter(stream, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(rows)
    print(
        f"{len(pages)} templates, {len(texts)} text entries, {len(relations)} template links, {sum(p['page_kind'] == 'routed' for p in pages)} routed templates"
    )


if __name__ == "__main__":
    main()
