"""AC36 and AC39: the generated OpenAPI 3.1 document, and the committed copy of it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from openapi_spec_validator import validate

from app.api.openapi import canonical_json
from app.core.security.access_policy import SIGNED_IN, requirement_for
from tests.openapi.support import by_id, operations

ROOT = Path(__file__).resolve().parents[2]


def _api_rules(app):
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/"):
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                yield rule, method


def _openapi_path(rule: str) -> str:
    """``/api/x/<uuid:item_id>/<path:key>`` -> ``/api/x/{item_id}/{key}``."""
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", rule)


# --- AC36 ---------------------------------------------------------------------------------------


def test_ac36_the_document_validates_as_openapi_3_1(full_doc):
    assert full_doc["openapi"].startswith("3.1")
    validate(full_doc)


def test_ac36_every_api_route_and_method_appears_with_an_operation_id_a_summary_and_a_permission(flask_app, full_doc):
    expected = {(_openapi_path(rule.rule), method) for rule, method in _api_rules(flask_app)}
    got = {(path, method) for path, method, _op in operations(full_doc)}
    assert got == expected
    for path, method, op in operations(full_doc):
        label = f"{method} {path}"
        assert op.get("operationId"), label
        assert (op.get("summary") or "").strip(), label
        assert "permission" in op.get("x-bize", {}), label


def test_ac36_operation_ids_are_unique_and_are_the_endpoint_name_with_dots_as_underscores(flask_app, full_doc):
    ids = [op["operationId"] for _p, _m, op in operations(full_doc)]
    assert len(ids) == len(set(ids))
    endpoints = {rule.endpoint.replace(".", "_") for rule, _m in _api_rules(flask_app)}
    assert set(ids) == endpoints  # one method per endpoint in this app, so no suffix is needed


def test_ac36_permission_is_what_the_policy_says(flask_app, full_doc):
    for rule, method in _api_rules(flask_app):
        op = by_id(full_doc)[rule.endpoint.replace(".", "_")][2]
        requirement = requirement_for(rule.endpoint, method)
        want = list(requirement) if isinstance(requirement, tuple) else requirement
        assert op["x-bize"]["permission"] == want, rule.endpoint


def test_ac36_public_and_signed_in_routes_are_named_as_such(full_doc):
    ops = by_id(full_doc)
    assert ops["mcp_get_me"][2]["x-bize"]["permission"] == SIGNED_IN
    assert ops["core_list_inventory"][2]["x-bize"]["permission"] == "inventory.view"
    assert ops["costing_get_stock_value"][2]["x-bize"]["permission"] == "costs.view"


def test_ac36_every_operation_has_a_domain_and_the_optional_products_say_which_one(full_doc):
    ops = by_id(full_doc)
    for _path, _method, op in operations(full_doc):
        assert op["x-bize"].get("domain"), op["operationId"]
    assert ops["crm_crm_api_monthly_sales"][2]["x-bize"]["feature"] == "crm"
    assert ops["compliant_compliant_api_get_excise_position"][2]["x-bize"]["feature"] == "compliant"
    assert "feature" not in ops["core_list_inventory"][2]["x-bize"]


def test_ac36_the_document_says_how_to_sign_in_and_that_it_lives_on_the_callers_host(full_doc):
    schemes = full_doc["components"]["securitySchemes"]
    assert schemes["bearerToken"]["type"] == "http" and schemes["bearerToken"]["scheme"] == "bearer"
    assert schemes["sessionCookie"]["type"] == "apiKey" and schemes["sessionCookie"]["in"] == "cookie"
    assert full_doc["servers"] == [{"url": "/", "description": full_doc["servers"][0]["description"]}]
    ops = by_id(full_doc)
    # A write is session-only; a read behind a view permission also takes a token; a public route takes neither.
    assert {tuple(s) for s in ops["core_create_process"][2]["security"]} == {("sessionCookie",)}
    assert {tuple(s) for s in ops["core_list_inventory"][2]["security"]} == {("sessionCookie",), ("bearerToken",)}


def test_the_document_is_the_same_whatever_order_python_iterates_sets_in(full_doc):
    """A second interpreter with another hash seed must produce byte-identical output."""
    script = (
        "import hashlib, sys\n"
        "sys.path.insert(0, '.')\n"
        "from app.api.app_factory import create_app\n"
        "from app.api.openapi import build_document, canonical_json\n"
        "print(hashlib.sha256(canonical_json(build_document(create_app())).encode()).hexdigest())\n"
    )
    env = {**os.environ, "PYTHONHASHSEED": "12345"}
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300, check=True
    )
    assert out.stdout.strip().splitlines()[-1] == hashlib.sha256(canonical_json(full_doc).encode()).hexdigest()


FORBIDDEN_IN_THE_DOCUMENT = {
    "an internal host": re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|host\.docker\.internal|\.internal\b|\.local\b", re.I),
    "a private address": re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+(?:\.\d+)?\b"),
    "one of our own tokens": re.compile(r"\bbz[acr]_[A-Za-z0-9_-]{8,}"),
    "a key or secret value": re.compile(r"-----BEGIN|AKIA[0-9A-Z]{12,}|sk-[A-Za-z0-9]{20,}|xox[bap]-"),
    "a checkout path": re.compile(r"/home/\w+|\.agents/|app/(?:core|features|api)/"),
    "an email address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
}


@pytest.mark.parametrize("what", sorted(FORBIDDEN_IN_THE_DOCUMENT))
def test_the_document_holds_no_secrets_internal_hostnames_or_checkout_paths(full_doc, what):
    text = canonical_json(full_doc)
    hits = sorted({m.group(0) for m in FORBIDDEN_IN_THE_DOCUMENT[what].finditer(text)})
    assert hits == [], f"the document contains {what}: {hits[:5]}"


def test_the_only_urls_in_the_document_are_the_openapi_standard_ones(full_doc):
    urls = sorted(set(re.findall(r"https?://[^\s\"')]+", canonical_json(full_doc))))
    assert [u for u in urls if not u.startswith("https://spec.openapis.org/")] == []


# --- AC39 ---------------------------------------------------------------------------------------


def test_ac39_the_committed_document_equals_the_generated_one(full_doc):
    committed = (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8")
    assert committed == canonical_json(full_doc), (
        "docs/openapi.json is stale. Regenerate it with `uv run python scripts/check_openapi.py --write` "
        "and commit the result."
    )
    assert json.loads(committed)["openapi"].startswith("3.1")
