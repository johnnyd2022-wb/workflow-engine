"""Exact-lot observation persistence; availability authority is mocked only at its boundary."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.core.db.models.audit_log import AuditLog
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.site import Site
from app.core.db.models.step import Step
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.security.access_policy import requirement_for
from app.features.planning import batch_service, demand_service, start_service
from app.features.planning import material_adapter as adapter
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.forecast_models import PlanningMaterialAssessment, PlanningMaterialBatchAssessment
from tests.features.planning import test_batches as fixtures

demand_world = fixtures.demand_world
base_demand_world = fixtures.base_demand_world
base_board_clients = fixtures.board_clients
demand_clients = fixtures.demand_clients
flask_app = fixtures.flask_app
TODAY = fixtures.TODAY


def lot(db, org_id, **changes):
    return InventoryRepository(db).create_inventory_item(
        org_id,
        name=changes.pop("name", "Sugar"),
        quantity=changes.pop("quantity", Decimal(5)),
        unit=changes.pop("unit", "kg"),
        inventory_type=changes.pop("inventory_type", "raw_material"),
        commit=False,
        **changes,
    )


def bind(step, item):
    return {"step_id": str(step.id), "input_index": 0, "inventory_item_id": str(item.id)}


def prepare(db, world):
    org_id, other_id, outputs = world
    step = db.query(Step).filter(Step.org_id == org_id).one()
    step.inputs = [{"name": "Sugar", "quantity": "2", "unit": "kg"}]
    db.flush()
    own = lot(db, org_id)
    sibling = lot(db, org_id, quantity=Decimal(100))
    foreign = lot(db, other_id)
    fixtures.native_recipe(db, org_id, step.process_id)
    data = fixtures.setting_payload(db, org_id, outputs[org_id], material_lots=[bind(step, own)])
    setting = batch_service.save_setting(db, org_id, step.process_id, data)
    demand = demand_service.create_demand(
        db, org_id, fixtures.payload(outputs[org_id], due_date=(TODAY + timedelta(days=2)).isoformat())
    )
    batches, _ = batch_service.plan_demand(db, org_id, demand.id, {}, today=TODAY)
    return org_id, other_id, step, own, sibling, foreign, setting, batches


def trusted_boundary(monkeypatch, availability=None):
    # Future owner/commitment adapters are NOT activated by these test doubles.
    monkeypatch.setattr(adapter, "resolve_owner", lambda item: (True, None))
    monkeypatch.setattr(
        adapter,
        "resolve_availability",
        availability or (lambda db, org, item: adapter.LotAvailability(item.quantity, TODAY, ())),
    )


def results(db, org_id):
    return adapter.latest(db, org_id)["batches"]


def test_freezes_exact_lot_and_does_not_substitute_same_name_or_mutate_stock(db, demand_world, monkeypatch):
    org_id, _, step, own, sibling, _, setting, batches = prepare(db, demand_world)
    saved = batches[0].snapshot["material_bindings"]
    assert saved == setting.snapshot["material_bindings"]
    data = fixtures.setting_payload(
        db, org_id, setting.source_output_id, expected_revision=1, material_lots=[bind(step, sibling)]
    )
    batch_service.save_setting(db, org_id, step.process_id, data)
    assert batches[0].snapshot["material_bindings"] == saved
    trusted_boundary(monkeypatch)
    adapter.assess(db, org_id, {}, today=TODAY)
    values = results(db, org_id)
    assert [row["material_status"] for row in values] == ["on_time", "on_time", "blocked"]
    assert [row["allocations"][0]["lot_id"] for row in values[:2]] == [str(own.id)] * 2
    assert values[2]["allocations"] == [] and values[2]["material_start_date"] is None
    assert own.quantity == Decimal(5) and sibling.quantity == Decimal(100)
    assert all(row.forecast_ready_date is None and row.status == "blocked" for row in batches)
    assert db.query(Execution).filter(Execution.org_id == org_id).count() == 0
    assert not start_service.can_start_batch(db, org_id, batches[0])


def test_owner_schema_absence_and_json_clearance_never_grant_availability(db, demand_world, monkeypatch):
    org_id, _, _, own, _, _, _, batches = prepare(db, demand_world)
    own.extra_data = {"available_quantity": "999", "ready_date_actual": TODAY.isoformat(), "holds_checked": True}
    db.flush()
    monkeypatch.setattr(adapter, "resolve_availability", lambda *args: adapter.LotAvailability(Decimal(5), TODAY, ()))
    monkeypatch.setattr(adapter, "resolve_owner", lambda item: (False, None))  # the owner schema is not (yet) trusted
    adapter.assess(db, org_id, {}, today=TODAY)
    current = adapter.latest(db, org_id)
    assert all(row["material_status"] == "blocked" for row in current["batches"])
    fact = current["observations"][0]
    assert not fact["owner_known"] and fact["available_quantity"] is None
    assert "ownership" in " ".join(fact["reasons"])
    assert all(row.forecast_ready_date is None for row in batches)


def test_pending_execution_and_another_planner_request_cannot_clear_unknown_holds(db, demand_world, monkeypatch):
    org_id, _, _, own, _, _, setting, batches = prepare(db, demand_world)
    monkeypatch.setattr(adapter, "resolve_owner", lambda item: (True, None))
    adapter.assess(db, org_id, {}, today=TODAY)
    assert all(row["material_start_date"] is None for row in results(db, org_id))
    execution = ExecutionRepository(db).create_execution(org_id, setting.process_id, commit=False)
    pending = (
        db.query(ExecutionStep).filter(ExecutionStep.org_id == org_id, ExecutionStep.execution_id == execution.id).one()
    )
    pending.actual_inputs = [{"inventory_item_id": str(own.id), "quantity": "2", "unit": "kg"}]
    second = demand_service.create_demand(
        db,
        org_id,
        fixtures.payload(
            setting.source_output_id, reference="Another request", due_date=(TODAY + timedelta(days=2)).isoformat()
        ),
    )
    batch_service.plan_demand(db, org_id, second.id, {}, today=TODAY)
    own.extra_data = {"holds_checked": True, "committed_quantity": "0", "stock_status": "available"}
    db.flush()
    adapter.assess(db, org_id, {}, today=TODAY)
    values = results(db, org_id)
    assert len(values) == 6
    assert all(
        row["material_status"] == "blocked" and not row["allocations"] and row["material_start_date"] is None
        for row in values
    )
    assert own.quantity == Decimal(5) and all(row.forecast_ready_date is None for row in batches)
    assert "commitments" in values[0]["reasons"][0]


@pytest.mark.parametrize(
    "change",
    [
        "foreign",
        "wrong_unit",
        "duplicate",
        "foreign_step",
        "bool_index",
        "unknown_field",
        "invalid_quantity",
        "output_stock",
    ],
)
def test_hostile_bindings_are_rejected_before_persistence(db, demand_world, change):
    org_id, _, step, own, _, foreign, setting, _ = prepare(db, demand_world)
    data = fixtures.setting_payload(
        db, org_id, setting.source_output_id, expected_revision=1, material_lots=[bind(step, own)]
    )
    if change == "foreign":
        data["material_lots"][0]["inventory_item_id"] = str(foreign.id)
    elif change == "wrong_unit":
        own.unit = "g"
    elif change == "duplicate":
        data["material_lots"].append(bind(step, own))
    elif change == "foreign_step":
        data["material_lots"][0]["step_id"] = str(uuid4())
    elif change == "bool_index":
        data["material_lots"][0]["input_index"] = True
    elif change == "unknown_field":
        data["material_lots"][0]["owner_known"] = True
    elif change == "invalid_quantity":
        step.inputs = [{"name": "Sugar", "quantity": "NaN", "unit": "kg"}]
    elif change == "output_stock":
        own.inventory_type = "final_product"
    db.flush()
    with pytest.raises(ValueError):
        batch_service.save_setting(db, org_id, step.process_id, data)
    assert setting.revision == 1


@pytest.mark.parametrize(
    "kind",
    [
        "owner",
        "legacy_owner",
        "unknown_ready",
        "overallocated",
        "nonfinite",
        "different_site",
        "changed_unit",
        "expired_window",
        "unknown_hold",
    ],
)
def test_owner_site_unit_readiness_and_balance_evidence_fails_closed(db, demand_world, monkeypatch, kind):
    org_id, _, _, own, _, _, _, batches = prepare(db, demand_world)
    trusted_boundary(monkeypatch)
    if kind == "owner":
        monkeypatch.setattr(adapter, "resolve_owner", lambda item: (True, uuid4()))
    elif kind == "legacy_owner":
        # A row that predates the contract stock guard: the guard refuses to save this hint through the
        # ORM once the app has registered it, so write it with a direct table update.
        table = InventoryItem.__table__
        db.execute(table.update().where(table.c.id == own.id).values(extra_data={"contract_customer_id": str(uuid4())}))
        db.refresh(own)
    elif kind == "unknown_ready":
        monkeypatch.setattr(
            adapter, "resolve_availability", lambda *args: adapter.LotAvailability(Decimal(5), None, ())
        )
    elif kind == "overallocated":
        monkeypatch.setattr(
            adapter, "resolve_availability", lambda *args: adapter.LotAvailability(Decimal(6), TODAY, ())
        )
    elif kind == "nonfinite":
        monkeypatch.setattr(
            adapter, "resolve_availability", lambda *args: adapter.LotAvailability(Decimal("NaN"), TODAY, ())
        )
    elif kind == "different_site":
        site = Site(org_id=org_id, name="New main site", is_default=True)
        db.add(site)
        db.flush()
        for row in batches:
            row.site_id = site.id
    elif kind == "changed_unit":
        own.unit = "g"
    elif kind == "expired_window":
        own.expiry_date = TODAY - timedelta(days=1)
    elif kind == "unknown_hold":
        own.extra_data = {"on_hold": False, "committed_quantity": "0"}
    db.flush()
    adapter.assess(db, org_id, {}, today=TODAY)
    assert all(row["material_status"] == "blocked" and not row["allocations"] for row in results(db, org_id))


def test_known_readiness_delays_only_material_estimate_and_unknown_output_stays_unknown(db, demand_world, monkeypatch):
    org_id, _, _, own, _, _, _, batches = prepare(db, demand_world)
    own.expiry_date = TODAY + timedelta(days=3)
    trusted_boundary(
        monkeypatch, lambda db, org, item: adapter.LotAvailability(item.quantity, TODAY + timedelta(days=3), ())
    )
    batches[0].snapshot = {**batches[0].snapshot, "readiness_reasons": ["Ready date is entered during production"]}
    db.flush()
    adapter.assess(db, org_id, {}, today=TODAY)
    first = next(row for row in results(db, org_id) if row["batch_id"] == str(batches[0].id))
    assert first["material_status"] == "delayed"
    assert first["material_start_date"] == (TODAY + timedelta(days=3)).isoformat()
    assert first["material_timing_estimate"] is None and first["forecast_ready_date"] is None
    assert all(row.forecast_ready_date is None for row in batches)


def test_missing_mapping_blocks_without_spending_a_known_lot(db, demand_world, monkeypatch):
    org_id, _, _, own, _, _, _, batches = prepare(db, demand_world)
    for batch in batches:
        batch.snapshot = {**batch.snapshot, "material_bindings": []}
    db.flush()
    trusted_boundary(monkeypatch)
    adapter.assess(db, org_id, {}, today=TODAY)
    assert all(
        row["material_status"] == "blocked"
        and not row["allocations"]
        and "Select an exact raw lot" in row["reasons"][0]
        for row in results(db, org_id)
    )
    assert own.quantity == Decimal(5)


def test_external_intermediate_is_not_inferred_from_other_planned_output(db, demand_world, monkeypatch):
    org_id, _, step, _, _, _, setting, batches = prepare(db, demand_world)
    step.inputs = [{"name": "Intermediate", "quantity": "2", "unit": "kg", "source_output_id": str(uuid4())}]
    for batch in batches:
        batch.status = "cancelled"
    db.flush()
    process = (
        db.query(adapter.Process).filter(adapter.Process.org_id == org_id, adapter.Process.id == step.process_id).one()
    )
    db.add(
        ProcessVersion(
            org_id=org_id,
            process_id=step.process_id,
            version_number=2,
            snapshot=batch_service._process_snapshot(process, [step]),
        )
    )
    db.flush()
    batch_service.save_setting(
        db,
        org_id,
        step.process_id,
        fixtures.setting_payload(db, org_id, setting.source_output_id, expected_revision=1, material_lots=[]),
    )
    batch_service.plan_demand(db, org_id, batches[0].demand_id, {}, today=TODAY)
    trusted_boundary(monkeypatch)
    adapter.assess(db, org_id, {}, today=TODAY)
    assert all(
        row["material_status"] == "blocked"
        and row["material_start_date"] is None
        and "intermediate supply is unresolved" in row["reasons"][0]
        for row in results(db, org_id)
    )


def test_changed_workflow_version_marks_prior_observations_stale(db, demand_world):
    org_id, _, step, _, _, _, _, _ = prepare(db, demand_world)
    adapter.assess(db, org_id, {}, today=TODAY)
    version = batch_service.latest_version(db, org_id, step.process_id)
    db.add(ProcessVersion(org_id=org_id, process_id=step.process_id, version_number=2, snapshot=version.snapshot))
    db.flush()
    assert all(row["stale"] for row in results(db, org_id))
    adapter.assess(db, org_id, {}, today=TODAY)
    assert all(
        row["material_status"] == "blocked" and "version changed" in row["reasons"][0] for row in results(db, org_id)
    )


def test_missing_lot_stays_unknown_and_cannot_use_same_named_stock(db, demand_world, monkeypatch):
    org_id, _, _, _, sibling, _, _, batches = prepare(db, demand_world)
    for batch in batches:
        binding = {**batch.snapshot["material_bindings"][0], "inventory_item_id": str(uuid4())}
        batch.snapshot = {**batch.snapshot, "material_bindings": [binding]}
    db.flush()
    trusted_boundary(monkeypatch)
    adapter.assess(db, org_id, {}, today=TODAY)
    assert all(
        row["material_status"] == "blocked" and "no longer available" in row["reasons"][0]
        for row in results(db, org_id)
    )
    assert sibling.quantity == Decimal(100)


def test_assessments_are_historical_and_batch_changes_mark_prior_results_stale(db, demand_world):
    org_id, _, _, _, _, _, _, batches = prepare(db, demand_world)
    first = adapter.assess(db, org_id, {}, today=TODAY)
    first_payload = results(db, org_id)
    batch_service.update_batch(
        db, org_id, batches[0].id, {"action": "priority", "priority": 75, "expected_revision": 1}, today=TODAY
    )
    assert next(row for row in results(db, org_id) if row["batch_id"] == str(batches[0].id))["stale"]
    second = adapter.assess(db, org_id, {}, today=TODAY)
    assert second.sequence == first.sequence + 1
    historical = (
        db.query(PlanningMaterialBatchAssessment)
        .filter(
            PlanningMaterialBatchAssessment.org_id == org_id, PlanningMaterialBatchAssessment.assessment_id == first.id
        )
        .all()
    )
    assert sorted(row.result["batch_revision"] for row in historical) == sorted(
        row["batch_revision"] for row in first_payload
    )
    assert not any(row["stale"] for row in results(db, org_id))


def test_all_batches_share_balance_and_catalog_reads_are_bounded_without_n_plus_one(db, demand_world):
    org_id, _, _, _, _, _, _, _ = prepare(db, demand_world)
    queries = []

    def collect(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", collect)
    try:
        adapter.assess(db, org_id, {}, today=TODAY)
        assert len(queries) == 7
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", collect)


def test_foreign_batch_cannot_be_attached_to_same_org_assessment(db, demand_world):
    org_id, other_id, _, _, _, _, _, batches = prepare(db, demand_world)
    run = PlanningMaterialAssessment(org_id=other_id, sequence=1, observations=[])
    db.add(run)
    db.flush()
    db.add(
        PlanningMaterialBatchAssessment(
            org_id=other_id, assessment_id=run.id, batch_id=batches[0].id, batch_revision=1, result={}
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.fixture
def board_clients(db, base_board_clients):
    yield base_board_clients
    ids = [item[1] for item in base_board_clients]
    db.rollback()
    db.query(PlanningMaterialBatchAssessment).filter(PlanningMaterialBatchAssessment.org_id.in_(ids)).delete(
        synchronize_session=False
    )
    db.query(PlanningMaterialAssessment).filter(PlanningMaterialAssessment.org_id.in_(ids)).delete(
        synchronize_session=False
    )
    db.query(InventoryMovement).filter(InventoryMovement.org_id.in_(ids)).delete(synchronize_session=False)
    db.query(InventoryItem).filter(InventoryItem.org_id.in_(ids)).delete(synchronize_session=False)
    db.commit()


def test_real_api_permission_tenant_and_csrf_boundaries(db, board_clients, flask_app):
    client, org_id, output = board_clients[0]
    other, _, _ = board_clients[1]
    auditor, _, _ = board_clients[2]
    fixtures.configure_http(db, client, output)
    assert requirement_for("planning.assess_materials", "POST") == "production.record"
    assert requirement_for("planning.get_material_assessment", "GET") == "production.view"
    assert auditor.post("/api/core/planner/material-assessments", json={}).status_code == 403
    original = flask_app.config["WTF_CSRF_ENABLED"]
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        from html.parser import HTMLParser

        class Token(HTMLParser):
            value = None

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag == "meta" and values.get("name") == "csrf-token":
                    self.value = values.get("content")

        parser = Token()
        parser.feed(client.get("/core/planner/board").text)
        assert client.post("/api/core/planner/material-assessments", json={}).status_code == 400
        assert (
            client.post(
                "/api/core/planner/material-assessments",
                json={},
                headers={"X-CSRFToken": parser.value, "Referer": "https://localhost/core/planner/board"},
            ).status_code
            == 201
        )
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = original
    assert other.get("/api/core/planner/material-assessments").get_json()["assessment"] is None
    assert auditor.get("/api/core/planner/material-assessments").get_json()["assessment"] is None
    assert client.post("/api/core/planner/material-assessments", json={"available_quantity": "1000"}).status_code == 400
    audit = db.query(AuditLog).filter(AuditLog.org_id == org_id, AuditLog.action == "planning_materials_observed").one()
    assert audit.meta_data["sequence"] == 1 and audit.user_id is not None


def test_api_audit_failure_rolls_back_entire_assessment(db, board_clients, monkeypatch):
    from app.features.planning import routes

    client, org_id, output = board_clients[0]
    demand = fixtures.configure_http(db, client, output)
    client.post("/api/core/planner/demands/" + demand["id"] + "/plan", json={})
    original = routes.AuditLog

    def reject_audit(*args, **kwargs):
        if kwargs.get("action") == "planning_materials_observed":
            raise ValueError("Audit record failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(routes, "AuditLog", reject_audit)
    response = client.post("/api/core/planner/material-assessments", json={})
    assert response.status_code == 400
    assert db.query(PlanningMaterialAssessment).filter(PlanningMaterialAssessment.org_id == org_id).count() == 0
    assert (
        db.query(PlanningMaterialBatchAssessment).filter(PlanningMaterialBatchAssessment.org_id == org_id).count() == 0
    )
    assert db.query(PlanningBatch).filter(PlanningBatch.org_id == org_id).count() == 3


def test_post_returns_its_own_run_when_another_assessment_commits_before_response(db, board_clients, monkeypatch):
    from app.core.db import SessionLocal
    from app.features.planning import routes

    client, org_id, output = board_clients[0]
    demand = fixtures.configure_http(db, client, output)
    client.post("/api/core/planner/demands/" + demand["id"] + "/plan", json={})
    commit = routes.db_session.commit

    def concurrent_commit():
        commit()
        with SessionLocal() as second:
            adapter.assess(second, org_id, {}, today=TODAY)
            second.commit()

    monkeypatch.setattr(routes.db_session, "commit", concurrent_commit)
    response = client.post("/api/core/planner/material-assessments", json={})
    assert response.status_code == 201 and response.get_json()["assessment"]["sequence"] == 1
    assert client.get("/api/core/planner/material-assessments").get_json()["assessment"]["sequence"] == 2
    monkeypatch.setattr(routes.db_session, "commit", commit)


def test_concurrent_observation_requests_preserve_sequence_and_never_reserve_stock(db, demand_world):
    from concurrent.futures import ThreadPoolExecutor

    from app.core.db import SessionLocal

    org_id, _, _, own, _, _, _, _ = prepare(db, demand_world)
    lot_id = own.id
    db.commit()

    def observe():
        with SessionLocal() as session:
            run = adapter.assess(session, org_id, {}, today=TODAY)
            sequence = run.sequence
            session.commit()
            return sequence

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: observe(), range(2))) == [1, 2]
        assert db.query(InventoryItem).filter(
            InventoryItem.org_id == org_id, InventoryItem.id == lot_id
        ).one().quantity == Decimal(5)
        assert all(row["material_start_date"] is None for row in results(db, org_id))
    finally:
        db.rollback()
        identities = demand_world[:2]
        for model in (PlanningMaterialBatchAssessment, PlanningMaterialAssessment, InventoryMovement, InventoryItem):
            db.query(model).filter(model.org_id.in_(identities)).delete(synchronize_session=False)
        db.commit()
        fixtures._cleanup_world(db, identities)
