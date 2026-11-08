"""Record a production step (/core/record): batches in flight and workflows, one tap each."""

import pytest

from app.core.db.models.execution import Execution
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.step import Step
from app.core.db.models.user import User
from tests.test_auth_password_session import account as _account  # noqa: F401 -- fixture re-export


@pytest.fixture
def account(_account, db):  # noqa: F811
    """The shared account, with the workflows and batches these tests make removed first."""
    yield _account
    db.rollback()
    org_id = db.query(User.org_id).filter(User.email == _account["email"]).scalar()
    for ex in db.query(Execution).filter(Execution.org_id == org_id).all():
        db.delete(ex)  # its execution steps go with it
    db.flush()
    ids = [p.id for p in db.query(Process.id).filter(Process.org_id == org_id)]
    if ids:
        db.query(Step).filter(Step.process_id.in_(ids)).delete(synchronize_session=False)
        db.query(ProcessVersion).filter(ProcessVersion.process_id.in_(ids)).delete(synchronize_session=False)
        db.query(Process).filter(Process.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


def _workflow(client, name, steps, draft=False):
    pid = client.post("/api/core/processes", json={"name": name, "is_draft": draft}).get_json()["id"]
    ids = [
        client.post(f"/api/core/processes/{pid}/steps", json={"step_number": i + 1, "name": s}).get_json()["id"]
        for i, s in enumerate(steps)
    ]
    return pid, ids


def test_a_batch_in_flight_links_straight_to_its_next_step(account):  # noqa: F811
    client = account["client"]
    pid, _ = _workflow(client, "Wildflower Gin", ["Macerate", "Distil", "Bottle"])
    started = client.post("/api/core/executions", json={"process_id": pid})
    assert started.status_code in (200, 201), started.data
    eid = started.get_json()["id"]

    body = client.get("/api/core/record-options").get_json()
    batch = next(b for b in body["batches"] if b["execution_id"] == eid)
    assert batch["workflow"] == "Wildflower Gin"
    assert (batch["step_name"], batch["step_number"], batch["step_total"]) == ("Macerate", 1, 3)
    assert batch["href"] == f"/core/flows/batches/start?id={pid}&execution_id={eid}&return_to=/core/record"


def test_every_ready_workflow_starts_a_batch_at_its_first_step(account):  # noqa: F811
    client = account["client"]
    pid, step_ids = _workflow(client, "Solstice", ["Steep", "Distil"])
    _workflow(client, "Half-built", ["Only step"], draft=True)
    _workflow(client, "No steps yet", [])

    names = {w["name"]: w for w in client.get("/api/core/record-options").get_json()["workflows"]}
    assert "Half-built" not in names, "a draft can't be run"
    assert "No steps yet" not in names, "nothing to record"
    solstice = names["Solstice"]
    assert solstice["first_step"] == "Steep" and solstice["step_count"] == 2
    assert (
        solstice["href"] == f"/core/flows/batches/start?draft=1&id={pid}&step_id={step_ids[0]}&return_to=/core/record"
    )


def test_the_page_renders(account):  # noqa: F811
    resp = account["client"].get("/core/record")
    assert resp.status_code == 200
    assert b"data-record-step-root" in resp.data


def _record(client, eid, step_index, data=None):
    ex = client.get(f"/api/core/executions/{eid}").get_json()
    steps = sorted(ex["execution_steps"], key=lambda s: s["step_number"])
    resp = client.post(
        f"/api/core/executions/{eid}/steps/{steps[step_index]['id']}/complete",
        json={"actual_inputs": [], "actual_outputs": [], "execution_data": data or {}},
    )
    assert resp.status_code == 200, resp.data


def test_a_batch_shows_the_batch_number_recorded_on_its_step(account):  # noqa: F811
    """Review on !576: the "Batch number" prompt is where operators record the batch code."""
    client = account["client"]
    pid, _ = _workflow(client, "Harbour Gin", ["Macerate", "Distil"])
    eid = client.post("/api/core/executions", json={"process_id": pid}).get_json()["id"]
    _record(client, eid, 0, {"Batch number": "GIN-2026-042"})

    batch = next(b for b in client.get("/api/core/record-options").get_json()["batches"] if b["execution_id"] == eid)
    assert batch["label"] == "GIN-2026-042"


def test_the_recorded_batch_is_read_on_its_own_not_inferred_from_the_bounded_list(account, monkeypatch):  # noqa: F811
    """Review on !576: a batch outside the limited list is still in progress, not finished."""
    from app.core.backend import record_step

    client = account["client"]
    pid, _ = _workflow(client, "Two Step", ["Steep", "Bottle"])
    older = client.post("/api/core/executions", json={"process_id": pid}).get_json()["id"]
    newer = client.post("/api/core/executions", json={"process_id": pid}).get_json()["id"]
    _record(client, newer, 0)
    monkeypatch.setattr(record_step, "MAX_BATCHES", 1)

    body = client.get(f"/api/core/record-options?recorded={newer}").get_json()
    assert [b["execution_id"] for b in body["batches"]] == [older]
    assert body["batches_total"] == 2
    assert body["recorded"]["finished"] is False
    assert body["recorded"]["batch"]["step_name"] == "Bottle"

    _record(client, newer, 1)
    done = client.get(f"/api/core/record-options?recorded={newer}").get_json()["recorded"]
    assert done == {"execution_id": newer, "finished": True, "batch": None}


def test_another_orgs_batch_is_not_reported_as_recorded(account):  # noqa: F811
    from uuid import uuid4

    body = account["client"].get(f"/api/core/record-options?recorded={uuid4()}").get_json()
    assert body["recorded"] is None


def test_the_workflow_limit_is_spent_on_runnable_workflows_most_recent_first(account, monkeypatch):  # noqa: F811
    """Review on !576: empty or alphabetically early workflows must not crowd out runnable ones."""
    from app.core.backend import record_step

    client = account["client"]
    _workflow(client, "A empty", [])
    _workflow(client, "B never run", ["Steep"])
    used, _ = _workflow(client, "Z runnable", ["Steep"])
    client.post("/api/core/executions", json={"process_id": used})
    monkeypatch.setattr(record_step, "MAX_WORKFLOWS", 1)

    body = client.get("/api/core/record-options").get_json()
    assert [w["name"] for w in body["workflows"]] == ["Z runnable"]
    assert body["workflows_total"] == 2
