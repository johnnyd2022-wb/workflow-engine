"""GL-P09: the getting-started path reads each step's state from the org's own records."""

from datetime import date

import pytest

from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.step import Step
from app.core.db.models.user import User
from tests.test_auth_password_session import account as _account  # noqa: F401 -- fixture re-export


@pytest.fixture
def account(_account, db):  # noqa: F811
    """The shared account, with the workflows these tests create removed before its org is."""
    yield _account
    db.rollback()
    org_id = db.query(User.org_id).filter(User.email == _account["email"]).scalar()
    ids = [p.id for p in db.query(Process.id).filter(Process.org_id == org_id)]
    if ids:
        db.query(Step).filter(Step.process_id.in_(ids)).delete(synchronize_session=False)
        db.query(ProcessVersion).filter(ProcessVersion.process_id.in_(ids)).delete(synchronize_session=False)
        db.query(Process).filter(Process.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


def _state(client):
    resp = client.get("/api/core/getting-started")
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    return body, {s["key"]: s for s in body["steps"]}


def _org(db, email):
    db.expire_all()
    return db.get(Organisation, db.query(User).filter(User.email == email).one().org_id)


def test_a_new_org_starts_at_the_first_step_with_later_ones_blocked(account):  # noqa: F811
    body, steps = _state(account["client"])
    assert steps["workflow"]["status"] == "todo"
    assert steps["first_batch"]["status"] == "blocked"
    assert steps["first_batch"]["blocked_by"] == "Set up a product workflow first."
    assert steps["first_batch"]["needs"] == "workflow"
    assert body["done"] == 0 and body["complete"] is False
    assert body["next"] == body["steps"][0]["key"]
    # A step is a link to where it's done, with words for the button.
    assert steps["opening_stock"]["href"] == "/core/go-live"


def test_steps_complete_from_what_the_org_has_done(account, db):  # noqa: F811
    client = account["client"]
    created = client.post("/api/core/processes", json={"name": "Wildflower Gin", "is_draft": False})
    assert created.status_code == 201, created.data
    _org(db, account["email"]).go_live_date = date(2026, 10, 1)
    db.commit()

    body, steps = _state(client)
    assert steps["workflow"]["status"] == "done"
    assert steps["workflow"]["fact"] == "1 workflow"
    assert steps["opening_stock"]["status"] == "done"
    assert steps["opening_stock"]["fact"] == "Counted on 1 Oct 2026"
    assert steps["first_batch"]["status"] == "todo", "unblocked once a workflow exists"
    assert body["done"] >= 2


def test_a_draft_workflow_does_not_count(account):  # noqa: F811
    client = account["client"]
    client.post("/api/core/processes", json={"name": "Half-built", "is_draft": True})
    _, steps = _state(client)
    assert steps["workflow"]["status"] == "todo"


def test_the_page_renders(account):  # noqa: F811
    resp = account["client"].get("/core/getting-started")
    assert resp.status_code == 200
    assert b"data-getting-started-root" in resp.data


def test_a_module_step_leads_and_a_failing_module_cannot_break_the_guide(account, monkeypatch):  # noqa: F811
    from app.core.backend import getting_started as gs

    def ours(session, org_id):
        return gs.ProvidedStep("ours", "Your business", "Tell us X", "Why", "/x", "Do X", done=True, fact="X set")

    def broken(session, org_id):
        raise RuntimeError("module bug")

    def not_for_this_org(session, org_id):
        return None

    monkeypatch.setattr(gs, "_PROVIDERS", [broken, ours, not_for_this_org])
    body, steps = _state(account["client"])
    assert body["steps"][0]["key"] == "ours"
    assert steps["ours"]["status"] == "done" and steps["ours"]["fact"] == "X set"
    assert "workflow" in steps
