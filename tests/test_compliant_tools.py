"""Compliant Tools suite: catalogue, dispatch, calculators, purity, page.

Covers spec .agents/specs/compliant_tools.md AC9-AC17.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.db.models.user import UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.compliant.tools.errors import CalculatorValidationError
from app.features.compliant.tools.registry import CALCULATORS, CATALOGUE
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOLVER_DIR = _REPO_ROOT / "app" / "features" / "compliant" / "tools" / "calculators"

TIER1_KEYS = [
    "dilution",
    "lal",
    "standard_drinks",
    "abv_abw",
    "gravity_convert",
    "abv_from_og_fg",
    "tank_volume",
    "yield_loss",
    "yeast_pitch",
    "keg_fill",
]

# input -> {field: (expected, abs_tol)}
FIXTURES: dict[str, list[tuple[dict, dict]]] = {
    "dilution": [
        (
            {"solve_for": "final_volume_ml", "starting_abv": 40, "starting_volume_ml": 1000, "final_abv": 20},
            {"solved_value": (2000.0, 0.0), "water_to_add_naive_ml": (1000.0, 0.0)},
        ),
        (
            {"solve_for": "final_abv", "starting_abv": 40, "starting_volume_ml": 1000, "final_volume_ml": 2000},
            {"solved_value": (20.0, 1e-9)},
        ),
    ],
    "lal": [
        ({"volume_l": 100, "abv_pct": 40}, {"lal": (40.0, 1e-9)}),
        ({"abv_pct": 40, "lal": 40}, {"volume_l": (100.0, 1e-9)}),
        ({"volume_l": 100, "lal": 40}, {"abv_pct": (40.0, 1e-9)}),
    ],
    "standard_drinks": [
        ({"volume_ml": 330, "abv_pct": 5}, {"standard_drinks": (1.302246, 1e-6)}),
        ({"solve_for": "volume_ml", "standard_drinks": 1, "abv_pct": 40}, {"volume_ml": (31.6761, 1e-3)}),
    ],
    "abv_abw": [
        ({"abv_pct": 40, "solution_sg": 0.9352}, {"abw_pct": (33.7571, 1e-3)}),
        ({"solve_for": "abv_pct", "abw_pct": 33.7571, "solution_sg": 0.9352}, {"abv_pct": (40.0, 1e-2)}),
    ],
    "gravity_convert": [
        ({"sg": 1.048}, {"plato": (11.91, 0.05), "baume": (6.6412, 1e-3)}),
        ({"plato": 11.91}, {"sg": (1.048, 1e-3)}),
        ({"baume": 6.6412}, {"sg": (1.048, 1e-4)}),
    ],
    "abv_from_og_fg": [
        ({"og_sg": 1.050, "fg_sg": 1.010}, {"abv_pct": (5.25, 1e-6), "apparent_attenuation_pct": (80.0, 1e-6)}),
    ],
    "tank_volume": [
        (
            {"diameter_m": 1.0, "cyl_height_m": 2.0, "cone_height_m": 0.3, "fill_height_m": 1.3},
            {"capacity_l": (1649.336, 0.01), "filled_l": (863.938, 0.01), "headspace_l": (785.398, 0.01)},
        ),
        (
            {"diameter_m": 1.0, "cyl_height_m": 2.0, "cone_height_m": 0, "fill_height_m": 0.5},
            {"capacity_l": (1570.796, 0.01), "filled_l": (392.699, 0.01)},
        ),
        (
            {"diameter_m": 1.0, "cyl_height_m": 2.0, "cone_height_m": 0.3, "fill_height_m": 0},
            {"filled_l": (0.0, 0.0), "headspace_l": (1649.336, 0.01)},
        ),
    ],
    "yield_loss": [
        (
            {
                "start_volume_l": 1000,
                "steps": [
                    {"name": "brewhouse", "loss_pct": 8},
                    {"name": "fermentation", "loss_pct": 5},
                    {"name": "packaging", "loss_pct": 2},
                ],
            },
            {"final_volume_l": (856.52, 1e-6), "total_loss_l": (143.48, 1e-6), "effective_yield_pct": (85.652, 1e-6)},
        ),
    ],
    "yeast_pitch": [
        (
            {"volume_l": 20, "gravity_plato": 12, "pitch_rate_m_per_ml_per_p": 1.0},
            {"cells_required_billion": (240.0, 1e-9), "packs": (3, 0)},
        ),
    ],
    "keg_fill": [
        (
            {"available_l": 1000, "keg_size_l": 50, "fill_loss_pct": 2},
            {"full_kegs": (19, 0), "packaged_l": (950.0, 1e-6), "loss_l": (19.0, 1e-6), "remainder_l": (31.0, 1e-6)},
        ),
    ],
}

REJECTIONS: dict[str, list[dict]] = {
    "lal": [
        {"volume_l": 100, "abv_pct": 40, "lal": 40},  # all three present
        {"volume_l": 100},  # only one
        {"abv_pct": 0, "lal": 40},  # solving volume_l with abv 0
        {"volume_l": 100, "abv_pct": "x"},  # non-number
        {"volume_l": 100, "abv_pct": True},  # bool rejected
    ],
    "standard_drinks": [
        {"solve_for": "volume_ml", "standard_drinks": 1, "abv_pct": 0},
        {"volume_ml": 330},  # missing abv_pct
        {"volume_ml": 330, "abv_pct": 150},
    ],
    "abv_abw": [
        {"abv_pct": 40},  # missing solution_sg
        {"abv_pct": 40, "solution_sg": 1.5},
        {"abv_pct": 120, "solution_sg": 0.99},
    ],
    "gravity_convert": [
        {},  # zero inputs
        {"sg": 1.04, "plato": 10},  # two inputs
        {"sg": 1.30},
        {"plato": 40},
        {"baume": 25},
    ],
    "abv_from_og_fg": [
        {"og_sg": 1.01, "fg_sg": 1.02},  # og <= fg
        {"og_sg": 1.000, "fg_sg": 0.999},  # og not > 1.000
        {"og_sg": 1.05},  # missing fg
    ],
    "tank_volume": [
        {"diameter_m": 1.0, "cyl_height_m": 2.0, "cone_height_m": 0.3, "fill_height_m": 3.0},
        {"diameter_m": 0, "cyl_height_m": 2.0, "fill_height_m": 1.0},
    ],
    "yield_loss": [
        {"start_volume_l": 1000, "steps": []},
        {"start_volume_l": 1000, "steps": [{"name": "a", "loss_pct": 5, "loss_l": 2}]},
        {"start_volume_l": 1000, "steps": [{"name": "a", "loss_pct": 5}, {"name": "b", "loss_l": 2}]},
        {"start_volume_l": 0, "steps": [{"name": "a", "loss_pct": 5}]},
        {"start_volume_l": 10, "steps": [{"name": "a", "loss_l": 20}]},
    ],
    "yeast_pitch": [
        {"volume_l": 0, "gravity_plato": 12, "pitch_rate_m_per_ml_per_p": 1},
        {"volume_l": 20, "gravity_plato": 12, "pitch_rate_m_per_ml_per_p": 0},
        {"volume_l": 20, "gravity_plato": 50, "pitch_rate_m_per_ml_per_p": 1},
        {"volume_l": 20, "gravity_plato": 12, "pitch_rate_m_per_ml_per_p": 1, "pack_billion": 0},
    ],
    "keg_fill": [
        {"available_l": 1000, "keg_size_l": 0, "fill_loss_pct": 2},
        {"available_l": 0, "keg_size_l": 50},
        {"available_l": 1000, "keg_size_l": 50, "fill_loss_pct": 80},
    ],
}

DISCLAIMER_KEYWORD = {
    "lal": "operational",
    "standard_drinks": "verify",
    "abv_abw": "measured",
    "gravity_convert": "approximation",
    "abv_from_og_fg": "approximation",
    "tank_volume": "nominal",
    "yield_loss": "estimate",
    "yeast_pitch": "viability",
    "keg_fill": "estimate",
}


# ── AC15: shared constants ─────────────────────────────────────────────────────


def test_ac15_constants_single_source():
    from app.features.compliant.modules.nz_alcohol import constants

    assert constants.ETHANOL_DENSITY_20C_G_PER_ML == 0.78924
    assert constants.NZ_STANDARD_DRINK_GRAMS_ETHANOL == 10.0
    # Neither NZ-specific constant may be re-typed as a literal in a calculator module —
    # it must be imported from the shared constants module.
    banned = ("0.78924", "= 10.0", "=10.0")
    for path in _SOLVER_DIR.glob("*.py"):
        src = path.read_text()
        for literal in banned:
            assert literal not in src, f"{path.name} hard-codes {literal!r} instead of importing the constant"
        if "NZ_STANDARD_DRINK_GRAMS_ETHANOL" in src:
            assert "from app.features.compliant.modules.nz_alcohol.constants import" in src


# ── AC14: solver purity ───────────────────────────────────────────────────────

_IMPORT_ALLOWLIST = {
    "math",
    "decimal",
    "typing",
    "collections.abc",
    "functools",
    "__future__",
    "app.features.compliant.modules.nz_alcohol.constants",
    "app.features.compliant.tools.errors",
    "app.features.compliant.tools.calculators._validate",
}
_IMPORT_FORBIDDEN_PREFIXES = (
    "os",
    "io",
    "pathlib",
    "socket",
    "urllib",
    "subprocess",
    "requests",
    "flask",
    "sqlalchemy",
    "app.core.db",
)


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", sorted(_SOLVER_DIR.glob("*.py")), ids=lambda p: p.name)
def test_ac14_solver_import_allowlist(path):
    for name in _module_imports(path):
        assert name in _IMPORT_ALLOWLIST, f"{path.name} imports disallowed module {name!r}"
        assert not name.startswith(_IMPORT_FORBIDDEN_PREFIXES)


def test_ac14_solvers_do_no_io(monkeypatch):
    import socket
    import subprocess
    import urllib.request

    def _boom(*_a, **_k):
        raise AssertionError("solver attempted I/O")

    monkeypatch.setattr("builtins.open", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    for key in TIER1_KEYS:
        inp, _exp = FIXTURES[key][0]
        result = CALCULATORS[key](json.loads(json.dumps(inp)))
        assert isinstance(result, dict)


# Tables a solve request is allowed to touch: the auth middleware's user+org load and the
# blueprint gate's single feature_subscriptions lookup. Nothing else — no write, no read
# of ANY other table (calculator, compliance, inventory, execution, crm, ...).
_GATE_INFRA_TABLES = ("users", "organisations", "feature_subscriptions")


def _sql_beyond_gate_infra(seen: list[str]) -> list[str]:
    out = []
    for s in seen:
        if s.startswith(("insert", "update", "delete")):
            out.append(f"WRITE: {s[:90]}")
            continue
        if not s.startswith("select"):
            continue
        # a plain read that names no table other than the gate-infra ones is fine
        touches_other = any(tok not in _GATE_INFRA_TABLES for tok in _table_names(s))
        if touches_other:
            out.append(f"READ: {s[:90]}")
    return out


def _table_names(sql: str) -> set[str]:
    import re

    return {m.group(1) for m in re.finditer(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", sql)}


@pytest.mark.parametrize("key", ["dilution", "lal", "yield_loss", "tank_volume", "gravity_convert"])
def test_ac14_solve_route_issues_no_query_beyond_the_gate(subbed_client, key):
    """A solve request runs ONLY the auth middleware's user/org load and the gate's one
    feature_subscriptions lookup — the solver + route touch no other table and never write.
    """
    from sqlalchemy import event

    from app.core.db import engine

    seen: list[str] = []

    def _listen(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()).lower())

    event.listen(engine, "before_cursor_execute", _listen)
    try:
        resp = subbed_client.post(f"/api/compliant/tools/{key}/solve", json=FIXTURES[key][0][0])
    finally:
        event.remove(engine, "before_cursor_execute", _listen)

    assert resp.status_code == 200
    assert any("feature_subscriptions" in s for s in seen), "gate query missing — test wired wrong"
    assert _sql_beyond_gate_infra(seen) == [], _sql_beyond_gate_infra(seen)


# ── AC13: per-calculator fixtures, rejections, disclaimer/sources ──────────────


@pytest.mark.parametrize("key", TIER1_KEYS)
def test_ac13_fixtures(key):
    for inp, expected in FIXTURES[key]:
        result = CALCULATORS[key](dict(inp))
        for field, (value, tol) in expected.items():
            got = result[field]
            if tol == 0:
                assert got == value, f"{key}.{field}: {got!r} != {value!r} (exact)"
            else:
                # absolute tolerance only — no hidden relative component (math.isclose's
                # default rel_tol=1e-9 would let a spec fixture pinned at tol 0.0 through).
                assert abs(got - value) <= tol, f"{key}.{field}: {got} != {value} (tol {tol})"


def test_ac13_extra_pinned_fixture_fields():
    """Two spec fixture assertions that don't fit the {field: (value, tol)} shape."""
    yl = CALCULATORS["yield_loss"](
        {
            "start_volume_l": 1000,
            "steps": [
                {"name": "brewhouse", "loss_pct": 8},
                {"name": "fermentation", "loss_pct": 5},
                {"name": "packaging", "loss_pct": 2},
            ],
        }
    )
    assert yl["per_step"][1] == {"name": "fermentation", "remaining_l": pytest.approx(874.0, abs=1e-6)}
    gc = CALCULATORS["gravity_convert"]({"sg": 1.048})
    assert gc["brix"] == gc["plato"]  # spec: brix is returned equal to plato


@pytest.mark.parametrize("key", [k for k in TIER1_KEYS if k in REJECTIONS])
def test_ac13_rejections(key):
    for bad in REJECTIONS[key]:
        with pytest.raises(CalculatorValidationError):
            CALCULATORS[key](dict(bad))


# Inputs that are individually in-range but whose product/quotient overflows to inf or
# underflows a divisor to 0 mid-calculation. Each MUST raise CalculatorValidationError
# (via @guarded / finalise()) — never an OverflowError/ZeroDivisionError/500 and never an
# `Infinity` in the returned dict. (build-review 2026-08-29.)
_OVERFLOWING_INPUTS = {
    "lal": {"abv_pct": 100, "lal": 1e308},  # lal*100 -> inf
    "standard_drinks": {"solve_for": "volume_ml", "standard_drinks": 1e308, "abv_pct": 5e-324},  # divisor -> 0
    "tank_volume": {"diameter_m": 1e308, "cyl_height_m": 1, "fill_height_m": 1},  # r**2 -> OverflowError
    "yeast_pitch": {"volume_l": 1e308, "gravity_plato": 40, "pitch_rate_m_per_ml_per_p": 5},  # ceil(inf)
    "keg_fill": {"available_l": 1e308, "keg_size_l": 5e-324},  # floor(inf)
}


@pytest.mark.parametrize("key", sorted(_OVERFLOWING_INPUTS))
def test_ac13_overflowing_inputs_raise_validation_error_not_500(key):
    with pytest.raises(CalculatorValidationError):
        CALCULATORS[key](dict(_OVERFLOWING_INPUTS[key]))


@pytest.mark.parametrize("key", sorted(_OVERFLOWING_INPUTS))
def test_ac13_overflowing_inputs_return_400_via_the_route(subbed_client, key):
    r = subbed_client.post(f"/api/compliant/tools/{key}/solve", json=_OVERFLOWING_INPUTS[key])
    assert r.status_code == 400, (key, r.status_code, r.get_data(as_text=True)[:200])
    assert "Traceback" not in r.get_data(as_text=True)
    body = r.get_json()
    assert isinstance(body.get("error"), str) and body["error"]


def test_ac13_finalise_rejects_a_non_finite_result_directly():
    from app.features.compliant.tools.calculators._validate import finalise

    with pytest.raises(CalculatorValidationError):
        finalise({"x": float("inf"), "disclaimer": "d", "sources": ["s"]})
    with pytest.raises(CalculatorValidationError):
        finalise({"per_step": [{"name": "a", "remaining_l": float("nan")}]})
    # a wholly-finite dict passes through unchanged
    ok = {"x": 1.0, "n": 3, "sources": ["s"]}
    assert finalise(ok) is ok


@pytest.mark.parametrize("key", [k for k in TIER1_KEYS if k != "dilution"])
def test_ac13_disclaimer_and_sources(key):
    inp, _exp = FIXTURES[key][0]
    result = CALCULATORS[key](dict(inp))
    disclaimer = result["disclaimer"]
    assert isinstance(disclaimer, str) and len(disclaimer) >= 20
    assert DISCLAIMER_KEYWORD[key] in disclaimer.lower()
    assert isinstance(result["sources"], list) and result["sources"]
    assert all(isinstance(s, str) and s for s in result["sources"])


def test_ac13_dilution_has_no_sources_key():
    inp, _ = FIXTURES["dilution"][0]
    assert "sources" not in CALCULATORS["dilution"](dict(inp))


# ── AC11: catalogue deep-equality with the pinned fixture ─────────────────────


def test_ac11_catalogue_matches_pinned_fixture():
    pinned = json.loads((_REPO_ROOT / "tests" / "fixtures" / "compliant_tools_catalogue.json").read_text())
    assert CATALOGUE == pinned

    by_key = {c["key"]: c for c in CATALOGUE["calculators"]}
    assert sorted(by_key) == sorted(TIER1_KEYS)
    for entry in CATALOGUE["calculators"]:
        assert entry["category"] in {"general", "beer", "wine", "vessel"}
        assert isinstance(entry["sources"], list) and entry["sources"]
        assert entry["solve"] is None or set(entry["solve"]) & {"field", "one_omitted_of", "one_provided_of"}
        for name, d in entry["inputs"].items():
            assert d["type"] in {"number", "integer", "enum", "array", "text"}
            assert "required" in d
            if d["type"] in {"number", "integer", "text"}:
                assert "unit" in d
            if d["type"] == "array":
                assert "item_fields" in d and "min_items" in d and "max_items" in d


def test_ac11_app_and_repo_catalogue_are_json_equal_and_match_appendix_a():
    """The served catalogue, the committed test fixture, and spec Appendix A must all be
    the same JSON document. (JSON-equal, not byte-identical — formatting is not the
    invariant; the field/value content is.)
    """
    import re

    app_json = json.loads((_REPO_ROOT / "app" / "features" / "compliant" / "tools" / "catalogue.json").read_text())
    fixture_json = json.loads((_REPO_ROOT / "tests" / "fixtures" / "compliant_tools_catalogue.json").read_text())
    spec = (_REPO_ROOT / ".agents" / "specs" / "compliant_tools.md").read_text()
    m = re.search(r"## Appendix A.*?```json\n(.*?)\n```", spec, re.S)
    assert m, "Appendix A JSON block not found in the spec"
    appendix_json = json.loads(m.group(1))

    assert app_json == fixture_json == appendix_json
    assert app_json == CATALOGUE  # the module loads the same file the route serves


# ── route-level tests (need a subscribed authed client) ────────────────────────


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        yield app


@pytest.fixture
def subbed_client(db, flask_app):
    org = OrganisationFactory()
    email = f"tools-{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.MEMBER,
        is_active=True,
    )
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.commit()
    c = flask_app.test_client()
    c.environ_base["wsgi.url_scheme"] = "https"
    c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert c.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD}).status_code == 200
    yield c
    from app.core.db.models.feature_subscription import FeatureSubscription

    db.query(FeatureSubscription).filter(FeatureSubscription.org_id == org.id).delete(synchronize_session=False)
    db.commit()


def test_ac11_catalogue_endpoint_serves_pinned(subbed_client):
    body = subbed_client.get("/api/compliant/tools").get_json()
    pinned = json.loads((_REPO_ROOT / "tests" / "fixtures" / "compliant_tools_catalogue.json").read_text())
    assert body == pinned


# ── AC9: dilution relocation parity ──────────────────────────────────────────


def test_ac9_dilution_moved_and_old_url_gone(subbed_client):
    r = subbed_client.post(
        "/api/compliant/tools/dilution/solve",
        json={"solve_for": "final_volume_ml", "starting_abv": 40, "starting_volume_ml": 1000, "final_abv": 20},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["solved_value"] == 2000.0
    assert body["water_to_add_naive_ml"] == 1000.0
    assert set(body) == {
        "solved_field",
        "solved_value",
        "starting_abv",
        "starting_volume_ml",
        "final_abv",
        "final_volume_ml",
        "water_to_add_ml",
        "water_to_add_naive_ml",
        "disclaimer",
    }
    assert subbed_client.post("/api/dilution-calculator/solve", json={}).status_code == 404


def test_ac9_dilution_error_parity(subbed_client):
    r = subbed_client.post("/api/compliant/tools/dilution/solve", json={"solve_for": "final_abv", "starting_abv": 40})
    assert r.status_code == 400
    assert "is required" in r.get_json()["error"]


def test_ac9_package_and_factory_wiring_removed():
    assert not (_REPO_ROOT / "app" / "features" / "dilution_calculator").exists()
    factory = (_REPO_ROOT / "app" / "api" / "app_factory.py").read_text()
    assert "dilution_calculator" not in factory
    assert "create_dilution_calculator_blueprint" not in factory


# ── AC12: dispatch behaviour ─────────────────────────────────────────────────


def test_ac12_unknown_calculator_404(subbed_client):
    r = subbed_client.post("/api/compliant/tools/nope/solve", json={})
    assert r.status_code == 404
    assert r.get_json() == {"error": "unknown calculator"}


def test_ac12_bad_payload_400_no_stack(subbed_client):
    r = subbed_client.post("/api/compliant/tools/lal/solve", json={"volume_l": 1, "abv_pct": 1, "lal": 1})
    assert r.status_code == 400
    assert "error" in r.get_json()
    assert "Traceback" not in r.get_data(as_text=True)
    r = subbed_client.post("/api/compliant/tools/lal/solve", data="not json", content_type="application/json")
    assert r.status_code == 400


def test_ac12_solve_logs_events(subbed_client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="app.features.compliant.routes.tools_routes"):
        subbed_client.post("/api/compliant/tools/lal/solve", json={"volume_l": 100, "abv_pct": 40})
        subbed_client.post("/api/compliant/tools/lal/solve", json={})
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "compliant.tool_solved" in text and "compliant.tool_rejected" in text


# ── AC17: page markup ───────────────────────────────────────────────────────


def test_ac17_tools_page_structure(subbed_client):
    r = subbed_client.get("/compliant/tools")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "tools-render.js" in html
    assert 'href="/compliant"' in html  # subscription-gated Compliant nav present
    for key in TIER1_KEYS:
        assert f'data-calculator="{key}"' in html
    assert html.count("data-result") >= len(TIER1_KEYS)
    # one input/select control per catalogue input field (+ solve_for select, + array item row)
    for entry in CATALOGUE["calculators"]:
        form_start = html.index(f'data-calculator="{entry["key"]}"')
        form_end = html.index("</form>", form_start)
        chunk = html[form_start:form_end]
        expected = 0
        if entry["solve"] and entry["solve"].get("field"):
            expected += 1
        for name, d in entry["inputs"].items():
            expected += len(d["item_fields"]) if d["type"] == "array" else 1
        controls = chunk.count("<input") + chunk.count("<select")
        assert controls == expected, f"{entry['key']}: {controls} controls, expected {expected}"


def test_ac17_tools_page_requires_subscription(db, flask_app):
    org = OrganisationFactory()
    email = f"tools-unsub-{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.MEMBER,
        is_active=True,
    )
    db.commit()
    c = flask_app.test_client()
    c.environ_base["wsgi.url_scheme"] = "https"
    c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    c.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
    assert c.get("/compliant/tools").status_code == 404
