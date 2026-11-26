#!/usr/bin/env python3
"""Inventory mounted routes, direct request reads, and static template controls.

URL rules and access policy come from the app. Python reads and HTML controls are
review leads. Calls through helpers, dynamic templates and JS controls need manual review.

Run with ENVIRONMENT unset: python -m scripts.input_validation_inventory [--blueprint auth]
"""

import argparse
import ast
import contextlib
import inspect
import json
import secrets
import sys
import textwrap
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST_INPUTS = {
    "args",
    "cookies",
    "data",
    "files",
    "form",
    "get_data",
    "get_json",
    "headers",
    "json",
    "query_string",
    "stream",
    "values",
    "view_args",
}
FORM_TAGS = {"form", "input", "select", "textarea"}
FORM_ATTRIBUTES = {
    "accept",
    "action",
    "disabled",
    "enctype",
    "form",
    "id",
    "max",
    "maxlength",
    "method",
    "min",
    "minlength",
    "multiple",
    "name",
    "novalidate",
    "pattern",
    "required",
    "step",
    "type",
}


def source_inputs(view):
    handler = inspect.unwrap(view)
    source_path = inspect.getsourcefile(handler)
    if not source_path or not Path(source_path).is_relative_to(ROOT):
        return {"source": None, "reads": []}
    try:
        lines, start = inspect.getsourcelines(handler)
    except OSError:
        return {"source": None, "reads": []}
    source = str(Path(source_path).relative_to(ROOT))
    code = textwrap.dedent("".join(lines))
    tree = ast.parse(code)
    reads = [
        {"line": start + node.lineno - 1, "source": ast.get_source_segment(code, node)}
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "request"
        and node.attr in REQUEST_INPUTS
    ]
    return {"source": source, "line": start, "reads": sorted(reads, key=lambda read: read["line"])}


def route_inventory(app, requirement_for, deny, blueprint):
    routes = []
    for rule in app.url_map.iter_rules():
        owner = rule.endpoint.rpartition(".")[0]
        if blueprint and owner != blueprint and not owner.startswith(f"{blueprint}."):
            continue
        handler = source_inputs(app.view_functions[rule.endpoint])
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            requirement = requirement_for(rule.endpoint, method)
            routes.append(
                {
                    "blueprint": owner,
                    "endpoint": rule.endpoint,
                    "method": method,
                    "route": rule.rule,
                    "policy": "deny" if requirement is deny else requirement,
                    "path_parameters": sorted(rule.arguments),
                    **handler,
                }
            )
    return sorted(routes, key=lambda route: (route["blueprint"], route["route"], route["method"]))


class Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.controls = []

    def handle_starttag(self, tag, attrs):
        if tag in FORM_TAGS:
            self.controls.append(
                {
                    "line": self.getpos()[0],
                    "tag": tag,
                    "attributes": {name: value for name, value in attrs if name in FORM_ATTRIBUTES},
                }
            )


def template_inventory():
    templates = {}
    for template in sorted((ROOT / "app").rglob("*.html")):
        parser = Controls()
        parser.feed(template.read_text(encoding="utf-8"))
        if parser.controls:
            templates[str(template.relative_to(ROOT))] = parser.controls
    return templates


def staff_routes(blueprint):
    from app.admin_site.app_factory import create_admin_app
    from app.admin_site.auth import PUBLIC_ENDPOINTS
    from app.admin_site.settings import AdminSettings

    staff_app = create_admin_app(
        AdminSettings(
            environment="test",
            allowed_emails=frozenset({"admin@example.test"}),
            require_authoritative_email=True,
            secret_key=secrets.token_urlsafe(32),
            google_client_id="inventory-only",
            google_client_secret="inventory-only",
            google_redirect_uri="https://admin.example.test/auth/google/callback",
            customer_app_url="https://example.test",
        )
    )

    def policy(endpoint, _method):
        return "public" if endpoint in PUBLIC_ENDPOINTS else "staff_session"

    return route_inventory(staff_app, policy, deny=None, blueprint=blueprint)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blueprint", help="Limit routes to one blueprint and its children")
    parser.add_argument("--staff", action="store_true", help="Inventory the separate staff application")
    args = parser.parse_args()

    with contextlib.redirect_stdout(sys.stderr):
        if args.staff:
            routes = staff_routes(args.blueprint)
        else:
            from app.app import app
            from app.core.security.access_policy import DENY, requirement_for

            routes = route_inventory(app, requirement_for, DENY, args.blueprint)

    inventory = {
        "routes": routes,
        "templates": template_inventory(),
    }
    json.dump(inventory, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
