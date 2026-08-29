"""GET /api/core/changes — the polled entity_events change feed (live-sync.js consumes it)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.db.models.organisation import Organisation
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.auth_service import AuthService
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory

PASSWORD = DEFAULT_TEST_PASSWORD
ENDPOINT = "/api/core/changes"


@pytest.fixture
def flask_app():
    from app.api.app_factory import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        yield app


def _org_and_client(db, flask_app):
    org = OrganisationFactory()
    db.commit()
    email = f"user_{uuid4()}@test.com"
    UserRepository(db).create_user(
        org_id=org.id, email=email, password_hash=AuthService.hash_password(PASSWORD), is_active=True
    )
    db.commit()
    client = flask_app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return org, client


@pytest.fixture
def two_orgs(db, flask_app):
    a = _org_and_client(db, flask_app)
    b = _org_and_client(db, flask_app)
    yield a, b
    db.rollback()
    for org, _c in (a, b):
        db.execute(text("DELETE FROM entity_events WHERE org_id = :o"), {"o": str(org.id)})
        db.query(Organisation).filter_by(id=org.id).delete(synchronize_session=False)
    db.commit()


def _emit(db, org_id, event_type, entity_type, entity_id, payload=None, *, created_at=None):
    db.execute(
        text(
            """
            INSERT INTO entity_events (id, org_id, event_type, entity_type, entity_id, actor_type, payload, created_at)
            VALUES (gen_random_uuid(), :o, :et, :ent, :eid, 'system', CAST(:p AS jsonb), :ts)
            """
        ),
        {
            "o": str(org_id),
            "et": event_type,
            "ent": entity_type,
            "eid": str(entity_id),
            "p": __import__("json").dumps(payload or {}),
            "ts": created_at or (datetime.now(UTC) - timedelta(seconds=5)),
        },
    )
    db.commit()


def test_bootstrap_returns_head_cursor_and_no_events(db, two_orgs):
    (org, client), _b = two_orgs
    _emit(db, org.id, "process.created", "process", uuid4())

    body = client.get(ENDPOINT).get_json()
    assert body["events"] == []
    assert body["has_more"] is False
    assert isinstance(body["cursor"], int) and body["cursor"] > 0


def test_since_returns_only_newer_events_in_seq_order(db, two_orgs):
    (org, client), _b = two_orgs
    start = client.get(ENDPOINT).get_json()["cursor"]

    pid = uuid4()
    _emit(db, org.id, "process.created", "process", pid)
    _emit(db, org.id, "execution.created", "execution", uuid4(), {"process_id": str(pid), "execution_id": str(uuid4())})

    body = client.get(f"{ENDPOINT}?since={start}").get_json()
    seqs = [e["seq"] for e in body["events"]]
    assert len(seqs) == 2 and seqs == sorted(seqs) and all(s > start for s in seqs)
    assert {e["event_type"] for e in body["events"]} == {"process.created", "execution.created"}
    assert body["cursor"] == seqs[-1]


def test_feed_is_org_scoped(db, two_orgs):
    (org_a, client_a), (org_b, _client_b) = two_orgs
    start = client_a.get(ENDPOINT).get_json()["cursor"]
    _emit(db, org_b.id, "process.created", "process", uuid4())  # other org

    body = client_a.get(f"{ENDPOINT}?since={start}").get_json()
    assert body["events"] == []


def test_keys_are_extracted_from_payload(db, two_orgs):
    (org, client), _b = two_orgs
    start = client.get(ENDPOINT).get_json()["cursor"]
    pid, eid, sid = uuid4(), uuid4(), uuid4()
    _emit(
        db, org.id, "execution.step_completed", "execution", eid,
        {"execution_id": str(eid), "step_id": str(sid), "process_id": str(pid)},
    )
    iid = uuid4()
    _emit(db, org.id, "inventory_item.created", "inventory_item", iid, {"id": str(iid), "source_execution_id": str(eid)})

    evts = {e["event_type"]: e for e in client.get(f"{ENDPOINT}?since={start}").get_json()["events"]}
    assert evts["execution.step_completed"]["keys"] == {
        "execution_id": str(eid), "step_id": str(sid), "process_id": str(pid),
    }
    assert evts["inventory_item.created"]["keys"]["inventory_item_id"] == str(iid)
    assert evts["inventory_item.created"]["keys"]["source_execution_id"] == str(eid)


def test_non_synced_entity_types_are_hidden(db, two_orgs):
    (org, client), _b = two_orgs
    start = client.get(ENDPOINT).get_json()["cursor"]
    _emit(db, org.id, "user.login", "user", uuid4())  # colleague login times must not leak

    assert client.get(f"{ENDPOINT}?since={start}").get_json()["events"] == []


def test_settle_window_withholds_events_from_the_last_second(db, two_orgs):
    (org, client), _b = two_orgs
    start = client.get(ENDPOINT).get_json()["cursor"]
    _emit(db, org.id, "process.created", "process", uuid4(), created_at=datetime.now(UTC))  # "just now"

    assert client.get(f"{ENDPOINT}?since={start}").get_json()["events"] == []


def test_conditional_get_304_when_caught_up(db, two_orgs):
    (org, client), _b = two_orgs
    head = client.get(ENDPOINT).get_json()["cursor"]
    r = client.get(f"{ENDPOINT}?since={head}", headers={"If-None-Match": f'"{head}"'})
    assert r.status_code == 304


def test_bad_params_are_400(db, two_orgs):
    (org, client), _b = two_orgs
    assert client.get(f"{ENDPOINT}?since=abc").status_code == 400
    assert client.get(f"{ENDPOINT}?since=-1").status_code == 400
    assert client.get(f"{ENDPOINT}?since=0&limit=0").status_code == 400
