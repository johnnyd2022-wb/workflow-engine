"""Plan item 2.4b: NP1 and NP2 run on the same verification workspace as NP3."""

import pytest

from app.core.db.models.organisation import Organisation
from app.features.compliant.models import ComplianceRecord
from app.features.compliant.modules.nz_alcohol.catalogue import framework_by_slug
from app.features.compliant.modules.nz_alcohol.module import run_check
from app.features.compliant.modules.nz_alcohol.national_programmes import (
    NP1_AUDIT_CATEGORIES,
    NP2_AUDIT_CATEGORIES,
    topic_ids,
)
from app.features.compliant.modules.nz_alcohol.np3_audit import audit_categories, evidence_playbook
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.test_compliant_routes import _admin_client, flask_app  # noqa: F401 -- fixture re-export

NP2_ONLY = {
    "time-temperature-processing",
    "defrosting-reheating",
    "water-activity-control",
    "acidification-fermentation-control",
}


def test_every_card_is_a_recordable_check_with_a_playbook():
    for slug, categories in (("np1-food-control", NP1_AUDIT_CATEGORIES), ("np2-food-control", NP2_AUDIT_CATEGORIES)):
        controls = dict(framework_by_slug(slug)["controls"])
        for control_id in topic_ids(categories):
            assert control_id in controls, (slug, control_id)
            assert evidence_playbook(control_id), control_id
        # checks recorded before 2.4b stay valid
        assert {"operational-verification", "registration-scope", "staff-competency"} <= set(controls)
    assert NP2_ONLY <= set(topic_ids(NP2_AUDIT_CATEGORIES))
    assert not NP2_ONLY & set(topic_ids(NP1_AUDIT_CATEGORIES))
    assert audit_categories("np1") is NP1_AUDIT_CATEGORIES and audit_categories("np3") is not NP2_AUDIT_CATEGORIES


@pytest.fixture
def np2_org(db, flask_app):  # noqa: F811
    org, client = _admin_client(db, flask_app)
    client.put(
        "/api/compliant/profile",
        json={"enabled": True, "settings": {"alcohol_product_types": ["spirits"], "food_control_programme": "np2"}},
    )
    yield org, client
    db.rollback()
    db.query(ComplianceRecord).filter(ComplianceRecord.org_id == org.id).delete(synchronize_session=False)
    db.commit()
    clear_org_synthetic_data(db, org.id)
    db.query(Organisation).filter(Organisation.id == org.id).delete(synchronize_session=False)
    db.commit()


def test_np2_workspace_register_and_sign_off(np2_org, db):
    org, client = np2_org
    audit = client.get("/api/compliant/np3-audit")
    assert audit.status_code == 200, audit.get_json()
    audit = audit.get_json()
    assert audit["programme"] == "np2" and audit["programme_short"] == "NP2"
    assert audit["guidance_url"].endswith("/21850/direct")
    assert {row["control_id"] for row in audit["rows"]} == set(topic_ids(NP2_AUDIT_CATEGORIES))
    assert [c["title"] for c in audit["categories"]] == [c for c, _ in NP2_AUDIT_CATEGORIES]
    assert all(row["guidance_url"] == audit["guidance_url"] for row in audit["rows"])

    signed = client.post(
        "/api/compliant/np3-audit/attestations",
        json={
            "control_id": "water-activity-control",
            "how_we_meet": "Dried botanicals are bought in sealed packs and stored dry.",
            "confirmed": True,
            "review_interval_months": 12,
        },
    )
    assert signed.status_code == 201, signed.get_json()
    record = db.query(ComplianceRecord).filter(ComplianceRecord.org_id == org.id).one()
    assert record.framework_slug == "np2-food-control" and record.title.startswith("NP2 review:")
    row = next(
        r
        for r in client.get("/api/compliant/np3-audit").get_json()["rows"]
        if r["control_id"] == "water-activity-control"
    )
    assert row["state"] == "ready"

    page = client.get("/compliant/nz-alcohol/food-safety")
    assert (
        page.status_code == 200 and b"NATIONAL PROGRAMME 2" in page.data and b'data-programme-short="NP2"' in page.data
    )
    assert b"data-verification-root" in page.data  # 2.2's verification panel serves NP2 too
    check = client.get("/compliant/nz-alcohol/np3-audit/check/water-activity-control")
    assert check.status_code == 200 and b"NATIONAL PROGRAMME 2 / CHECK DETAIL" in check.data

    summary = run_check(org.id, db).data["workspace_summary"]
    assert summary["module_name"] == "NP2" and summary["action_label"] == "Open NP2"
    assert "milestone" in summary  # 2.2's next-verification line, whichever programme


def test_np1_has_no_process_control_cards(np2_org):
    _org, client = np2_org
    client.put("/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "np1"}})
    audit = client.get("/api/compliant/np3-audit").get_json()
    assert audit["programme"] == "np1"
    assert not NP2_ONLY & {row["control_id"] for row in audit["rows"]}
    wrong = client.post(
        "/api/compliant/np3-audit/attestations",
        json={"control_id": "defrosting-reheating", "how_we_meet": "x", "confirmed": True},
    )
    assert wrong.status_code == 400  # not an NP1 check
    client.put("/api/compliant/profile", json={"enabled": True, "settings": {"food_control_programme": "none"}})
    assert client.get("/compliant/nz-alcohol/food-safety").status_code == 302
