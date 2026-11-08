"""GL-S03 step 3: every Alpine expression in the templates parses under Alpine's CSP build.

The CSP build has its own small expression parser instead of `new Function`, and it rejects
template literals, arrow functions, `?.`, statement sequences and `+=`. A rejected expression
only fails when it runs (a click, a modal opening), so loading the pages misses most of them.
This hands every attribute in app/**/*.html to the build's own parser instead.

Globals (`Math`, `window`, `encodeURIComponent`) parse but fail when evaluated, so a regex
catches those.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

APP = Path(__file__).resolve().parents[2] / "app"
BUILD = APP / "core" / "frontend" / "js" / "alpinejs-csp.min.js"
ATTR = re.compile(r"""\s((?:x-[\w:.-]+|@[\w.:-]+|:[\w.-]+))\s*=\s*("([^"]*)"|'([^']*)')""", re.S)
# Attributes whose value is not an expression.
NOT_EXPRESSIONS = ("x-ref", "x-cloak", "x-transition", "x-ignore", "x-teleport", "x-id", "x-collapse")
GLOBALS = re.compile(
    r"\b(window|document|Math|JSON|parseInt|parseFloat|console|Number|String|Boolean|Date|Object|Array"
    r"|localStorage|setTimeout|fetch|alert|encodeURIComponent|isNaN)\s*[.(]"
)


def _expressions() -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(APP.rglob("*.html")):
        text = path.read_text()
        for m in ATTR.finditer(text):
            name = m.group(1)
            value = m.group(3) if m.group(3) is not None else m.group(4)
            if name.startswith(NOT_EXPRESSIONS):
                continue
            # A bound attribute that is only Jinja (`:href="{{ url }}"`) has no Alpine in it.
            if name.startswith(":") and "{{" in value and "'" not in value:
                continue
            value = html.unescape(re.sub(r"\{\{.*?\}\}", "x", value, flags=re.S)).strip()
            if not value:
                continue
            if name.startswith("x-for"):
                value = re.split(r"\s+(?:in|of)\s+", value, maxsplit=1)[1]
            where = f"{path.relative_to(APP)}:{text[: m.start()].count(chr(10)) + 1}"
            found.append((where, name, value))
    return found


def test_there_are_expressions_to_check():
    # A broken attribute regex would pass both tests below by finding nothing.
    assert len(_expressions()) > 1000


def test_no_alpine_expression_names_a_browser_global():
    offenders = [f"{w} {n}={v!r}" for w, n, v in _expressions() if GLOBALS.search(v)]
    assert offenders == [], "move these into a component method:\n" + "\n".join(offenders)


def test_every_alpine_expression_parses_under_the_csp_build(browser):
    source = BUILD.read_text()
    # The parser is a module-private function; expose it. It is defined when Alpine first
    # evaluates something, so the page carries one small component.
    hook = "function Me(t){"
    assert source.count(hook) == 1, "the Alpine CSP build changed: find its parser function again"
    source = source.replace(hook, "globalThis.__cspParse=Me;" + hook)

    page = browser.new_page()
    try:
        # A real origin: the build reads localStorage, which an about:blank page refuses.
        page.route(
            "https://alpine-csp.test/",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body='<html><body><div x-data="{ a: 1 }"><span x-text="a"></span></div></body></html>',
            ),
        )
        page.goto("https://alpine-csp.test/")
        page.add_script_tag(content=source)
        page.wait_for_function("typeof globalThis.__cspParse === 'function'", timeout=5000)
        rejected = page.evaluate(
            """(list) => list.map(([where, name, value]) => {
                try { globalThis.__cspParse(value); return null; }
                catch (e) { return where + ' ' + name + '="' + value + '": ' + e.message; }
            }).filter(Boolean)""",
            _expressions(),
        )
    finally:
        page.close()
    assert rejected == [], "rewrite these for the CSP build:\n" + "\n".join(rejected)
