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
