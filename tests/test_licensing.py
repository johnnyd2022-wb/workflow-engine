"""Plan item 2.5: liquor licensing register, reminders, checks, log and inspector pack."""

from datetime import date, timedelta

import pytest

from app.core.db.models.organisation import Organisation
from app.features.compliant.models import ComplianceRecord
from app.features.compliant.models.licensing import LicensingLogEntry, LiquorLicence, ManagerCertificate
from app.features.compliant.modules.nz_alcohol import licensing
from app.features.compliant.modules.nz_alcohol.module import run_licensing_check
from app.features.compliant.modules.nz_alcohol.nz_calendar import easter_sunday, is_working_day, working_days_before
from app.features.compliant.service import ComplianceService
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

TODAY = date.today()


# --- working days as the Act counts them ------------------------------------------------------


def test_working_days_follow_section_5():
    assert easter_sunday(2026) == date(2026, 4, 5) and easter_sunday(2027) == date(2027, 3, 28)
    for holiday in (
        date(2026, 2, 6),  # Waitangi Day
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 6),  # Easter Monday
        date(2026, 4, 27),  # Anzac Day (Saturday) Mondayised
        date(2026, 6, 1),  # Sovereign's birthday
        date(2026, 7, 10),  # Matariki
        date(2026, 10, 26),  # Labour Day
        date(2026, 12, 21),  # 20 Dec - 15 Jan
        date(2027, 1, 15),
    ):
        assert not is_working_day(holiday), holiday
    assert is_working_day(date(2027, 1, 18)) and is_working_day(date(2026, 12, 18))
    assert is_working_day(date(2026, 1, 20))  # Wellington Anniversary isn't excluded by the Act


@pytest.mark.parametrize(
    ("expires", "file_by"),
    [
        (date(2026, 11, 30), date(2026, 10, 30)),  # 20 working days: 2-27 Nov
        (date(2027, 1, 29), date(2026, 12, 3)),  # the Christmas period doesn't count
        (date(2026, 11, 20), date(2026, 10, 21)),  # Labour Day (26 Oct) does not count
    ],
)
def test_renewal_must_be_filed_20_working_days_before_expiry(expires, file_by):
    assert working_days_before(expires, 20) == file_by


# --- the register against a real tenant ----------------------------------------------------------


@pytest.fixture
def world(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    client.put(
        "/api/compliant/profile",
        json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"], "liquor_licence_types": ["off"]}},
    )
    yield {"org": org, "client": client, "db": db}
    db.rollback()
    for model in (LicensingLogEntry, ManagerCertificate, LiquorLicence, ComplianceRecord):
        db.query(model).filter(model.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def _licence(client, **extra):
    body = {
        "kind": "off",
        "licence_number": "31/OFF/123/2026",
        "issuing_dlc": "Hutt City DLC",
        "premises": "Unit 15, 7 Tunnel Grove",
        "endorsements": ["s40_remote_sales"],
        "issued_on": (TODAY - timedelta(days=300)).isoformat(),
        "expires_on": (TODAY + timedelta(days=70)).isoformat(),
        "delivery_hours_start": "07:00",
        "delivery_hours_end": "23:00",
        **extra,
    }
    return client.post("/api/compliant/licensing/licences", json=body)


def _alert_ids(world):
    result = run_licensing_check(world["org"].id, world["db"])
    return [a["id"] for a in result.data.get("system_alerts", [])]


def test_licence_renewal_reminder_until_lodged_and_granted(world):
    client = world["client"]
    resp = _licence(client)
    assert resp.status_code == 201, resp.get_json()
    (lic,) = resp.get_json()["licences"]
    assert lic["kind_label"] == "Off-licence" and lic["endorsement_labels"] == ["Remote sales (s 40)"]
    expires = date.fromisoformat(lic["expires_on"])
    assert lic["renewal_file_by"] == working_days_before(expires, 20).isoformat()
    assert lic["state_code"] == "due"  # the file-by date is within 60 days
    assert any(a.startswith("licence-renewal-") for a in _alert_ids(world))

    lodged = client.post(f"/api/compliant/licensing/licences/{lic['id']}/renewal-lodged", json={})
    assert lodged.get_json()["licences"][0]["state_code"] == "ok"
    assert not any(a.startswith("licence-renewal-") for a in _alert_ids(world))

    too_soon = client.post(
        f"/api/compliant/licensing/licences/{lic['id']}/renewed", json={"expires_on": lic["expires_on"]}
    )
    assert too_soon.status_code == 400
    granted = client.post(
        f"/api/compliant/licensing/licences/{lic['id']}/renewed",
        json={"expires_on": (expires + timedelta(days=3 * 365)).isoformat()},
    )
    lic = granted.get_json()["licences"][0]
    assert lic["renewal_lodged_on"] is None and lic["state_code"] == "ok"


def test_late_and_expired_licences(world):
    client, db = world["client"], world["db"]
    late = _licence(client, expires_on=(TODAY + timedelta(days=10)).isoformat()).get_json()["licences"][0]
    assert late["state_code"] == "late" and "waiver" in late["state_label"]
    expired = LiquorLicence(
        org_id=world["org"].id, kind="on", endorsements=[], expires_on=TODAY - timedelta(days=1), licence_number="X"
    )
    db.add(expired)
    db.commit()
    body = client.get("/api/compliant/licensing").get_json()
    gone = next(x for x in body["licences"] if x["licence_number"] == "X")
    assert gone["state_code"] == "expired"
    refused = client.post(f"/api/compliant/licensing/licences/{gone['id']}/renewal-lodged", json={})
    assert refused.status_code == 400 and "expired" in refused.get_json()["error"]
    # The register proves the licence-renewal check, and says when it's lapsed.
    frameworks = ComplianceService(db).evaluate(world["org"].id)
    controls = {c["control_id"]: c for f in frameworks if f["slug"] == "liquor-licence" for c in f["controls"]}
    assert controls["licence-scope"]["state"] == "compliant"
    assert controls["licence-renewal"]["state"] == "attention"


def test_annual_fee_and_validation(world):
    client = world["client"]
    assert _licence(client, kind="bogus").status_code == 400
    assert _licence(client, expires_on=None).status_code == 400
    assert _licence(client, delivery_hours_end=None).status_code == 400
    lic = _licence(client, annual_fee_due_on=(TODAY + timedelta(days=20)).isoformat()).get_json()["licences"][0]
    assert any(a.startswith("licence-fee-") for a in _alert_ids(world))
    paid = client.post(f"/api/compliant/licensing/licences/{lic['id']}/fee-paid").get_json()["licences"][0]
    assert date.fromisoformat(paid["annual_fee_due_on"]) > TODAY + timedelta(days=300)
    assert not any(a.startswith("licence-fee-") for a in _alert_ids(world))


def test_special_licence_needs_its_event_and_a_manager_on_duty(world):
    client = world["client"]
    assert client.post("/api/compliant/licensing/licences", json={"kind": "special"}).status_code == 400
    resp = client.post(
        "/api/compliant/licensing/licences",
        json={
            "kind": "special",
            "event_name": "Wellington Gin Fest",
            "event_starts_on": (TODAY + timedelta(days=5)).isoformat(),
        },
    )
    lic = resp.get_json()["licences"][0]
    assert lic["state_code"] == "attention" and lic["event_ends_on"] == lic["event_starts_on"]
    assert f"special-licence-manager-{lic['id']}" in _alert_ids(world)
    named = client.put(f"/api/compliant/licensing/licences/{lic['id']}", json={"manager_on_duty": "Johnny"})
    assert named.get_json()["licences"][0]["state_code"] == "ok"
    assert client.post(f"/api/compliant/licensing/licences/{lic['id']}/renewal-lodged", json={}).status_code == 400


def test_manager_certificates(world, db, flask_app):  # noqa: F811
    client = world["client"]
    staff_id = client.get("/api/compliant/licensing").get_json()["staff"][0]["id"]
    resp = client.post(
        "/api/compliant/licensing/managers",
        json={
            "user_id": staff_id,
            "certificate_number": "31/CERT/77/2026",
            "expires_on": (TODAY + timedelta(days=30)).isoformat(),
        },
    )
    assert resp.status_code == 201, resp.get_json()
    (cert,) = resp.get_json()["managers"]
    assert cert["state_code"] == "due" and cert["holder_name"]
    assert any(a.startswith("manager-certificate-") for a in _alert_ids(world))
    assert client.post(f"/api/compliant/licensing/managers/{cert['id']}/renewal-lodged", json={}).status_code == 200
    assert not any(a.startswith("manager-certificate-") for a in _alert_ids(world))
    assert client.post("/api/compliant/licensing/managers", json={"certificate_number": "1"}).status_code == 400

    other_org, other = _admin_client(db, flask_app)
    try:
        stranger = other.get("/api/compliant/licensing")
        # a user from another org can't be a holder here, and can't touch this org's rows
        other_staff = stranger.get_json()["staff"][0]["id"] if stranger.status_code == 200 else None
        if other_staff:
            bad = client.post(
                "/api/compliant/licensing/managers",
                json={"user_id": other_staff, "certificate_number": "2", "expires_on": TODAY.isoformat()},
            )
            assert bad.status_code == 400
        assert other.put(f"/api/compliant/licensing/managers/{cert['id']}", json={"holder_name": "x"}).status_code in (
            404,
            409,
        )
    finally:
        clear_org_synthetic_data(db, other_org.id)
        db.query(Organisation).filter(Organisation.id == other_org.id).delete(synchronize_session=False)
        db.commit()


def test_log_checks_and_the_inspector_pack(world):
    client = world["client"]
    assert client.post("/api/compliant/licensing/log", json={"kind": "id_refusal"}).status_code == 400
    future = (TODAY + timedelta(days=2)).isoformat() + "T10:00:00+13:00"
    assert (
        client.post(
            "/api/compliant/licensing/log", json={"kind": "incident", "description": "x", "occurred_at": future}
        ).status_code
        == 400
    )
    logged = client.post(
        "/api/compliant/licensing/log",
        json={
            "kind": "id_refusal",
            "description": "Online order, no ID at delivery",
            "location": "Online order",
            "action_taken": "Returned to store",
        },
    )
    assert logged.status_code == 201 and logged.get_json()["log"][0]["kind_label"].startswith("Refused")

    record = client.post(
        "/api/compliant/records",
        json={
            "framework_slug": "liquor-licence",
            "control_id": "licence-displayed",
            "record_type": "attestation",
            "title": "Licence and duty manager sign at the cellar door",
            "evidence_reference": "photo-2026-09.jpg",
            "due_date": (TODAY + timedelta(days=10)).isoformat(),
        },
    )
    assert record.status_code == 201, record.get_json()
    checks = {c["control_id"]: c for c in client.get("/api/compliant/licensing").get_json()["checks"]}
    assert checks["licence-displayed"]["state"] == "due"  # review within 30 days
    assert checks["responsibility-policy"]["state"] == "missing"
    assert checks["licence-scope"]["from_register"] is True and checks["licence-scope"]["state"] == "setup"
    assert any(a.startswith("licensing-check-licence-displayed") for a in _alert_ids(world))

    _licence(client)
    pack = client.get("/api/compliant/licensing/pack.pdf")
    assert pack.status_code == 200 and pack.mimetype == "application/pdf" and pack.data[:4] == b"%PDF"

    page = client.get("/compliant/nz-alcohol/licensing")
    assert page.status_code == 200 and b"data-licensing-root" in page.data
    assert b'href="/compliant/nz-alcohol/licensing" hidden' not in client.get("/compliant/nz-alcohol").data


def test_state_helpers_directly():
    lic = LiquorLicence(kind="off", status="current", endorsements=[], expires_on=date(2026, 11, 30))
    assert licensing.licence_state(lic, date(2026, 8, 1))["state"] == "ok"
    assert licensing.licence_state(lic, date(2026, 9, 1))["state"] == "due"
    assert licensing.licence_state(lic, date(2026, 10, 31))["state"] == "late"
    assert licensing.licence_state(lic, date(2026, 12, 1))["state"] == "expired"
    lic.renewal_lodged_on = date(2026, 10, 1)
    assert "continues" in licensing.licence_state(lic, date(2026, 12, 1))["label"]
