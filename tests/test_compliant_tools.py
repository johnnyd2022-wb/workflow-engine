"""Compliant Tools suite: catalogue, dispatch, calculators, purity, page.

Covers spec .agents/specs/compliant_tools.md AC9-AC17.
"""

from __future__ import annotations

import ast
import json
import math
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
    for path in _SOLVER_DIR.glob("*.py"):
        src = path.read_text()
        assert "0.78924" not in src, f"{path.name} hard-codes the ethanol density literal"


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


# ── AC13: per-calculator fixtures, rejections, disclaimer/sources ──────────────


@pytest.mark.parametrize("key", TIER1_KEYS)
def test_ac13_fixtures(key):
    for inp, expected in FIXTURES[key]:
        result = CALCULATORS[key](dict(inp))
        for field, (value, tol) in expected.items():
            got = result[field]
            if isinstance(value, float):
                assert math.isclose(got, value, abs_tol=tol) or abs(got - value) <= tol, (
                    f"{key}.{field}: {got} != {value} (tol {tol})"
                )
            else:
                assert got == value, f"{key}.{field}: {got} != {value}"


@pytest.mark.parametrize("key", [k for k in TIER1_KEYS if k in REJECTIONS])
def test_ac13_rejections(key):
    for bad in REJECTIONS[key]:
        with pytest.raises(CalculatorValidationError):
            CALCULATORS[key](dict(bad))


# Extreme-but-finite inputs whose product/quotient overflows or underflows a divisor.
# Every one must surface as a CalculatorValidationError (route -> 400), never a 500 or an
# `Infinity` in the JSON body. (build-review 2026-08-29.)
_EXTREME_INPUTS = {
    "lal": {"abv_pct": 100, "lal": 1e308},
    "standard_drinks": {"solve_for": "volume_ml", "standard_drinks": 1e308, "abv_pct": 5e-324},
    "abv_abw": {"abv_pct": 1e308, "solution_sg": 0.9},
    "gravity_convert": {"sg": 1.0000000001},
    "tank_volume": {"diameter_m": 1e308, "cyl_height_m": 1, "fill_height_m": 1},
    "yield_loss": {"start_volume_l": 1e308, "steps": [{"name": "a", "loss_pct": 99}]},
    "yeast_pitch": {"volume_l": 1e308, "gravity_plato": 40, "pitch_rate_m_per_ml_per_p": 5},
    "keg_fill": {"available_l": 1e308, "keg_size_l": 5e-324},
    "abv_from_og_fg": {"og_sg": 1.2, "fg_sg": 0.98},
}


@pytest.mark.parametrize("key", [k for k in TIER1_KEYS if k in _EXTREME_INPUTS])
def test_ac13_extreme_finite_inputs_are_rejected_not_crashed(key):
    try:
        result = CALCULATORS[key](dict(_EXTREME_INPUTS[key]))
    except CalculatorValidationError:
        return  # rejected at the door or by finalise() — good
    # If it did return, every numeric value must be finite (no Infinity leaking to JSON).
    for v in result.values():
        assert not (isinstance(v, float) and (v != v or v in (float("inf"), float("-inf")))), (
            f"{key} returned non-finite {v!r} for extreme input"
        )


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


def test_ac11_app_and_repo_catalogue_files_identical():
    a = (_REPO_ROOT / "app" / "features" / "compliant" / "tools" / "catalogue.json").read_text()
    b = (_REPO_ROOT / "tests" / "fixtures" / "compliant_tools_catalogue.json").read_text()
    assert json.loads(a) == json.loads(b)


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
