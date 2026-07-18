#!/usr/bin/env python3
"""Deterministic E2E coverage map: which app routes the Playwright suite touches, and
which are gaps.

Answers, in one cheap pass, the question an agent would otherwise re-derive by reading the
whole app and the whole test suite: for every route the app exposes, is there an E2E test
that exercises it, and for which HTTP methods? Skills call this BEFORE writing or running
E2E tests so they spend tokens on the actual gaps instead of rediscovering the map.

Design rules (same as preflight.py / error_scan.py):
- stdlib only; the sole non-stdlib touch is importing the app to read its real url_map,
  which is the only accurate source of the route surface (blueprint prefixes and all).
- machine-readable first (`--json`). Agents parse the gap list; humans read the summary.
- it reports, it does not fix. Writing the missing tests is the calling skill's decision.
- app import noise (structlog, OTel) is redirected to stderr so `--json` stdout stays clean.

Coverage is derived by matching:
- the app's (method, rule) pairs from `app.url_map`, against
- every route-like string and f-string literal in `tests/e2e/*.py` (from `page.goto(...)`,
  `page.request.<verb>(...)`, and parametrized page lists), with the verb inferred from the
  call (`.request.post` -> POST; `goto` and bare string constants -> GET).

A route counts as covered for a method when some tested path with that verb matches its
rule (Flask `<param>` and test `{expr}` segments are wildcards).

Usage:
    python scripts/e2e_coverage.py               # human summary
    python scripts/e2e_coverage.py --json        # full JSON (covered + gaps)
    python scripts/e2e_coverage.py --gaps        # human summary, list every gap
    python scripts/e2e_coverage.py --check       # exit 1 if any non-excluded gap exists
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = REPO_ROOT / "tests" / "e2e"

METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")

# Routes that are infrastructure, not user-facing flows. Absence of an E2E test here is not
# a gap worth an agent's tokens: static assets, health, telemetry proxies, SDK shims.
EXCLUDE_PREFIXES = ("/static", "/telemetry", "/ui/shared", "/crm/static")
EXCLUDE_EXACT = {"/healthcheck", "/initialize", "/landing-diagram"}

# Endpoints exercised through the browser UI (a form submit) rather than a page.request
# literal the matcher can see. These are genuinely covered — the JS behind the form does
# the POST — so listing them as gaps would be a false alarm that wastes an agent's tokens
# chasing tests that already exist. Keep this list tiny and only for real form flows; every
# entry names the test that drives it. API calls made with page.request are matched
# automatically and must NOT be added here.
UI_DRIVEN_COVERAGE = {
    ("POST", "/auth/login"): "test_auth_flows / login_through_ui (login modal)",
    ("POST", "/auth/signup"): "test_auth_flows::test_signup_creates_org_and_signs_in",
    ("POST", "/auth/verify-2fa"): "test_auth_flows::test_2fa_enroll_enable_then_login_requires_a_code",
}

_ROUTE_STR = re.compile(r"^/[A-Za-z0-9_\-/.<>:{}]*$")


# --------------------------------------------------------------------------------------
# App surface
# --------------------------------------------------------------------------------------


def app_routes() -> list[dict]:
    """(method, rule) pairs from the real url_map. App import noise goes to stderr."""
    with contextlib.redirect_stdout(sys.stderr):
        from app.app import app  # noqa: PLC0415

    routes = []
    for rule in app.url_map.iter_rules():
        methods = sorted(m for m in rule.methods if m in METHODS)
        if not methods:
            continue
        routes.append({"rule": rule.rule, "methods": methods, "endpoint": rule.endpoint})
    routes.sort(key=lambda r: r["rule"])
    return routes


def _excluded(rule: str) -> bool:
    return rule in EXCLUDE_EXACT or any(rule.startswith(p) for p in EXCLUDE_PREFIXES)


def _category(rule: str) -> str:
    if _excluded(rule):
        return "excluded"
    if rule.startswith("/api/"):
        return "api"
    return "page"


# --------------------------------------------------------------------------------------
# Tested paths (from the E2E test sources)
# --------------------------------------------------------------------------------------


def _joined_template(node: ast.JoinedStr) -> str | None:
    """Reconstruct an f-string into a template, interpolations -> '{}' wildcard segments."""
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append("{}")
    text = "".join(parts)
    return text if text.startswith("/") else None


def tested_paths() -> list[tuple[str, str, str]]:
    """List of (verb, path_template, source_file) touched by the E2E suite."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(E2E_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        rel = str(path.relative_to(REPO_ROOT))

        for node in ast.walk(tree):
            # Verb-bearing calls: page.goto(...) and page.request.<verb>(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                verb = None
                if attr == "goto":
                    verb = "GET"
                elif attr in ("get", "post", "put", "delete", "patch", "fetch", "head"):
                    verb = "GET" if attr in ("get", "fetch", "head") else attr.upper()
                if verb and node.args:
                    tpl = _literal_route(node.args[0])
                    if tpl:
                        found.append((verb, tpl, rel))

            # Bare route string constants (parametrized page lists, module constants).
            # Attributed to GET — these are page navigations.
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _ROUTE_STR.match(node.value) and len(node.value) > 1:
                    found.append(("GET", node.value.split("?")[0], rel))
    return found


def _literal_route(arg: ast.expr) -> str | None:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value.split("?")[0] if arg.value.startswith("/") else None
    if isinstance(arg, ast.JoinedStr):
        tpl = _joined_template(arg)
        return tpl.split("?")[0] if tpl else None
    return None


# --------------------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------------------


def _segs(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s != ""]


def _seg_is_wild(seg: str) -> bool:
    return (seg.startswith("<") and seg.endswith(">")) or (seg.startswith("{") and seg.endswith("}"))


def path_matches_rule(url: str, rule: str) -> bool:
    """A tested url template matches a Flask rule (wildcards on either side)."""
    r_segs, u_segs = _segs(rule), _segs(url)
    # <path:...> in the last rule segment swallows the remainder.
    if r_segs and r_segs[-1].startswith("<path:"):
        if len(u_segs) < len(r_segs):
            return False
        r_head, u_head = r_segs[:-1], u_segs[: len(r_segs) - 1]
        return all(_seg_is_wild(r) or _seg_is_wild(u) or r == u for r, u in zip(r_head, u_head))
    if len(r_segs) != len(u_segs):
        return False
    return all(_seg_is_wild(r) or _seg_is_wild(u) or r == u for r, u in zip(r_segs, u_segs))


def build_coverage() -> dict:
    routes = app_routes()
    tested = tested_paths()
    tested_by_verb: dict[str, list[str]] = {}
    for verb, url, _src in tested:
        tested_by_verb.setdefault(verb, []).append(url)

    rows = []
    for r in routes:
        rule = r["rule"]
        covered, missing, ui = [], [], []
        for method in r["methods"]:
            urls = tested_by_verb.get(method, [])
            if any(path_matches_rule(u, rule) for u in urls):
                covered.append(method)
            elif (method, rule) in UI_DRIVEN_COVERAGE:
                covered.append(method)
                ui.append(method)
            else:
                missing.append(method)
        row = {
            "rule": rule,
            "endpoint": r["endpoint"],
            "category": _category(rule),
            "covered_methods": covered,
            "missing_methods": missing,
        }
        if ui:
            row["ui_driven_methods"] = ui
        rows.append(row)

    considered = [row for row in rows if row["category"] != "excluded"]
    gaps = [row for row in considered if row["missing_methods"]]
    fully = [row for row in considered if not row["missing_methods"]]
    return {
        "summary": {
            "app_routes_total": len(rows),
            "considered": len(considered),
            "excluded": len(rows) - len(considered),
            "fully_covered": len(fully),
            "with_gaps": len(gaps),
            "e2e_test_files": len(list(E2E_DIR.glob("test_*.py"))),
        },
        "gaps": gaps,
        "routes": rows,
    }


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _print_human(data: dict, show_gaps: bool) -> None:
    s = data["summary"]
    print("E2E coverage map")
    print(
        f"  routes: {s['considered']} considered "
        f"({s['excluded']} excluded), "
        f"{s['fully_covered']} fully covered, {s['with_gaps']} with gaps"
    )
    print(f"  e2e test files: {s['e2e_test_files']}")
    if s["with_gaps"] and (show_gaps or True):
        print("\n  gaps (route: methods with no E2E coverage):")
        for row in data["gaps"]:
            tag = row["category"]
            print(f"    [{tag}] {row['rule']}  →  {', '.join(row['missing_methods'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic E2E route-coverage map.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--gaps", action="store_true", help="list every gap (human)")
    parser.add_argument("--check", action="store_true", help="exit 1 if any non-excluded gap exists")
    args = parser.parse_args()

    # Ensure the repo root is importable when run as a plain script.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        data = build_coverage()
    except Exception as exc:  # pragma: no cover - defensive
        err = {"error": f"could not build coverage: {exc}"}
        if args.json:
            print(json.dumps(err))
        else:
            print(f"e2e_coverage: {err['error']}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_human(data, args.gaps)

    if args.check and data["summary"]["with_gaps"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
