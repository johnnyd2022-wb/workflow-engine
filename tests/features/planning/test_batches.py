"""Persisted plans, hostile references and responsive board controls."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.audit_log import AuditLog
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.entity_event_summary import EntityEventSummary
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.site import Site
from app.core.db.models.step import Step
from app.core.security.access_policy import requirement_for
from app.features.planning import batch_service as service
from app.features.planning import demand_service, start_service
from app.features.planning.batch_models import PlanningBatch, PlanningWorkflowSetting
from app.features.planning.models import PlanningDemand
from tests.features.planning import test_demand as demand_fixtures

demand_clients = demand_fixtures.demand_clients
base_demand_world = demand_fixtures.demand_world
flask_app = demand_fixtures.flask_app
payload = demand_fixtures.payload

TODAY = date.today()


@pytest.fixture
def demand_world(db, base_demand_world):
    # Persisted-batch fixture uses a native 250-unit recipe matching its settings.
    for org_id in base_demand_world[:2]:
        step = db.query(Step).filter(Step.org_id == org_id).one()
        step.outputs = [{**output, "quantity": 250} for output in step.outputs]
    db.flush()
    yield base_demand_world


def setting_payload(db, scope_id, output_id, **changes):
    step = db.query(Step).filter(Step.org_id == scope_id).first()
    return {
        "source_output_id": str(output_id),
        "batch_quantity": "250",
        "steps": [{"step_id": str(step.id), "duration_minutes": 60, "waiting_minutes": 2820}],
        "expected_revision": 0,
        **changes,
    }


def configured(db, world):
    org_id, _, outputs = world
    step = db.query(Step).filter(Step.org_id == org_id).first()
    native_recipe(db, org_id, step.process_id)
    setting = service.save_setting(db, org_id, step.process_id, setting_payload(db, org_id, outputs[org_id]))
    demand = demand_service.create_demand(
        db, org_id, payload(outputs[org_id], due_date=(TODAY + timedelta(days=2)).isoformat())
    )
    return org_id, setting, demand


def native_recipe(db, org_id, process_id):
    """Fixture represents a versioned native 250-bottle workflow batch."""
    process = db.query(Process).filter(Process.org_id == org_id, Process.id == process_id).one()
    steps = db.query(Step).filter(Step.org_id == org_id, Step.process_id == process_id).all()
    for step in steps:
        step.outputs = [{"quantity": 250, **output} for output in step.outputs]
    db.flush()
    if service.latest_version(db, org_id, process_id) is None:
        db.add(
            ProcessVersion(
                org_id=org_id,
                process_id=process_id,
                version_number=1,
                snapshot=service._process_snapshot(process, steps),
            )
        )
        db.flush()


def planned(db, world):
    org_id, setting, demand = configured(db, world)
    rows, created = service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert created
    return org_id, setting, demand, rows


def test_settings_and_physical_batches_keep_snapshots_without_promising_delivery(db, demand_world):
    org_id, setting, demand, rows = planned(db, demand_world)
    assert len(rows) == 3
    assert [row.batch_number for row in rows] == [1, 2, 3]
    assert all(row.quantity == Decimal(250) for row in rows)
    assert all(
        row.proposed_start_date == TODAY and row.theoretical_ready_date == TODAY + timedelta(days=2) for row in rows
    )
    assert all(row.forecast_ready_date is None and row.status == "blocked" for row in rows)
    assert all(not service.batch_dict(row)["can_start"] for row in rows)
    saved = rows[0].snapshot.copy()
    service.save_setting(
        db,
        org_id,
        setting.process_id,
        setting_payload(db, org_id, demand.source_output_id, expected_revision=1, batch_quantity="300"),
    )
    assert rows[0].snapshot == saved
    retry, created = service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert not created and [row.id for row in retry] == [row.id for row in rows]
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"batch_quantity": "NaN"},
        {"batch_quantity": "Infinity"},
        {"batch_quantity": "-1"},
        {"batch_quantity": "0"},
        {"batch_quantity": "1.5"},
        {"batch_quantity": "1.00001"},
        {"batch_quantity": "100000000000000"},
        {"steps": []},
        {"steps": None},
        {"expected_revision": True},
        {"org_id": str(uuid4())},
        {"unit": "cases"},
    ],
)
def test_invalid_settings_never_write_rows(db, demand_world, changes):
    org_id, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).first()
    with pytest.raises(ValueError):
        service.save_setting(db, org_id, step.process_id, setting_payload(db, org_id, outputs[org_id], **changes))
    assert db.query(PlanningWorkflowSetting).count() == 0


@pytest.mark.parametrize("minutes", [True, -1, 1.5, "60", None, 525601])
def test_invalid_step_duration_or_wait_is_rejected(db, demand_world, minutes):
    org_id, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).first()
    for field in ("duration_minutes", "waiting_minutes"):
        data = setting_payload(db, org_id, outputs[org_id])
        data["steps"][0][field] = minutes
        with pytest.raises(ValueError):
            service.save_setting(db, org_id, step.process_id, data)


def test_foreign_steps_process_outputs_and_stale_settings_fail_closed(db, demand_world):
    org_id, other, outputs = demand_world
    ours = db.query(Step).filter(Step.org_id == org_id).first()
    foreign = db.query(Step).filter(Step.org_id == other).first()
    for process_id, output_id, steps in (
        (foreign.process_id, outputs[org_id], None),
        (ours.process_id, outputs[other], None),
        (
            ours.process_id,
            outputs[org_id],
            [{"step_id": str(foreign.id), "duration_minutes": 60, "waiting_minutes": 0}],
        ),
    ):
        data = setting_payload(db, org_id, output_id)
        if steps is not None:
            data["steps"] = steps
        with pytest.raises(ValueError):
            service.save_setting(db, org_id, process_id, data)
    setting = service.save_setting(db, org_id, ours.process_id, setting_payload(db, org_id, outputs[org_id]))
    with pytest.raises(service.PlanningConflictError):
        service.save_setting(db, org_id, ours.process_id, setting_payload(db, org_id, outputs[org_id]))
    assert setting.revision == 1
    demand = demand_service.create_demand(
        db, org_id, payload(outputs[org_id], due_date=(TODAY + timedelta(days=2)).isoformat())
    )
    ours.outputs = [{"id": str(outputs[org_id]), "name": "Changed", "unit": "bottles"}]
    db.flush()
    with pytest.raises(service.PlanningConflictError, match="changed"):
        service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert db.query(PlanningBatch).count() == 0


def test_decimal_position_fingerprint_survives_session_refresh(db, demand_world):
    org_id, _, demand = configured(db, demand_world)
    db.expire_all()
    rows, _ = service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert len(rows) == 3


def test_fixed_output_readiness_extends_timing_and_unknown_execution_date_has_no_ready_estimate(db, demand_world):
    org_id, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).first()
    output = {
        "id": str(outputs[org_id]),
        "name": "Gin",
        "unit": "bottles",
        "extra_data": {
            "ready_date": {"enabled": True, "mode": "fixed_duration", "duration_value": 7, "duration_unit": "days"}
        },
    }
    step.outputs = [output]
    db.flush()
    _, setting, demand, rows = planned(db, demand_world)
    assert setting.snapshot["elapsed_seconds"] == 9 * 86400
    assert rows[0].theoretical_ready_date == TODAY + timedelta(days=9)
    step.outputs = [{**output, "extra_data": {"ready_date": {"enabled": True, "mode": "set_at_execution"}}}]
    db.flush()
    service.save_setting(db, org_id, step.process_id, setting_payload(db, org_id, outputs[org_id], expected_revision=1))
    for row in rows:
        row.status = "cancelled"
    db.flush()
    unknown, _ = service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert all(row.theoretical_ready_date is None and row.forecast_ready_date is None for row in unknown)
    assert "not known until production" in unknown[0].blockers[0]


def test_dag_timings_do_not_sum_parallel_branches_and_cycles_are_refused(db, demand_world):
    org_id, _, outputs = demand_world
    first = db.query(Step).filter(Step.org_id == org_id).first()
    second_id = uuid4()
    second = Step(
        org_id=org_id,
        process_id=first.process_id,
        step_number=2,
        position=2000,
        name="Parallel",
        inputs=[],
        outputs=[{"id": str(second_id), "unit": "bottles"}],
        execution_prompts=[],
    )
    db.add(second)
    db.flush()
    data = setting_payload(
        db,
        org_id,
        outputs[org_id],
        steps=[{"step_id": str(row.id), "duration_minutes": 60, "waiting_minutes": 0} for row in (first, second)],
    )
    assert service.save_setting(db, org_id, first.process_id, data).snapshot["elapsed_seconds"] == 3600
    first.inputs = [{"source_output_id": str(second_id)}]
    second.inputs = [{"source_output_id": str(outputs[org_id])}]
    db.flush()
    with pytest.raises(ValueError, match="cycle"):
        service.save_setting(db, org_id, first.process_id, {**data, "expected_revision": 1})


def test_ambiguous_output_mapping_and_unknown_batch_settings_never_guess_dates(db, demand_world):
    org_id, _, outputs = demand_world
    demand = demand_service.create_demand(db, org_id, payload(outputs[org_id]))
    with pytest.raises(service.PlanningConflictError, match="timings"):
        service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    step = db.query(Step).filter(Step.org_id == org_id).first()
    step.outputs = [step.outputs[0], step.outputs[0]]
    db.flush()
    with pytest.raises(ValueError, match="ambiguous"):
        service.save_setting(db, org_id, step.process_id, setting_payload(db, org_id, outputs[org_id]))
    assert db.query(PlanningBatch).count() == 0


def test_plan_limit_and_tenant_scope_injection_are_rejected(db, demand_world):
    org_id, setting, demand = configured(db, demand_world)
    demand.quantity = Decimal(250 * (service.MAX_PLAN_BATCHES + 1))
    db.flush()
    with pytest.raises(ValueError, match="at most"):
        service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    with pytest.raises(ValueError, match="Unexpected"):
        service.plan_demand(db, org_id, demand.id, {"unit": "cases"}, today=TODAY)
    assert db.query(PlanningBatch).count() == 0


def test_pin_revision_reschedule_priority_and_cancel_transitions(db, demand_world):
    org_id, _, demand, rows = planned(db, demand_world)
    row = rows[0]

    def update(action, **values):
        return service.update_batch(
            db, org_id, row.id, {"action": action, "expected_revision": row.revision, **values}, today=TODAY
        )

    update("priority", priority=75)
    assert row.priority == 75
    update("pin", pinned=True)
    with pytest.raises(service.PlanningConflictError, match="Unpin"):
        update("reschedule", start_date=(TODAY + timedelta(days=1)).isoformat())
    with pytest.raises(service.PlanningConflictError, match="changed"):
        service.update_batch(
            db, org_id, row.id, {"action": "pin", "pinned": False, "expected_revision": 1}, today=TODAY
        )
    update("pin", pinned=False)
    update("reschedule", start_date=(TODAY + timedelta(days=3)).isoformat())
    assert row.proposed_start_date == TODAY + timedelta(days=3)
    assert row.theoretical_ready_date == TODAY + timedelta(days=5)
    assert row.forecast_ready_date is None
    update("cancel")
    assert row.status == "cancelled"
    _, changed = update("cancel")
    assert not changed
    with pytest.raises(service.PlanningConflictError):
        update("priority", priority=50)
    demand_service.cancel_demand(db, org_id, demand.id)
    assert all(row.status == "cancelled" for row in rows)


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "priority", "priority": True},
        {"action": "priority", "priority": 101},
        {"action": "pin", "pinned": "true"},
        {"action": "reschedule", "start_date": "invalid"},
        {"action": "reschedule", "start_date": (TODAY - timedelta(days=1)).isoformat()},
        {"action": "cancel", "quantity": "1"},
        {"action": "start"},
        {"action": []},
        {"action": {}},
        {"action": "priority", "priority": 0, "site_id": str(uuid4())},
    ],
)
def test_invalid_actions_cannot_mutate_plan(db, demand_world, changes):
    org_id, _, _, rows = planned(db, demand_world)
    row = rows[0]
    with pytest.raises(ValueError):
        service.update_batch(db, org_id, row.id, {"expected_revision": 1, **changes}, today=TODAY)
    assert row.revision == 1 and row.status == "blocked"


def test_other_org_cannot_read_mutate_or_start_plan_and_db_rejects_foreign_demand(db, demand_world):
    org_id, other, outputs = demand_world
    _, setting, _, rows = planned(db, demand_world)
    row = rows[0]
    assert service.list_batches(db, other, TODAY, TODAY + timedelta(days=3))["batches"] == []
    assert service.update_batch(db, other, row.id, {"action": "cancel", "expected_revision": 1}, today=TODAY) == (
        None,
        False,
    )
    assert start_service.start_batch(db, other, row.id, {"expected_revision": 1}, "foreign-key") == (None, False)
    foreign = demand_service.create_demand(db, other, payload(outputs[other]))
    row.demand_id = foreign.id
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_foreign_inactive_or_disabled_site_is_refused_and_database_enforces_site_org(db, demand_world):
    org_id, other, _ = demand_world
    _, _, demand = configured(db, demand_world)
    site = Site(org_id=other, name="Other site", is_default=True)
    db.add(site)
    db.flush()
    with pytest.raises(ValueError, match="Switch on"):
        service.plan_demand(db, org_id, demand.id, {"site_id": str(site.id)}, today=TODAY)
    org = db.query(Organisation).filter(Organisation.id == org_id).one()
    org.multiple_sites_enabled = True
    default = Site(org_id=org_id, name="Main", is_default=True)
    inactive = Site(org_id=org_id, name="Closed", is_active=False)
    db.add_all([default, inactive])
    db.flush()
    for identity in (site.id, inactive.id):
        with pytest.raises(ValueError, match="active site"):
            service.plan_demand(db, org_id, demand.id, {"site_id": str(identity)}, today=TODAY)
    rows, _ = service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert rows[0].site_id == default.id
    rows[0].site_id = site.id
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_unchecked_start_cannot_be_unlocked_by_database_flags_or_payload(db, demand_world):
    org_id, _, _, rows = planned(db, demand_world)
    row = rows[0]
    row.blockers = []
    row.status = "planned"
    db.flush()
    with pytest.raises(service.PlanningConflictError, match="Materials"):
        start_service.start_batch(db, org_id, row.id, {"expected_revision": 1}, "unchecked-start")
    with pytest.raises(ValueError, match="Unexpected"):
        start_service.start_batch(
            db, org_id, row.id, {"expected_revision": 1, "materials_checked": True}, "unchecked-start"
        )
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0
    assert db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == org_id).count() == 0


def test_trusted_start_uses_real_repository_once_and_key_cannot_cross_batches(db, demand_world, monkeypatch):
    org_id, _, demand, rows = planned(db, demand_world)
    row = rows[0]
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    result, changed = start_service.start_batch(db, org_id, row.id, {"expected_revision": 1}, "retry-start-key")
    assert changed and result["execution_id"] and row.status == "started"
    replay, changed = start_service.start_batch(db, org_id, row.id, {"expected_revision": 1}, "retry-start-key")
    assert not changed and replay == result
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 1
    assert db.query(ExecutionStep).filter(ExecutionStep.org_id == org_id).count() == 1
    with pytest.raises(service.PlanningConflictError, match="different"):
        start_service.start_batch(db, org_id, rows[1].id, {"expected_revision": 1}, "retry-start-key")
    with pytest.raises(ValueError, match="started"):
        demand_service.cancel_demand(db, org_id, demand.id)


def test_start_rejects_changed_or_draft_workflow_even_with_trusted_clearance(db, demand_world, monkeypatch):
    org_id, setting, _, rows = planned(db, demand_world)
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    step = db.query(Step).filter(Step.org_id == org_id).one()
    step.inputs = [{"name": "Changed ingredient"}]
    db.flush()
    with pytest.raises(service.PlanningConflictError, match="changed"):
        start_service.start_batch(db, org_id, rows[0].id, {"expected_revision": 1}, "workflow-changed")
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0


@pytest.mark.parametrize("quantity", [100, None, "NaN", -250])
def test_start_never_scales_native_recipe_to_a_planner_quantity(db, demand_world, monkeypatch, quantity):
    org_id, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).one()
    step.outputs = [{"id": str(outputs[org_id]), "unit": "bottles", "quantity": quantity}]
    db.flush()
    _, _, _, rows = planned(db, demand_world)
    assert rows[0].quantity == Decimal(250)
    assert any("quantity" in reason for reason in rows[0].snapshot["start_reasons"])
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    assert not start_service.can_start_batch(db, org_id, rows[0])
    with pytest.raises(service.PlanningConflictError, match="quantity"):
        start_service.start_batch(db, org_id, rows[0].id, {"expected_revision": 1}, "native-quantity-key")
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0
    assert db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == org_id).count() == 0
    assert rows[0].status == "blocked" and rows[0].forecast_ready_date is None


def test_start_pins_exact_version_even_when_recipe_definition_is_identical(db, demand_world, monkeypatch):
    org_id, _, _, rows = planned(db, demand_world)
    version = service.latest_version(db, org_id, rows[0].process_id)
    assert rows[0].snapshot["process_version_id"] == str(version.id)
    db.add(ProcessVersion(org_id=org_id, process_id=version.process_id, version_number=2, snapshot=version.snapshot))
    db.flush()
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    assert not start_service.can_start_batch(db, org_id, rows[0])
    with pytest.raises(service.PlanningConflictError, match="version changed"):
        start_service.start_batch(db, org_id, rows[0].id, {"expected_revision": 1}, "version-pinned-key")
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0


def test_unversioned_workflow_can_be_proposed_but_cannot_start(db, demand_world, monkeypatch):
    org_id, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).one()
    service.save_setting(db, org_id, step.process_id, setting_payload(db, org_id, outputs[org_id]))
    demand = demand_service.create_demand(
        db, org_id, payload(outputs[org_id], due_date=(TODAY + timedelta(days=2)).isoformat())
    )
    rows, _ = service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    assert rows[0].snapshot["process_version_id"] is None
    assert "Workflow version needs review" in rows[0].blockers
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    assert not start_service.can_start_batch(db, org_id, rows[0])
    with pytest.raises(service.PlanningConflictError, match="version changed"):
        start_service.start_batch(db, org_id, rows[0].id, {"expected_revision": 1}, "unversioned-start")
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0


def test_workflow_reads_refresh_a_cached_step_from_another_transaction(db, demand_world):
    from app.core.db import SessionLocal

    org_id, _, _, rows = planned(db, demand_world)
    step = db.query(Step).filter(Step.org_id == org_id).one()
    old_fingerprint = rows[0].snapshot["workflow_fingerprint"]
    identity = step.id
    db.commit()
    try:
        # Load into this session before a concurrent edit; re-read must refresh it.
        assert db.query(Step).filter(Step.id == identity).one().name == step.name
        with SessionLocal() as concurrent:
            changed = concurrent.query(Step).filter(Step.org_id == org_id, Step.id == identity).one()
            changed.name = "Concurrent recipe edit"
            concurrent.commit()
        _, _, _, _, current = service._workflow(db, org_id, rows[0].process_id, rows[0].source_output_id)
        assert current != old_fingerprint
    finally:
        _cleanup_world(db, demand_world[:2])


@pytest.fixture
def board_clients(db, demand_clients):
    for _, org_id, _ in demand_clients:
        step = db.query(Step).filter(Step.org_id == org_id).one()
        step.outputs = [{**output, "quantity": 250} for output in step.outputs]
    db.commit()
    yield demand_clients
    ids = [row[1] for row in demand_clients]
    db.rollback()
    for model in (
        PlanningBatch,
        PlanningWorkflowSetting,
        ApiIdempotencyKey,
        ExecutionStep,
        Execution,
        ProcessVersion,
        EntityEvent,
        EntityEventSummary,
    ):
        db.query(model).filter(model.org_id.in_(ids)).delete(synchronize_session=False)
    db.commit()


def configure_http(db, client, output_id):
    catalog = client.get("/api/core/planner/workflows").get_json()["workflows"]
    workflow = next(row for row in catalog if row["id"] == str(output_id))
    step = db.query(Step).filter(Step.id == service._id(workflow["steps"][0]["step_id"])).one()
    native_recipe(db, step.org_id, step.process_id)
    db.commit()
    response = client.post(
        "/api/core/planner/workflows/" + workflow["process_id"] + "/settings",
        json={
            "source_output_id": str(output_id),
            "batch_quantity": "250",
            "expected_revision": 0,
            "steps": [
                {"step_id": row["step_id"], "duration_minutes": 60, "waiting_minutes": 2820}
                for row in workflow["steps"]
            ],
        },
    )
    assert response.status_code == 200, response.get_json()
    created = client.post(
        "/api/core/planner/demands", json=payload(output_id, due_date=(TODAY + timedelta(days=2)).isoformat())
    ).get_json()
    return created


def test_http_board_mutations_audit_permission_and_cross_tenant_boundaries(db, board_clients):
    client, org_id, output = board_clients[0]
    other = board_clients[1][0]
    auditor = board_clients[2][0]
    demand = configure_http(db, client, output)
    response = client.post("/api/core/planner/demands/" + demand["id"] + "/plan", json={})
    assert response.status_code == 201
    row = response.get_json()["batches"][0]
    assert client.post("/api/core/planner/demands/" + demand["id"] + "/plan", json={}).status_code == 200
    assert other.post("/api/core/planner/demands/" + demand["id"] + "/plan", json={}).status_code == 404
    path = "/api/core/planner/batches/" + row["id"]
    assert other.post(path + "/action", json={"action": "cancel", "expected_revision": 1}).status_code == 404
    assert auditor.get("/core/planner/board").status_code == 200
    assert auditor.post(path + "/action", json={"action": "cancel", "expected_revision": 1}).status_code == 403
    assert (
        client.post(
            path + "/start", json={"expected_revision": 1}, headers={"Idempotency-Key": "unchecked-key"}
        ).status_code
        == 409
    )
    assert (
        client.post(path + "/action", json={"action": "priority", "priority": 75, "expected_revision": 1}).status_code
        == 200
    )
    audit = db.query(AuditLog).filter(AuditLog.org_id == org_id, AuditLog.entity == "planning_batch").all()
    assert len([entry for entry in audit if entry.action == "planning_batch_created"]) == 3
    assert any(entry.action == "planning_batch_priority" and entry.user_id is not None for entry in audit)
    assert requirement_for("planning.start_planning_batch", "POST") == "production.record"


def _cleanup_world(db, identities):
    db.rollback()
    for model in (
        PlanningBatch,
        PlanningWorkflowSetting,
        ApiIdempotencyKey,
        ExecutionStep,
        Execution,
        ProcessVersion,
        EntityEvent,
        EntityEventSummary,
        PlanningDemand,
        AuditLog,
        Step,
        Site,
        Process,
        Organisation,
    ):
        column = model.id if model is Organisation else model.org_id
        db.query(model).filter(column.in_(identities)).delete(synchronize_session=False)
    db.commit()


def test_concurrent_planning_retries_create_one_physical_batch_set(db, demand_world):
    from concurrent.futures import ThreadPoolExecutor

    from app.core.db import SessionLocal

    org_id, _, demand = configured(db, demand_world)
    identity = demand.id
    db.commit()

    def plan():
        with SessionLocal() as session:
            rows, created = service.plan_demand(session, org_id, identity, {}, today=TODAY)
            ids = [str(row.id) for row in rows]
            session.commit()
            return ids, created

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: plan(), range(2)))
        assert first[0] == second[0]
        assert sorted([first[1], second[1]]) == [False, True]
        assert db.query(PlanningBatch).filter(PlanningBatch.org_id == org_id).count() == 3
    finally:
        _cleanup_world(db, demand_world[:2])


def test_concurrent_start_retries_create_one_execution(db, demand_world, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.core.db import SessionLocal

    org_id, _, _, rows = planned(db, demand_world)
    identity = rows[0].id
    db.commit()
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))

    def start():
        with SessionLocal() as session:
            result, changed = start_service.start_batch(
                session, org_id, identity, {"expected_revision": 1}, "concurrent-retry"
            )
            session.commit()
            return result, changed

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: start(), range(2)))
        assert first[0] == second[0]
        assert sorted([first[1], second[1]]) == [False, True]
        assert db.query(Execution).filter(Execution.org_id == org_id).count() == 1
        assert db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == org_id).count() == 1
    finally:
        _cleanup_world(db, demand_world[:2])


def test_all_new_mutation_routes_enforce_real_csrf(db, board_clients, flask_app):
    from html.parser import HTMLParser

    class Token(HTMLParser):
        value = None

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "meta" and attributes.get("name") == "csrf-token":
                self.value = attributes.get("content")

    client, org_id, output = board_clients[0]
    demand = configure_http(db, client, output)
    original = flask_app.config["WTF_CSRF_ENABLED"]
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        token = Token()
        token.feed(client.get("/core/planner/board").get_data(as_text=True))
        headers = {"X-CSRFToken": token.value, "Referer": "https://localhost/core/planner/board"}
        plan_path = "/api/core/planner/demands/" + demand["id"] + "/plan"
        assert client.post(plan_path, json={}).status_code == 400
        result = client.post(plan_path, json={}, headers=headers)
        assert result.status_code == 201
        row = result.get_json()["batches"][0]
        action_path = "/api/core/planner/batches/" + row["id"] + "/action"
        action = {"action": "priority", "priority": 75, "expected_revision": 1}
        assert client.post(action_path, json=action).status_code == 400
        assert client.post(action_path, json=action, headers=headers).status_code == 200
        setting = db.query(PlanningWorkflowSetting).filter(PlanningWorkflowSetting.org_id == org_id).first()
        settings_path = "/api/core/planner/workflows/" + str(setting.process_id) + "/settings"
        data = setting_payload(db, org_id, output, expected_revision=1)
        assert client.post(settings_path, json=data).status_code == 400
        assert client.post(settings_path, json=data, headers=headers).status_code == 200
        start_path = "/api/core/planner/batches/" + row["id"] + "/start"
        retry = {**headers, "Idempotency-Key": "csrf-start-key"}
        assert client.post(start_path, json={"expected_revision": 2}).status_code == 400
        assert client.post(start_path, json={"expected_revision": 2}, headers=retry).status_code == 409
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = original


def test_catalog_prefetches_with_constant_query_count(db, demand_world):
    from sqlalchemy import event

    org_id, _, _ = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).first()
    step.outputs = [*step.outputs, *[{"id": str(uuid4()), "name": "Extra", "unit": "bottles"} for _ in range(5)]]
    db.flush()
    queries = []

    def collect(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", collect)
    try:
        assert len(service.workflow_catalog(db, org_id)) == 6
        assert len(queries) == 4
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", collect)


def test_start_failure_rolls_back_real_execution_and_audit(db, board_clients, monkeypatch):
    from app.core.db.repositories.execution_repo import ExecutionRepository

    client, org_id, output = board_clients[0]
    demand = configure_http(db, client, output)
    row = client.post("/api/core/planner/demands/" + demand["id"] + "/plan", json={}).get_json()["batches"][0]
    original = ExecutionRepository.create_execution

    def fail_after_create(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise ValueError("Production start failed")

    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    monkeypatch.setattr(ExecutionRepository, "create_execution", fail_after_create)
    result = client.post(
        "/api/core/planner/batches/" + row["id"] + "/start",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "rollback-start-key"},
    )
    assert result.status_code == 400
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0
    assert db.query(ExecutionStep).filter(ExecutionStep.org_id == org_id).count() == 0
    assert db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.org_id == org_id).count() == 0
    assert (
        db.query(AuditLog).filter(AuditLog.org_id == org_id, AuditLog.action == "planning_batch_started").count() == 0
    )
    batch = db.query(PlanningBatch).filter(PlanningBatch.org_id == org_id, PlanningBatch.id == row["id"]).one()
    assert batch.status == "blocked" and batch.execution_id is None


@pytest.mark.parametrize("field", ["process_id", "setting_id", "execution_id"])
def test_database_rejects_other_tenant_batch_references(db, demand_world, field):
    org_id, other, outputs = demand_world
    _, _, _, rows = planned(db, demand_world)
    other_step = db.query(Step).filter(Step.org_id == other).first()
    foreign_setting = service.save_setting(db, other, other_step.process_id, setting_payload(db, other, outputs[other]))
    foreign_execution = Execution(org_id=other, process_id=other_step.process_id)
    db.add(foreign_execution)
    db.flush()
    foreign = {
        "process_id": other_step.process_id,
        "setting_id": foreign_setting.id,
        "execution_id": foreign_execution.id,
    }[field]
    setattr(rows[0], field, foreign)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize(
    "rule",
    [
        [],
        "",
        {"enabled": True, "mode": "fixed_duration", "duration_value": 7, "duration_unit": []},
        {"enabled": "true", "mode": "fixed_duration", "duration_value": 7, "duration_unit": "days"},
        {"enabled": True, "mode": "fixed_duration", "duration_value": True, "duration_unit": "days"},
    ],
)
def test_malformed_existing_readiness_rules_keep_the_ready_date_unknown(db, demand_world, rule, monkeypatch):
    org_id, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).one()
    step.outputs = [{"id": str(outputs[org_id]), "unit": "bottles", "extra_data": {"ready_date": rule}}]
    db.flush()
    _, setting, _, rows = planned(db, demand_world)
    assert setting.snapshot["readiness_reasons"]
    assert setting.snapshot["start_reasons"]
    assert all(row.theoretical_ready_date is None and row.forecast_ready_date is None for row in rows)
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    assert not start_service.can_start_batch(db, org_id, rows[0])
    with pytest.raises(service.PlanningConflictError, match="settings need review"):
        start_service.start_batch(db, org_id, rows[0].id, {"expected_revision": 1}, "invalid-readiness")
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0


def test_set_at_execution_ready_date_does_not_prevent_a_trusted_start_or_invent_a_forecast(
    db, demand_world, monkeypatch
):
    org_id, _, outputs = demand_world
    step = db.query(Step).filter(Step.org_id == org_id).one()
    step.outputs = [
        {
            "id": str(outputs[org_id]),
            "unit": "bottles",
            "extra_data": {"ready_date": {"enabled": True, "mode": "set_at_execution"}},
        }
    ]
    db.flush()
    _, setting, _, rows = planned(db, demand_world)
    assert setting.snapshot["readiness_reasons"] and not setting.snapshot["start_reasons"]
    assert not start_service.can_start_batch(db, org_id, rows[0])
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    assert start_service.can_start_batch(db, org_id, rows[0])
    result, changed = start_service.start_batch(
        db, org_id, rows[0].id, {"expected_revision": 1}, "unknown-output-ready"
    )
    assert changed and result["execution_id"] and result["status"] == "started"
    assert result["theoretical_ready_date"] is None and result["forecast_ready_date"] is None
    assert result["blockers"] == setting.snapshot["readiness_reasons"]


def test_can_start_requires_fresh_trusted_checks_and_available_site(db, demand_world, monkeypatch):
    org_id, _, demand, rows = planned(db, demand_world)
    row = rows[0]
    assert not start_service.can_start_batch(db, org_id, row)
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    assert start_service.can_start_batch(db, org_id, row)
    row.pinned = True
    row.proposed_start_date = TODAY + timedelta(days=1)
    assert not start_service.can_start_batch(db, org_id, row)
    row.proposed_start_date = TODAY
    row.site_id = uuid4()
    assert not start_service.can_start_batch(db, org_id, row)
    row.site_id = None
    demand.status = "cancelled"
    assert not start_service.can_start_batch(db, org_id, row)


def test_site_operations_uuid_seam_passes_explicit_scope_and_preserves_guard(db, demand_world, monkeypatch):
    from types import SimpleNamespace

    from app.core.db.repositories.execution_repo import ExecutionRepository

    org_id, _, _ = demand_world
    org = db.query(Organisation).filter(Organisation.id == org_id).one()
    org.multiple_sites_enabled = True
    default = Site(org_id=org_id, name="Default", is_default=True)
    db.add(default)
    db.flush()
    _, _, _, rows = planned(db, demand_world)
    original = ExecutionRepository.create_execution
    seen = []

    def create(self, org_id, process_id, commit=True, site_id=None):
        seen.append(site_id)
        assert site_id == default.id and not commit
        return original(self, org_id, process_id, commit=commit)

    monkeypatch.setattr(
        start_service, "import_module", lambda name: SimpleNamespace(resolve_site=lambda db, org_id, site_id: site_id)
    )
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    monkeypatch.setattr(ExecutionRepository, "create_execution", create)
    result, changed = start_service.start_batch(db, org_id, rows[0].id, {"expected_revision": 1}, "guarded-site-key")
    assert changed and result["execution_id"] and seen == [default.id]


@pytest.mark.parametrize("key", [None, "", "with spaces", "x" * 111])
def test_start_requires_valid_retry_key(db, demand_world, key):
    org_id, _, _, rows = planned(db, demand_world)
    with pytest.raises(ValueError, match="Idempotency-Key"):
        start_service.start_batch(db, org_id, rows[0].id, {"expected_revision": 1}, key)
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0


def test_start_cannot_ignore_pin_date_stale_revision_or_cancelled_demand(db, demand_world, monkeypatch):
    org_id, _, demand, rows = planned(db, demand_world)
    row = rows[0]
    monkeypatch.setattr(start_service, "evaluate_start", lambda *args: start_service.StartCheck(()))
    row.proposed_start_date = TODAY + timedelta(days=1)
    db.flush()
    with pytest.raises(service.PlanningConflictError, match="before starting early"):
        start_service.start_batch(db, org_id, row.id, {"expected_revision": 1}, "future-date-key")
    row.proposed_start_date = TODAY
    row.revision = 2
    db.flush()
    with pytest.raises(service.PlanningConflictError, match="changed"):
        start_service.start_batch(db, org_id, row.id, {"expected_revision": 1}, "stale-revision-key")
    demand.status = "cancelled"
    db.flush()
    with pytest.raises(service.PlanningConflictError, match="no longer open"):
        start_service.start_batch(db, org_id, row.id, {"expected_revision": 2}, "closed-demand-key")
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0
