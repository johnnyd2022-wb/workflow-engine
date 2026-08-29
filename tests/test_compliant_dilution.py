"""Tests for the relocated dilution calculator (now Compliant Tools).

The dilution solver moved verbatim from app/features/dilution_calculator/ into
app/features/compliant/tools/calculators/dilution.py and its API from
POST /api/dilution-calculator/solve to POST /api/compliant/tools/dilution/solve, gated by
the per-org Compliant subscription. Maths, validation, error strings and payload are
unchanged — every assertion below is the migrated one (spec compliant_tools.md AC9).

Coverage:
  - solver: the exact (a,b,c,d) identity, water_to_add contraction model, validation,
    determinism (AC1-AC5, AC7-AC9 of the original dilution_calculator spec)
  - API endpoint at the new path: happy path, validation errors, auth + subscription gate
  - the old /dilution-calculator page/API URLs are gone (404)

See .agents/specs/dilution_calculator.md for the original AC definitions.
"""

from __future__ import annotations

import logging
import math
from uuid import uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.compliant.tools.calculators.dilution import (
    DilutionValidationError,
    _mass_fraction_for_abv,
    solve_dilution,
)


class _LogRecordCollector(logging.Handler):
    """Collects raw LogRecords for direct inspection of the structlog event dict
    (`record.msg`), bypassing stdout/renderer capture entirely — see
    test_ac4_endpoint_logs_rejection_event_on_validation_failure for why: the app
    factory's own logging setup (root handlers bound during app_client fixture setup)
    doesn't interact reliably with pytest's capsys/capfd fd-swap timing.
    """

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


# ─────────────────────────────────────────────
# Service-level tests (pure computation, no Flask/DB)
# ─────────────────────────────────────────────


class TestDilutionServiceHappyPath:
    def test_ac1_response_shape(self):
        result = solve_dilution(
            {
                "solve_for": "final_volume_ml",
                "starting_abv": 40,
                "starting_volume_ml": 1000,
                "final_abv": 20,
                "final_volume_ml": None,
            }
        )
        assert set(result.keys()) == {
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
        assert result["solved_field"] == "final_volume_ml"

    def test_ac2_exact_identity_matches_naive_pearson_square(self):
        """The (a,b,c,d) relation is exact — solving final_volume_ml from the brief's own
        example must equal naive C1V1=C2V2 (2000mL), NOT a contraction-perturbed figure.
        A wrong reintroduction of a density model into this solve would break this test.
        """
        result = solve_dilution(
            {
                "solve_for": "final_volume_ml",
                "starting_abv": 40,
                "starting_volume_ml": 1000,
                "final_abv": 20,
                "final_volume_ml": None,
            }
        )
        assert result["solved_value"] == pytest.approx(2000.0, abs=1e-6)

    def test_ac2_water_to_add_is_contraction_aware_and_exceeds_naive(self):
        """This is where contraction actually shows up: more water (measured on its own)
        is needed than the naive additive assumption to reach the same actual final state.
        """
        result = solve_dilution(
            {
                "solve_for": "final_volume_ml",
                "starting_abv": 40,
                "starting_volume_ml": 1000,
                "final_abv": 20,
                "final_volume_ml": None,
            }
        )
        assert result["water_to_add_naive_ml"] == pytest.approx(1000.0, abs=1e-6)
        assert result["water_to_add_ml"] > result["water_to_add_naive_ml"]

    def test_ac3_round_trip_final_volume_then_final_abv(self):
        step1 = solve_dilution(
            {"solve_for": "final_volume_ml", "starting_abv": 40, "starting_volume_ml": 1000, "final_abv": 20}
        )
        step2 = solve_dilution(
            {
                "solve_for": "final_abv",
                "starting_abv": 40,
                "starting_volume_ml": 1000,
                "final_volume_ml": step1["solved_value"],
            }
        )
        assert step2["solved_value"] == pytest.approx(20.0, abs=1e-6)

    def test_ac3_round_trip_starting_volume_then_starting_abv(self):
        step1 = solve_dilution(
            {"solve_for": "starting_volume_ml", "starting_abv": 40, "final_abv": 20, "final_volume_ml": 2000}
        )
        step2 = solve_dilution(
            {
                "solve_for": "starting_abv",
                "starting_volume_ml": step1["solved_value"],
                "final_abv": 20,
                "final_volume_ml": 2000,
            }
        )
        assert step2["solved_value"] == pytest.approx(40.0, abs=1e-6)

    @pytest.mark.parametrize(
        "solve_for",
        ["starting_abv", "starting_volume_ml", "final_abv", "final_volume_ml"],
    )
    def test_ac1_all_four_scenarios_solvable(self, solve_for):
        base = {"starting_abv": 45.0, "starting_volume_ml": 500.0, "final_abv": 15.0, "final_volume_ml": 1500.0}
        payload = {k: v for k, v in base.items()}
        payload[solve_for] = None
        payload["solve_for"] = solve_for
        result = solve_dilution(payload)
        # exact identity must hold for the fully resolved quadruple, regardless of which
        # field was the unknown
        assert result["starting_abv"] * result["starting_volume_ml"] == pytest.approx(
            result["final_abv"] * result["final_volume_ml"], rel=1e-9
        )

    def test_ac4_starting_abv_of_100_is_a_valid_given_value(self):
        """AC4 allows ABV in the closed range [0, 100] for *given* values, not just
        solved ones — starting_abv=100 must be accepted, not rejected by validation
        (pure ethanol diluted down to a lower final_abv is a legal request).
        """
        result = solve_dilution(
            {
                "solve_for": "final_volume_ml",
                "starting_abv": 100.0,
                "starting_volume_ml": 500,
                "final_abv": 50,
            }
        )
        assert result["starting_abv"] == 100.0

    def test_mass_fraction_for_abv_100_boundary_is_exact_pure_ethanol(self):
        """_mass_fraction_for_abv's abv_pct >= 100.0 fast path must return exactly w=1.0
        (pure ethanol), not run the bisection or return some other value — a wrong
        constant here wouldn't be caught by a solve_dilution-level test alone, since
        starting_abv is an echoed input and water_to_add_ml stays finite regardless of
        which mass fraction feeds it.
        """
        assert _mass_fraction_for_abv(100.0) == 1.0
        assert _mass_fraction_for_abv(150.0) == 1.0


class TestDilutionServiceValidation:
    def test_ac4_rejects_missing_solve_for(self):
        with pytest.raises(DilutionValidationError, match="solve_for"):
            solve_dilution({"starting_abv": 40, "starting_volume_ml": 1000, "final_abv": 20})

    def test_ac4_rejects_non_string_solve_for(self):
        """build-review finding: a list/dict solve_for must not crash on the frozenset
        membership test — it must be rejected as a normal 400-worthy validation error.
        """
        with pytest.raises(DilutionValidationError, match="solve_for"):
            solve_dilution(
                {
                    "solve_for": ["final_volume_ml"],
                    "starting_abv": 40,
                    "starting_volume_ml": 1000,
                    "final_abv": 20,
                }
            )

    def test_ac4_rejects_overflow_to_infinite_solved_value(self):
        """build-review finding: an extreme-but-finite input that overflows the division
        to inf must be rejected, not silently pass the `> 0` volume check (inf > 0 is
        True in Python).
        """
        with pytest.raises(DilutionValidationError, match="non-finite"):
            solve_dilution(
                {
                    "solve_for": "final_volume_ml",
                    "starting_abv": 100,
                    "starting_volume_ml": 1.5e308,
                    "final_abv": 1e-300,
                }
            )

    def test_ac4_rejects_invalid_solve_for_value(self):
        with pytest.raises(DilutionValidationError, match="solve_for"):
            solve_dilution(
                {
                    "solve_for": "temperature",
                    "starting_abv": 40,
                    "starting_volume_ml": 1000,
                    "final_abv": 20,
                }
            )

    def test_ac4_rejects_solve_for_field_present(self):
        with pytest.raises(DilutionValidationError, match="omitted or null"):
            solve_dilution(
                {
                    "solve_for": "final_volume_ml",
                    "starting_abv": 40,
                    "starting_volume_ml": 1000,
                    "final_abv": 20,
                    "final_volume_ml": 9999,
                }
            )

    def test_ac4_rejects_missing_required_field(self):
        with pytest.raises(DilutionValidationError, match="starting_volume_ml"):
            solve_dilution({"solve_for": "final_volume_ml", "starting_abv": 40, "final_abv": 20})

    def test_ac4_rejects_non_numeric_field(self):
        with pytest.raises(DilutionValidationError, match="finite number"):
            solve_dilution(
                {
                    "solve_for": "final_volume_ml",
                    "starting_abv": "forty",
                    "starting_volume_ml": 1000,
                    "final_abv": 20,
                }
            )

    def test_ac4_rejects_nan_field(self):
        with pytest.raises(DilutionValidationError, match="finite number"):
            solve_dilution(
                {
                    "solve_for": "final_volume_ml",
                    "starting_abv": math.nan,
                    "starting_volume_ml": 1000,
                    "final_abv": 20,
                }
            )

    def test_ac4_rejects_abv_out_of_range(self):
        with pytest.raises(DilutionValidationError, match="between 0 and 100"):
            solve_dilution(
                {
                    "solve_for": "final_volume_ml",
                    "starting_abv": 140,
                    "starting_volume_ml": 1000,
                    "final_abv": 20,
                }
            )

    def test_ac4_rejects_non_positive_volume(self):
        with pytest.raises(DilutionValidationError, match="greater than 0"):
            solve_dilution(
                {
                    "solve_for": "final_volume_ml",
                    "starting_abv": 40,
                    "starting_volume_ml": 0,
                    "final_abv": 20,
                }
            )

    def test_ac5_rejects_final_abv_not_less_than_starting_abv(self):
        with pytest.raises(DilutionValidationError, match="final_abv must be less than starting_abv"):
            solve_dilution(
                {
                    "solve_for": "final_volume_ml",
                    "starting_abv": 20,
                    "starting_volume_ml": 1000,
                    "final_abv": 40,
                }
            )

    def test_ac5_rejects_shrinking_volume_when_solving_abv_field(self):
        with pytest.raises(DilutionValidationError, match="final_volume_ml must be greater than starting_volume_ml"):
            solve_dilution(
                {
                    "solve_for": "final_abv",
                    "starting_abv": 40,
                    "starting_volume_ml": 1000,
                    "final_volume_ml": 500,
                }
            )

    def test_ac5_divisor_guard_final_abv_zero_does_not_crash(self):
        """Round-2 spec-critic finding: final_abv=0 passes the `final_abv < starting_abv`
        pair check but is the divisor for solving final_volume_ml — must be rejected with
        a clear error, not raise ZeroDivisionError.
        """
        with pytest.raises(DilutionValidationError, match="greater than 0"):
            solve_dilution(
                {
                    "solve_for": "final_volume_ml",
                    "starting_abv": 40,
                    "starting_volume_ml": 1000,
                    "final_abv": 0,
                }
            )

    def test_ac5_diluting_water_with_water_is_allowed(self):
        """starting_abv computed as 0 (given final_abv=0, final_volume_ml > starting_volume_ml)
        is a degenerate but valid case per the spec, not specially rejected.
        """
        result = solve_dilution(
            {
                "solve_for": "starting_abv",
                "starting_volume_ml": 500,
                "final_abv": 0,
                "final_volume_ml": 1000,
            }
        )
        assert result["solved_value"] == pytest.approx(0.0, abs=1e-9)

    def test_ac4_rejects_non_dict_payload_direct_call(self):
        """The HTTP route already 400s a non-dict body before calling solve_dilution
        (test_ac4_endpoint_rejects_non_object_body below), so that path never reaches
        this guard. It's still a real defensive check in solve_dilution's own contract
        for any direct/non-HTTP caller — exercise it directly.
        """
        with pytest.raises(DilutionValidationError, match="JSON object"):
            solve_dilution([1, 2, 3])

    def test_ac5_post_solve_starting_abv_over_100_is_rejected(self):
        """AC5's pre-solve pair check (final_volume_ml > starting_volume_ml) doesn't by
        itself bound the solved starting_abv — a large enough final/starting volume
        ratio still pushes the closed-form result past 100, which only the post-solve
        guard catches (90 * 2000 / 100 = 1800).
        """
        with pytest.raises(DilutionValidationError, match="outside 0-100"):
            solve_dilution(
                {
                    "solve_for": "starting_abv",
                    "starting_volume_ml": 100,
                    "final_abv": 90,
                    "final_volume_ml": 2000,
                }
            )

    def test_ac5_post_solve_starting_volume_non_positive_is_rejected(self):
        """final_abv=0.0 is a legal boundary value (AC4) and passes the AC5 pre-check for
        this direction (0 < starting_abv), but the closed-form solve for
        starting_volume_ml then divides through to exactly 0 — the post-solve guard must
        reject that rather than silently return a 0 mL volume.
        """
        with pytest.raises(DilutionValidationError, match="non-positive volume"):
            solve_dilution(
                {
                    "solve_for": "starting_volume_ml",
                    "starting_abv": 40,
                    "final_abv": 0,
                    "final_volume_ml": 1000,
                }
            )


class TestDilutionServiceDeterminism:
    def test_ac7_repeated_calls_are_byte_identical(self):
        payload = {
            "solve_for": "final_volume_ml",
            "starting_abv": 37.5,
            "starting_volume_ml": 750,
            "final_abv": 12.3,
        }
        first = solve_dilution(dict(payload))
        second = solve_dilution(dict(payload))
        assert first == second

    def test_ac8_disclaimer_present(self):
        result = solve_dilution(
            {
                "solve_for": "final_volume_ml",
                "starting_abv": 40,
                "starting_volume_ml": 1000,
                "final_abv": 20,
            }
        )
        assert "hydrometer" in result["disclaimer"].lower()
        assert result["water_to_add_ml"] is not None
        assert result["water_to_add_naive_ml"] is not None

    def test_ac9_solved_value_is_not_rounded(self):
        result = solve_dilution(
            {
                "solve_for": "final_abv",
                "starting_abv": 33,
                "starting_volume_ml": 777,
                "final_volume_ml": 1234,
            }
        )
        # 33 * 777 / 1234 has a long decimal tail; a server-side round to e.g. 2dp would
        # truncate it well before float precision does.
        exact = 33 * 777 / 1234
        assert result["solved_value"] == exact


# ─────────────────────────────────────────────
# API / route-level tests
# ─────────────────────────────────────────────


@pytest.fixture()
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture()
def org(db):
    org_repo = OrganisationRepository(db)
    o = org_repo.create_org(f"Dilution Calc Test Org {uuid4()}")
    db.commit()
    yield o
    db.query(Organisation).filter(Organisation.id == o.id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture()
def user(db, org):
    user_repo = UserRepository(db)
    email = f"dilution_calc_test_{uuid4()}@test.com"
    password_hash = AuthService.hash_password("TestPass123!")
    u = user_repo.create_user(org_id=org.id, email=email, password_hash=password_hash)
    # Every Compliant route (including the relocated dilution solve endpoint) is gated
    # on an active per-org subscription.
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.commit()
    return u


@pytest.fixture()
def app_client(db, org, user):
    """Authenticated Flask test client."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            resp = client.post(
                "/auth/login",
                json={"email": user.email, "password": "TestPass123!"},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


class TestDilutionCalculatorAPI:
    def test_ac1_endpoint_solves_and_returns_200(self, app_client):
        resp = app_client.post(
            "/api/compliant/tools/dilution/solve",
            json={
                "solve_for": "final_volume_ml",
                "starting_abv": 40,
                "starting_volume_ml": 1000,
                "final_abv": 20,
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["solved_field"] == "final_volume_ml"
        assert body["solved_value"] == pytest.approx(2000.0, abs=1e-6)

    def test_ac1_endpoint_logs_solved_event_on_success(self, app_client):
        """A successful solve must leave a structured log line behind. The shared tools
        dispatch route logs `compliant.tool_solved` with the calculator key.
        """
        collector = _LogRecordCollector()
        root_logger = logging.getLogger()
        root_logger.addHandler(collector)
        try:
            resp = app_client.post(
                "/api/compliant/tools/dilution/solve",
                json={
                    "solve_for": "final_volume_ml",
                    "starting_abv": 40,
                    "starting_volume_ml": 1000,
                    "final_abv": 20,
                },
            )
        finally:
            root_logger.removeHandler(collector)

        assert resp.status_code == 200

        solved = [
            r.msg
            for r in collector.records
            if isinstance(r.msg, dict) and r.msg.get("event") == "compliant.tool_solved"
        ]
        assert solved, f"Expected a compliant.tool_solved log record, got: {collector.records}"
        assert solved[0]["level"] == "info"
        assert solved[0]["tool"] == "dilution"

    def test_ac4_endpoint_returns_400_with_error_message(self, app_client):
        resp = app_client.post(
            "/api/compliant/tools/dilution/solve",
            json={"solve_for": "final_volume_ml", "starting_abv": 40, "starting_volume_ml": 1000, "final_abv": 900},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_ac4_endpoint_logs_rejection_event_on_validation_failure(self, app_client):
        """A validation 400 must leave a structured log line behind — otherwise a spike
        of rejected requests (e.g. a broken frontend build) would be invisible in the
        logs. Attaches a plain logging.Handler to the root logger for the duration of
        the request and inspects the raw structlog event dict off `record.msg` — this
        is renderer-independent (works whether local.ini's console renderer or
        prod/test.ini's JSON renderer is active) and immune to stdout/fd capture-fixture
        ordering issues against the app factory's own logging setup. Checks the
        event/level/field shape fires; doesn't assert on message wording.
        """
        collector = _LogRecordCollector()
        root_logger = logging.getLogger()
        root_logger.addHandler(collector)
        try:
            resp = app_client.post(
                "/api/compliant/tools/dilution/solve",
                json={
                    "solve_for": "final_volume_ml",
                    "starting_abv": 40,
                    "starting_volume_ml": 1000,
                    "final_abv": 900,
                },
            )
        finally:
            root_logger.removeHandler(collector)

        assert resp.status_code == 400

        rejected = [
            r.msg
            for r in collector.records
            if isinstance(r.msg, dict) and r.msg.get("event") == "compliant.tool_rejected"
        ]
        assert rejected, f"Expected a compliant.tool_rejected log record, got: {collector.records}"
        assert rejected[0]["level"] == "warning"
        assert rejected[0]["tool"] == "dilution"
        assert "reason" in rejected[0]

    def test_ac4_endpoint_rejects_non_object_body(self, app_client):
        resp = app_client.post("/api/compliant/tools/dilution/solve", json=[1, 2, 3])
        assert resp.status_code == 400

    def test_ac7_endpoint_issues_no_write_and_no_query_beyond_the_gate(self, app_client):
        """The solve endpoint is pure. The ONLY SQL a solve request may run is the auth
        middleware's user/org load and the blueprint gate's single feature_subscriptions
        lookup — no write, and no SELECT that names any other table.
        """
        import re

        from sqlalchemy import event

        from app.core.db import engine

        allowed = {"users", "organisations", "feature_subscriptions"}
        offending: list[str] = []
        saw_gate = False

        def _before_cursor(conn, cursor, statement, parameters, context, executemany):
            nonlocal saw_gate
            s = " ".join(statement.split()).lower()
            if "feature_subscriptions" in s:
                saw_gate = True
            if s.startswith(("insert", "update", "delete")):
                offending.append(f"WRITE: {s[:90]}")
            elif s.startswith("select"):
                tables = {m.group(1) for m in re.finditer(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", s)}
                if tables - allowed:
                    offending.append(f"READ: {s[:90]}")

        event.listen(engine, "before_cursor_execute", _before_cursor)
        try:
            resp = app_client.post(
                "/api/compliant/tools/dilution/solve",
                json={
                    "solve_for": "final_volume_ml",
                    "starting_abv": 40,
                    "starting_volume_ml": 1000,
                    "final_abv": 20,
                },
            )
        finally:
            event.remove(engine, "before_cursor_execute", _before_cursor)

        assert resp.status_code == 200
        assert saw_gate, "the feature_subscriptions gate query never ran — test wired wrong"
        assert offending == [], offending


class TestDilutionCalculatorAuth:
    def test_ac6_api_endpoint_requires_auth(self):
        from app.api.app_factory import create_app

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        flask_app.config["WTF_CSRF_ENABLED"] = False
        with flask_app.test_client() as client:
            client.environ_base["wsgi.url_scheme"] = "https"
            client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
            resp = client.post("/api/compliant/tools/dilution/solve", json={"solve_for": "final_volume_ml"})
        assert resp.status_code in (401, 302)

    def test_ac9_old_dilution_urls_are_gone(self, app_client):
        """The standalone /dilution-calculator page and /api/dilution-calculator/solve
        no longer exist — the calculator lives on /compliant/tools now.
        """
        assert app_client.get("/dilution-calculator").status_code == 404
        assert app_client.post("/api/dilution-calculator/solve", json={}).status_code == 404

    def test_ac9_dilution_form_is_on_the_tools_page(self, app_client):
        resp = app_client.get("/compliant/tools")
        assert resp.status_code == 200
        assert b'data-calculator="dilution"' in resp.data
