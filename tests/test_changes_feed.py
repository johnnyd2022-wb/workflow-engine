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
    # Raw insert -- seq is filled by the column's IDENTITY default here. (EventWriter
    # allocates it explicitly under a per-org advisory lock; that path is covered by
    # test_open_writer_transaction_never_causes_a_skipped_event.)
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
    """The 1s settle window is retained as a rolling-deploy belt (an old worker still
    allocates seq from the bare IDENTITY without the advisory lock). An event created
    "just now" is withheld until it clears the window."""
    (org, client), _b = two_orgs
    start = client.get(ENDPOINT).get_json()["cursor"]
    _emit(db, org.id, "process.created", "process", uuid4(), created_at=datetime.now(UTC))  # "just now"

    assert client.get(f"{ENDPOINT}?since={start}").get_json()["events"] == []


def test_open_writer_transaction_never_causes_a_skipped_event(db, two_orgs):
    """The race MR !201 P1 is about: a bare sequence lets txn A take seq=N, stay open, and
    txn B take seq=N+1 and commit first -- a poller past the settle window advances past N
    and A's event is skipped forever.

    With the per-org advisory lock, B cannot allocate a seq until A commits. This test
    holds A's transaction open, starts B (which must block), proves B is blocked, polls
    (sees nothing), then releases A -- and asserts BOTH events are then delivered exactly
    once, in order, with contiguous seqs.
    """
    import threading
    import time

    from app.core.backend.event_writer import EventWriter, _feed_cursor_lock_key
    from app.core.db import SessionLocal

    (org, client), _b = two_orgs
    start = client.get(ENDPOINT).get_json()["cursor"]

    # pg_advisory_xact_lock(bigint) shows in pg_locks with the key split across
    # (classid, objid) as unsigned int32 halves and objsubid = 1.
    _key = _feed_cursor_lock_key(org.id) & 0xFFFFFFFFFFFFFFFF
    _key_hi, _key_lo = (_key >> 32) & 0xFFFFFFFF, _key & 0xFFFFFFFF

    a_has_seq = threading.Event()
    a_may_commit = threading.Event()
    b_pid: dict[str, int] = {}
    outcomes: dict[str, str] = {}

    def txn_a():
        s = SessionLocal()
        try:
            EventWriter(s, org.id).emit("process.created", "process", uuid4(), {})
            a_has_seq.set()
            a_may_commit.wait(timeout=15)
            s.commit()
            outcomes["a"] = "committed"
        except Exception as exc:  # pragma: no cover
            outcomes["a"] = f"exc:{exc}"
        finally:
            s.close()

    def txn_b():
        s = SessionLocal()
        try:
            b_pid["pid"] = s.execute(text("SELECT pg_backend_pid()")).scalar()
            EventWriter(s, org.id).emit("execution.created", "execution", uuid4(), {"execution_id": str(uuid4())})
            s.commit()
            outcomes["b"] = "committed"
        except Exception as exc:  # pragma: no cover
            outcomes["b"] = f"exc:{exc}"
        finally:
            s.close()

    def _b_is_waiting_on_this_feed_lock() -> bool:
        # Proof it is *this B* backend waiting on *this org's feed allocator lock* --
        # not merely an unscheduled thread or unrelated advisory-lock contention.
        # rollback() after so this probe never leaves `db` holding a transaction whose
        # frozen now() would then hide freshly-committed rows from the feed's settle window.
        if "pid" not in b_pid:
            return False
        try:
            return bool(
                db.execute(
                    text(
                        "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
                        "AND pid = :pid AND classid = :hi AND objid = :lo AND objsubid = 1"
                    ),
                    {"pid": b_pid["pid"], "hi": _key_hi, "lo": _key_lo},
                ).scalar()
            )
        finally:
            db.rollback()

    ta = threading.Thread(target=txn_a)
    tb = threading.Thread(target=txn_b)
    try:
        ta.start()
        assert a_has_seq.wait(timeout=10), "txn A never allocated its seq"

        tb.start()
        # Wait until B is provably blocked on THIS advisory lock (not just "still alive").
        deadline = time.monotonic() + 10
        while not _b_is_waiting_on_this_feed_lock():
            assert time.monotonic() < deadline, "txn B never blocked on the feed advisory lock"
            assert outcomes.get("b") is None, f"txn B allocated a seq while A was open: {outcomes}"
            time.sleep(0.05)

        # Poll while A is open and B is blocked -> the feed shows neither.
        assert client.get(f"{ENDPOINT}?since={start}").get_json()["events"] == []
    finally:
        a_may_commit.set()  # never leave A (and thus B) hanging, even on assertion failure
        ta.join(timeout=15)
        tb.join(timeout=15)

    assert outcomes == {"a": "committed", "b": "committed"}, outcomes

    # Both events now exist and are committed. The retained 1s settle window delays their
    # visibility, so poll until they clear it (the point of this test is the SEQ ordering
    # once they do, not the window). db.rollback() each iteration: the test thread's scoped
    # session (shared by the Flask test client under the single app_context) otherwise
    # keeps one transaction open, and Postgres pins now() to a transaction's start, so the
    # settle predicate would never see the fresh rows clear.
    deadline = time.monotonic() + 5
    while True:
        db.rollback()
        body = client.get(f"{ENDPOINT}?since={start}").get_json()
        if len(body["events"]) == 2:
            break
        assert time.monotonic() < deadline, f"events never cleared the settle window: {body}"
        time.sleep(0.1)

    assert [e["event_type"] for e in body["events"]] == ["process.created", "execution.created"]
    seqs = [e["seq"] for e in body["events"]]
    assert seqs == sorted(seqs) and seqs[1] == seqs[0] + 1, f"seqs not contiguous/ordered: {seqs}"
    assert body["cursor"] == seqs[-1]


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
