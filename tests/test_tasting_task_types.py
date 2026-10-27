"""Typed task creation, lifecycle protection and subscription isolation on real PostgreSQL."""

from uuid import UUID

import pytest
from sqlalchemy import text

from app.core.backend.tasks import list_tasks as core_list_tasks
from app.features.crm.models.crm_task import CRMTask
from app.features.crm.services.crm_service import CRMService
from app.features.tastings.models import Tasting
from tests.test_tastings import payload
from tests.test_tastings import world as base_world


@pytest.fixture
def world(db):
    return base_world.__wrapped__(db)


@pytest.fixture
def typed_client(db, world):
    from app.api.app_factory import create_app
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.features.compliant.models.compliance_profile import ComplianceProfile
    from tests.factories import DEFAULT_TEST_PASSWORD

    org, rep, *_ = world
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.add(ComplianceProfile(org_id=org.id, enabled=True, industry_module="nz_alcohol"))
    db.commit()
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    client = app.test_client()
    client.environ_base.update(wsgi_url_scheme="https", HTTP_X_FORWARDED_PROTO="https")
    response = client.post("/auth/login", json={"email": rep.email, "password": DEFAULT_TEST_PASSWORD})
    assert response.status_code == 200
    return client


def test_ac1_simple_types_persist_and_update(db, world):
    org, rep, *_ = world
    service = CRMService(db)
    for kind in ("general", "call", "email"):
        row = service.create_task(org.id, {"title": kind, "task_type": kind}, rep.id)
        assert row["task_type"] == kind
        assert db.get(CRMTask, UUID(row["id"])).task_type == kind
    default = service.create_task(org.id, {"title": "old client without type"}, rep.id)
    assert default["task_type"] == "general"
    changed = service.update_task(UUID(default["id"]), org.id, {"task_type": "call"})
    assert changed["task_type"] == "call"


@pytest.mark.parametrize("kind", ["tasting", "bogus", {"type": "tasting"}, None])
def test_ac1_generic_service_rejects_forged_types(db, world, kind):
    org, rep, *_ = world
    with pytest.raises(ValueError):
        CRMService(db).create_task(org.id, {"title": "invalid", "task_type": kind}, rep.id)
    assert db.query(CRMTask).filter(CRMTask.org_id == org.id).count() == 0


def test_ac4_unified_creation_is_one_typed_task_and_event(db, world, typed_client):
    org, rep, item, *_ = world
    response = typed_client.post("/api/crm/tasks", json={"task_type": "tasting", "tasting": payload(rep, item)})
    assert response.status_code == 201, response.get_json()
    data = response.get_json()
    assert data["task"]["task_type"] == "tasting"
    assert data["task"]["id"] == data["tasting"]["task_id"]
    assert data["task"]["tasting_id"] == data["tasting"]["id"]
    assert data["task"]["href"] == "/crm/tasks?task_id=" + data["task"]["id"]
    assert db.query(CRMTask).filter(CRMTask.org_id == org.id).count() == 1
    assert db.query(Tasting).filter(Tasting.org_id == org.id).count() == 1
    assert (
        typed_client.put(
            "/api/crm/tasks/" + data["task"]["id"], json={"task_type": "general", "status": "completed"}
        ).status_code
        == 400
    )
    assert typed_client.delete("/api/crm/tasks/" + data["task"]["id"]).status_code == 409
    db.expire_all()
    assert db.get(CRMTask, UUID(data["task"]["id"])).status == "pending"
    redirect = typed_client.get("/crm/tastings?tasting_id=" + data["tasting"]["id"])
    assert redirect.status_code == 302 and redirect.location.endswith(data["task"]["href"])


def test_ac4_invalid_specialized_creation_leaves_no_partial_task(db, world, typed_client):
    org, rep, item, *_ = world
    broken = payload(rep, item)
    broken["ends_at"] = broken["starts_at"]
    response = typed_client.post("/api/crm/tasks", json={"task_type": "tasting", "tasting": broken})
    assert response.status_code == 400
    assert db.query(CRMTask).filter(CRMTask.org_id == org.id).count() == 0
    assert db.query(Tasting).filter(Tasting.org_id == org.id).count() == 0


def test_ac1_lapse_hides_specialized_tasks_from_crm_core_and_direct_read(db, world, typed_client):
    from app.features.compliant.models.compliance_profile import ComplianceProfile

    org, rep, item, *_ = world
    data = typed_client.post("/api/crm/tasks", json={"task_type": "tasting", "tasting": payload(rep, item)}).get_json()
    task_id = data["task"]["id"]
    regular = CRMService(db).create_task(org.id, {"title": "keep ordinary work"}, rep.id)
    # Assert the specialized record was visible first: a no-op empty reader cannot pass.
    assert task_id in {t["id"] for t in CRMService(db).list_tasks(org.id)}
    profile = db.query(ComplianceProfile).filter_by(org_id=org.id).one()
    profile.enabled = False
    db.commit()
    assert {t["id"] for t in CRMService(db).list_tasks(org.id)} == {regular["id"]}
    assert task_id not in {t["id"] for t in core_list_tasks(db, org.id)}
    assert typed_client.get("/api/crm/tasks/" + task_id).status_code == 404
    assert typed_client.get("/api/crm/tastings/" + data["tasting"]["id"]).status_code == 404
    assert (
        typed_client.post("/api/crm/tasks", json={"task_type": "tasting", "tasting": payload(rep, item)}).status_code
        == 404
    )
    html = typed_client.get("/crm/tasks").get_data(as_text=True)
    assert '<option value="tasting"' not in html
    assert "data-tastings-root" not in html
    assert db.query(Tasting).filter(Tasting.org_id == org.id).count() == 1


def test_ac1_database_rejects_unknown_type(db, world):
    from sqlalchemy.exc import IntegrityError

    org, rep, *_ = world
    task = CRMTask(org_id=org.id, title="DB constraint", task_type="general")
    db.add(task)
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE crm_tasks SET task_type = 'unsupported' WHERE id = :id"), {"id": task.id})
        db.commit()
    db.rollback()
