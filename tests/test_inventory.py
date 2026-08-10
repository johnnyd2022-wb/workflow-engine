"""Regression tests for the core inventory audit (review-feature, spec .agents/specs/inventory.md).

This file holds two kinds of test, and the distinction matters — test-evaluator graded an
earlier version `invalid` partly for blurring it:

- **Regressions**, marked `[REGRESSION]`. Each was verified RED against the code at the
  audit baseline (branch work/2026-07-27-session, base 8d95f83) and reproduces a specific
  finding from `.agents/reports/inventory/security-audit.md`.
- **Positive controls**, marked `[CONTROL]`. These pass both before and after the fix.
  They exist to catch over-tightening — a validator that rejects everything would satisfy
  every regression here and break the product. `test_adjust_rejects_infinity_with_400` is
  one of these despite looking like a regression: `Decimal("Infinity") < 0` is False, so
  the pre-fix code already reached `coerce_stored_quantity`'s finite check and returned a
  400. The `is_finite()` guard moved where that 400 comes from, not whether it happens.

The headline one is F1: `POST /api/core/inventory` accepted client-supplied
`source_execution_id` / `source_execution_step_id` / `source_output_id` without checking
they belonged to the caller's org, and `DagTraversal._enrich_items_bulk` then fetched
those rows with no org filter — so org A could plant a reference to org B's execution
step and read org B's process data (prompts, inputs, outputs, process name) back out of
its own trace response. Two independent layers are fixed and both are tested here: the
write-side rejection AND the read-side scoping, because the read-side scoping is the
thing that would have contained the blast radius on day one.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.api_idempotency_key import ApiIdempotencyKey
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.organisation import Organisation
from app.core.security.auth_service import AuthService
from app.core.security.tenant_scope import unscoped
from tests.factories import (
    ExecutionFactory,
    InventoryItemFactory,
    OrganisationFactory,
    ProcessFactory,
)


@pytest.fixture
def org(db):
    organisation = OrganisationFactory(name=f"Inventory Audit Org {uuid4()}")
    db.commit()
    org_id = organisation.id
    yield organisation
    db.rollback()
    _purge_org(db, org_id)


@pytest.fixture
def other_org(db):
    """A hostile neighbour org — the one whose data must never surface in `org`'s responses."""
    organisation = OrganisationFactory(name=f"Inventory Audit Neighbour {uuid4()}")
    db.commit()
    org_id = organisation.id
    yield organisation
    db.rollback()
    _purge_org(db, org_id)


def _purge_org(db, org_id):
    """Remove org children that are ON DELETE NO ACTION before the org itself.

    Same ordering rationale as tests/test_wastage.py: deleting the org cascades users and
    audit rows, but inventory/wastage/movement/idempotency rows must go first. These tests
    also build processes and executions (to get a real cross-org ExecutionStep), so the
    process graph has to come down too — steps and version rows before the process.

    Failures here are swallowed deliberately: a teardown that raises leaves the org row
    behind, and the NEXT run then dies in fixture *setup* on the unique org-name
    constraint, which reads as an unrelated failure and hides whatever the real one was.
    """
    from app.core.db.models.entity_event_summary import EntityEventSummary
    from app.core.db.models.execution import Execution
    from app.core.db.models.process import Process
    from app.core.db.models.process_version import ProcessVersion
    from app.core.db.models.step import Step

    try:
        for model in (InventoryMovement, InventoryWastage, ApiIdempotencyKey, EntityEventSummary, InventoryItem):
            db.query(model).filter(model.org_id == org_id).delete(synchronize_session=False)
        exec_ids = [e.id for e in db.query(Execution).filter(Execution.org_id == org_id).all()]
        if exec_ids:
            db.query(ExecutionStep).filter(ExecutionStep.execution_id.in_(exec_ids)).delete(synchronize_session=False)
        db.query(Execution).filter(Execution.org_id == org_id).delete(synchronize_session=False)
        proc_ids = [p.id for p in db.query(Process).filter(Process.org_id == org_id).all()]
        if proc_ids:
            db.query(Step).filter(Step.process_id.in_(proc_ids)).delete(synchronize_session=False)
        db.query(ProcessVersion).filter(ProcessVersion.org_id == org_id).delete(synchronize_session=False)
        db.query(Process).filter(Process.org_id == org_id).delete(synchronize_session=False)
        db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


@pytest.fixture
def user(db, org):
    from app.core.db.repositories.user_repo import UserRepository

    u = UserRepository(db).create_user(
        org_id=org.id,
        email=f"inv_{uuid4()}@test.com",
        password_hash=AuthService.hash_password("TestPass123!"),
    )
    db.commit()
    yield u


@pytest.fixture
def app_client(db, org, user):
    """Authenticated Flask test client scoped to `org`."""
    from app.api.app_factory import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.test_client() as client:
        client.environ_base["wsgi.url_scheme"] = "https"
        client.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
        with flask_app.app_context():
            resp = client.post(
                "/auth/login",
                json={"email": user.email, "password": "TestPass123!"},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


def _plant_item_with_foreign_ref(db, org_id, name, execution_id=None, step_id=None):
    """Write an inventory row whose provenance FK points at ANOTHER org, below the repository.

    The repository now refuses this shape, which is the point of the write-side fix — so a
    test for the READ-side layer has to get underneath it. That is not a contrived setup:
    rows created before the fix shipped are exactly this shape and are already in the
    database. The read side has to hold on its own for those rows.

    The quantity write still goes through `allow_inventory_quantity_write`, because the DB
    trigger rejects an unguarded INSERT outright (AC11) — bypassing the repository does not
    mean bypassing the quantity guard.
    """
    from app.core.domain.inventory_quantity_guard import (
        InventoryQuantityWriteReason,
        allow_inventory_quantity_write,
    )

    with allow_inventory_quantity_write(InventoryQuantityWriteReason.REPOSITORY_CREATE):
        item = InventoryItem(
            org_id=org_id,
            name=name,
            quantity=Decimal("5"),
            unit="kg",
            inventory_type="raw_material",
            source_execution_id=execution_id,
            source_execution_step_id=step_id,
            extra_data={},
        )
        db.add(item)
        db.commit()
    return item


def _foreign_execution_step(db, other_org, name_prefix="Neighbour Secret"):
    """A real ExecutionStep in `other_org` carrying data that must never cross the tenant line.

    Also used with the caller's OWN org to build the positive control that proves enrichment
    runs at all — hence the name_prefix, so the two cases can't collide on process name.
    """
    from app.core.db.models.step import Step

    process = ProcessFactory(org_id=other_org.id, name=f"{name_prefix} Process {uuid4()}")
    db.commit()
    # ProcessFactory creates the process and its first version but no steps, and
    # create_execution derives one ExecutionStep per Step — so without this the execution
    # has no steps to reference and the test would silently assert nothing.
    db.add(
        Step(
            org_id=other_org.id,
            process_id=process.id,
            step_number=1,
            # chk_steps_position_grid requires position > 0 AND MOD(position, 1000) = 0 —
            # the 1000-unit grid that leaves room for fractional drag/drop inserts.
            position=1000,
            name=f"{name_prefix} Step",
            inputs=[],
            outputs=[],
            execution_prompts=[],
        )
    )
    db.commit()
    execution = ExecutionFactory(org_id=other_org.id, process_id=process.id)
    db.commit()
    step = (
        db.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.step_number)
        .first()
    )
    return process, execution, step


# --------------------------------------------------------------------------------------
# F1 — cross-tenant FK injection (write side) and unscoped trace enrichment (read side)
# --------------------------------------------------------------------------------------


def test_create_item_rejects_source_execution_id_from_another_org(db, app_client, org, other_org):
    """[REGRESSION] F1 step 1: the write side must refuse to reference another org's execution."""
    process = ProcessFactory(org_id=other_org.id)
    foreign_execution = ExecutionFactory(org_id=other_org.id, process_id=process.id)
    db.commit()

    resp = app_client.post(
        "/api/core/inventory",
        json={
            "name": "Poisoned Item",
            "quantity": "5",
            "unit": "kg",
            "source_execution_id": str(foreign_execution.id),
        },
    )

    assert resp.status_code == 400, resp.data
    assert "not found" in resp.get_json()["error"].lower()
    # And nothing was written.
    assert db.query(InventoryItem).filter(InventoryItem.name == "Poisoned Item").count() == 0


def test_create_item_rejects_source_execution_step_id_from_another_org(db, app_client, org, other_org):
    """[REGRESSION] F1 step 1, the step FK — the one that actually carries the leaked payload."""
    _process, _execution, foreign_step = _foreign_execution_step(db, other_org)
    assert foreign_step is not None, "fixture must produce a real execution step to reference"

    resp = app_client.post(
        "/api/core/inventory",
        json={
            "name": "Poisoned Item Step",
            "quantity": "5",
            "unit": "kg",
            "source_execution_step_id": str(foreign_step.id),
        },
    )

    assert resp.status_code == 400, resp.data
    assert db.query(InventoryItem).filter(InventoryItem.name == "Poisoned Item Step").count() == 0


def test_cross_tenant_reference_rejection_emits_access_denied(db, app_client, org, other_org, caplog):
    """[REGRESSION] A rejected cross-tenant reference must be observable.

    The route turns the refusal into an ordinary 400, so without an explicit log line a
    tenant-boundary probe leaves no trace and prod-sentinel has nothing to find. The event
    name matches the one the auth decorators emit (`access_denied`), so a single query
    covers both surfaces. Mutation this catches: dropping the `_deny(...)` call and keeping
    only the `raise`.
    """
    import logging

    process = ProcessFactory(org_id=other_org.id)
    foreign_execution = ExecutionFactory(org_id=other_org.id, process_id=process.id)
    db.commit()

    with caplog.at_level(logging.WARNING):
        resp = app_client.post(
            "/api/core/inventory",
            json={
                "name": "Probe Item",
                "quantity": "5",
                "unit": "kg",
                "source_execution_id": str(foreign_execution.id),
            },
        )

    assert resp.status_code == 400, resp.data
    denials = [r for r in caplog.records if "access_denied" in r.getMessage()]
    assert denials, f"cross-tenant rejection was not logged: {[r.getMessage() for r in caplog.records]}"
    logged = denials[0].getMessage()
    assert "cross_org_source_execution" in logged, logged


def test_create_item_accepts_own_org_source_execution(db, app_client, org):
    """[CONTROL] The rejection above must not break the legitimate in-flow case it exists to allow."""
    process = ProcessFactory(org_id=org.id)
    own_execution = ExecutionFactory(org_id=org.id, process_id=process.id)
    db.commit()

    resp = app_client.post(
        "/api/core/inventory",
        json={
            "name": "Legitimate Output",
            "quantity": "5",
            "unit": "kg",
            "source_execution_id": str(own_execution.id),
        },
    )

    assert resp.status_code == 201, resp.data
    # Status alone would pass even if the reference were silently dropped.
    stored = db.query(InventoryItem).filter(InventoryItem.id == UUID(resp.get_json()["id"])).one()
    assert stored.source_execution_id == own_execution.id


def test_create_item_rejects_source_output_id_without_a_step(db, app_client, org):
    """[REGRESSION] F1, third reference. `source_output_id` is `steps.outputs[].id` in JSONB
    with no FK, so there is nothing to join against — an id with no step is unverifiable and
    must be refused rather than trusted. test-evaluator caught that the first fix validated
    the two FK columns and left this one arbitrary."""
    resp = app_client.post(
        "/api/core/inventory",
        json={
            "name": "Orphan Output Ref",
            "quantity": "5",
            "unit": "kg",
            "source_output_id": str(uuid4()),
        },
    )

    assert resp.status_code == 400, resp.data
    assert db.query(InventoryItem).filter(InventoryItem.name == "Orphan Output Ref").count() == 0


def test_create_item_rejects_source_output_id_from_another_orgs_step(db, app_client, org, other_org):
    """[REGRESSION] F1: an output id belonging to a neighbour's step, with that step's id."""
    _process, _execution, foreign_step = _foreign_execution_step(db, other_org)

    resp = app_client.post(
        "/api/core/inventory",
        json={
            "name": "Foreign Output Ref",
            "quantity": "5",
            "unit": "kg",
            "source_execution_step_id": str(foreign_step.id),
            "source_output_id": str(uuid4()),
        },
    )

    assert resp.status_code == 400, resp.data
    assert db.query(InventoryItem).filter(InventoryItem.name == "Foreign Output Ref").count() == 0


def test_create_item_rejects_source_output_id_not_declared_by_its_own_step(db, app_client, org):
    """[REGRESSION] The membership check itself, on an OWNED step.

    The foreign-step case above is rejected earlier, at step ownership — so it never
    reaches the membership condition and cannot guard it. test-evaluator proved that by
    mutation: delete the membership check and every other source_output_id test stays
    green while arbitrary output ids become accepted for owned steps. This is the test
    that goes red for that mutation.
    """
    from app.core.db.models.step import Step

    _process, execution, step = _foreign_execution_step(db, org, name_prefix="Own Membership")
    step_def = db.query(Step).filter(Step.id == step.step_id).one()
    step_def.outputs = [{"id": str(uuid4()), "name": "Declared Output", "quantity": 5, "unit": "kg"}]
    db.commit()

    undeclared_output_id = str(uuid4())
    resp = app_client.post(
        "/api/core/inventory",
        json={
            "name": "Undeclared Output Ref",
            "quantity": "5",
            "unit": "kg",
            "source_execution_id": str(execution.id),
            "source_execution_step_id": str(step.id),
            "source_output_id": undeclared_output_id,
        },
    )

    assert resp.status_code == 400, resp.data
    assert "not an output of that execution step" in resp.get_json()["error"]
    assert db.query(InventoryItem).filter(InventoryItem.name == "Undeclared Output Ref").count() == 0


def test_create_item_accepts_own_org_source_output_id(db, app_client, org):
    """[CONTROL] A real output id from the caller's own step must still be accepted —
    otherwise the validator above has simply broken the in-flow 'add missing output' path."""
    from app.core.db.models.step import Step

    _process, execution, step = _foreign_execution_step(db, org, name_prefix="Own Output")
    step_def = db.query(Step).filter(Step.id == step.step_id).one()
    output_id = str(uuid4())
    step_def.outputs = [{"id": output_id, "name": "Distillate", "quantity": 5, "unit": "kg"}]
    db.commit()

    resp = app_client.post(
        "/api/core/inventory",
        json={
            "name": "Distillate",
            "quantity": "5",
            "unit": "kg",
            "source_execution_id": str(execution.id),
            "source_execution_step_id": str(step.id),
            "source_output_id": output_id,
        },
    )

    assert resp.status_code == 201, resp.data
    stored = db.query(InventoryItem).filter(InventoryItem.id == UUID(resp.get_json()["id"])).one()
    assert str(stored.source_output_id) == output_id


def test_trace_enrichment_enriches_own_org_step_data(db, app_client, org):
    """[CONTROL] Enrichment must actually run for in-org provenance.

    This is the control that gives the leak test below its teeth. Without it, a change that
    disabled `_enrich_items_bulk` entirely would return a clean 200 with none of the
    neighbour's strings in it — and the leak test would call that a pass.
    """
    process, execution, step = _foreign_execution_step(db, org, name_prefix="Own")
    step.execution_data = {"own_prompt": "our own visible prompt"}
    step.actual_inputs = [{"name": "our own input", "quantity": "7"}]
    db.commit()

    item = _plant_item_with_foreign_ref(
        db, org.id, "Own Item", execution_id=execution.id, step_id=step.id
    )

    resp = app_client.get(f"/api/core/inventory/trace/{item.id}")

    assert resp.status_code == 200, resp.data
    body = resp.get_data(as_text=True)
    assert "our own visible prompt" in body, "enrichment did not run — the leak test below would be vacuous"
    assert "our own input" in body
    assert process.name in body


def test_trace_enrichment_does_not_leak_another_orgs_step_data(db, app_client, org, other_org):
    """[REGRESSION] F1 step 2: a poisoned FK already in the DB must not enrich across orgs.

    The FK is planted below the repository — bypassing the write-side fix — precisely
    because this asserts the *second* layer. If the read side is ever the only thing standing
    between a tenant and its neighbour's process data, it has to hold on its own.

    BOTH provenance references are planted. Process-name enrichment follows
    `source_execution_id`, so asserting the neighbour's process name is absent while only
    planting the step id would be tautological — it could never appear, fixed or not.
    (test-evaluator caught exactly that in the first version of this test.)
    """
    process, execution, foreign_step = _foreign_execution_step(db, other_org)
    foreign_step.execution_data = {"secret_prompt": "neighbour proprietary botanical ratio"}
    foreign_step.actual_inputs = [{"name": "secret input", "quantity": "42"}]
    db.commit()

    raw_material = _plant_item_with_foreign_ref(
        db, org.id, "Planted Item", execution_id=execution.id, step_id=foreign_step.id
    )

    resp = app_client.get(f"/api/core/inventory/trace/{raw_material.id}")

    assert resp.status_code == 200, resp.data
    payload = resp.get_json()
    # Prove the endpoint really returned our item, so absence below means "not leaked"
    # rather than "returned nothing at all".
    traced_ids = {i["id"] for i in payload["all_items"]}
    assert str(raw_material.id) in traced_ids, f"planted item missing from trace: {payload}"
    # The item carries both foreign references, so enrichment definitely had something to
    # follow — process_name staying None is the scoping working, not an absent input.
    planted = next(i for i in payload["all_items"] if i["id"] == str(raw_material.id))
    assert planted["source_execution_step_id"] == str(foreign_step.id)
    assert planted["process_name"] is None

    body = resp.get_data(as_text=True)
    assert "neighbour proprietary botanical ratio" not in body
    assert "secret input" not in body
    assert process.name not in body


def test_list_inventory_by_process_id_does_not_match_another_orgs_execution(db, app_client, org, other_org):
    """[REGRESSION] F4: the process_id filter joined Execution without an org constraint.

    test-evaluator (round 2) caught that this test had no same-org positive control: an
    implementation that returns nothing for ANY process_id filter (foreign or otherwise)
    would also pass. `Own Process Item` is that control — it must appear so absence of the
    foreign item means "filtered correctly", not "the filter is broken/empty for everyone".
    """
    own_process = ProcessFactory(org_id=org.id)
    own_execution = ExecutionFactory(org_id=org.id, process_id=own_process.id)
    db.commit()
    _plant_item_with_foreign_ref(db, org.id, "Own Process Item", execution_id=own_execution.id)

    foreign_process = ProcessFactory(org_id=other_org.id)
    foreign_execution = ExecutionFactory(org_id=other_org.id, process_id=foreign_process.id)
    db.commit()
    _plant_item_with_foreign_ref(db, org.id, "Cross Joined Item", execution_id=foreign_execution.id)

    resp = app_client.get(f"/api/core/inventory?process_id={own_process.id}")
    assert resp.status_code == 200, resp.data
    own_names = [i["name"] for i in resp.get_json().get("inventory_items", [])]
    assert "Own Process Item" in own_names, "filtering by the caller's own process_id must still match"

    resp = app_client.get(f"/api/core/inventory?process_id={foreign_process.id}")
    assert resp.status_code == 200, resp.data
    names = [i["name"] for i in resp.get_json().get("inventory_items", [])]
    assert "Cross Joined Item" not in names, "filtering by a foreign org's process_id must match nothing"


# --------------------------------------------------------------------------------------
# F2 / F3 — non-finite and out-of-range quantities must be 400s, not 500s
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad_quantity", ["nan", "NaN", "-nan"])
def test_adjust_rejects_non_finite_quantity_with_400(db, app_client, org, bad_quantity):
    """[REGRESSION] F2: float("nan") <= 0 is False, so "nan" passed the route gate; Decimal("NaN") < 0
    then raised InvalidOperation — which is NOT a ValueError, so the route's only handler
    missed it and Flask returned a non-JSON 500 with nothing in the structured log."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(f"/api/core/inventory/{item.id}/adjust", json={"new_quantity": bad_quantity})

    assert resp.status_code == 400, resp.data
    assert resp.is_json, "error responses must stay JSON — a 500 here breaks the API contract"
    db.expire_all()
    assert db_session().get(InventoryItem, item.id).quantity == Decimal("10")


def test_adjust_rejects_infinity_with_400(db, app_client, org):
    """[CONTROL] Not a regression: `Decimal("Infinity") < 0` is False, so the pre-fix code
    already fell through to `coerce_stored_quantity`'s finite check and returned 400. The
    `is_finite()` guard changed where that 400 comes from, not whether it happens."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(f"/api/core/inventory/{item.id}/adjust", json={"new_quantity": "Infinity"})

    assert resp.status_code == 400, resp.data
    assert resp.is_json


def test_create_rejects_huge_exponent_quantity_with_400(db, app_client, org):
    """[REGRESSION] F3: Decimal("1e400") is finite and parses, but quantizing it to 4dp needs ~404
    significant digits and raises InvalidOperation outside coerce_stored_quantity's try."""
    resp = app_client.post(
        "/api/core/inventory",
        json={"name": "Huge Item", "quantity": "1e400", "unit": "kg"},
    )

    assert resp.status_code == 400, resp.data
    assert db.query(InventoryItem).filter(InventoryItem.name == "Huge Item").count() == 0


def test_update_rejects_huge_exponent_quantity_with_400(db, app_client, org):
    """[REGRESSION] F3 also applies to PUT /api/core/inventory/<id> (update), not just
    create — the same coerce_stored_quantity path backs both. test-evaluator's coverage
    review named this route as untested for the huge-exponent case."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.put(
        f"/api/core/inventory/{item.id}",
        # name/unit are required fields on this route independent of the quantity bug —
        # omitting them would 400 for the wrong reason and make this test vacuous.
        json={"name": item.name, "unit": item.unit, "quantity": "1e400"},
    )

    assert resp.status_code == 400, resp.data
    assert "error" in resp.get_json()
    db.expire_all()
    assert db_session().get(InventoryItem, item.id).quantity == Decimal("10")


def test_adjust_accepts_a_normal_quantity(db, app_client, org):
    """[CONTROL] Guard against over-tightening the validation above."""
    item = InventoryItemFactory(org_id=org.id, quantity="10", unit="kg")
    db.commit()

    resp = app_client.post(f"/api/core/inventory/{item.id}/adjust", json={"new_quantity": "2.5"})

    assert resp.status_code == 200, resp.data
    db.expire_all()
    assert db_session().get(InventoryItem, item.id).quantity == Decimal("2.5000")


# --------------------------------------------------------------------------------------
# F6 — inventory_type is an unconstrained String(50) the routes never validated
# --------------------------------------------------------------------------------------


def test_create_rejects_unknown_inventory_type(db, app_client, org):
    """[REGRESSION] F6: an item stored with an off-enum type silently disappears from every exact-match
    view, including /out-of-stock — the recall-tracing view. Found because the E2E stage's
    own helper passes "RAW_MATERIAL" (uppercase) and the item vanished."""
    resp = app_client.post(
        "/api/core/inventory",
        json={"name": "Wrong Type Item", "quantity": "5", "unit": "kg", "inventory_type": "RAW_MATERIAL"},
    )

    assert resp.status_code == 400, resp.data
    assert "inventory_type" in resp.get_json()["error"]
    assert db.query(InventoryItem).filter(InventoryItem.name == "Wrong Type Item").count() == 0


def test_create_accepts_every_valid_inventory_type(db, app_client, org):
    """[CONTROL] see above. test-evaluator (round 2): a 201 alone does not prove the
    supplied type was preserved rather than silently coerced/defaulted — assert the
    stored row's inventory_type matches exactly what was sent."""
    for value in ("raw_material", "work_in_progress", "final_product"):
        resp = app_client.post(
            "/api/core/inventory",
            json={"name": f"Typed {value}", "quantity": "5", "unit": "kg", "inventory_type": value},
        )
        assert resp.status_code == 201, resp.data
        stored = db.query(InventoryItem).filter(InventoryItem.id == UUID(resp.get_json()["id"])).one()
        assert stored.inventory_type == value


# --------------------------------------------------------------------------------------
# F5 — the CSV raw-body path never enforced the endpoint's own documented 2MB limit
# --------------------------------------------------------------------------------------


def test_csv_validate_raw_body_enforces_csv_size_limit(db, app_client, org):
    """[REGRESSION] F5: only the multipart branch checked CSV_MAX_BYTES; the raw-body branch inherited
    MAX_CONTENT_LENGTH, a cap owned by evidence-upload config and 5x larger."""
    oversized = "Item Name,Quantity,Unit\n" + ("widget,1,kg\n" * 250_000)
    assert len(oversized.encode("utf-8")) > 2 * 1024 * 1024

    resp = app_client.post(
        "/api/core/inventory/csv-validate",
        data=oversized,
        content_type="text/csv",
    )

    assert resp.status_code == 400, resp.status_code
    assert "2MB" in resp.get_json()["error"]


def test_csv_validate_raw_body_rejects_invalid_utf8(db, app_client, org):
    """[REGRESSION] AC20 was an implementation gap, not just missing coverage.

    `request.get_data(as_text=True)` decodes with errors="replace", so invalid bytes became
    U+FFFD and the upload proceeded — while the multipart branch returned 400 for the same
    input. Silently mangling an item name is the worst outcome for a traceability product.
    """
    resp = app_client.post(
        "/api/core/inventory/csv-validate",
        data=b"Item Name,Quantity,Unit\nWidget,5,kg\n\xff\xfe",
        content_type="text/csv",
    )

    assert resp.status_code == 400, resp.data
    assert "UTF-8" in resp.get_json()["error"]


def test_csv_validate_raw_body_accepts_valid_utf8(db, app_client, org):
    """[CONTROL] Non-ASCII but valid UTF-8 must still be accepted, with the name intact."""
    resp = app_client.post(
        "/api/core/inventory/csv-validate",
        data="Item Name,Quantity,Unit\nJuniperus commūnis,5,kg\n".encode(),
        content_type="text/csv",
    )

    assert resp.status_code == 200, resp.data
    assert resp.get_json()["rows"][0]["name"] == "Juniperus commūnis"


def test_csv_commit_records_acting_user_in_audit_history(db, app_client, org, user):
    """AC25: every CSV-created item's inventory_audit_history entry must carry the acting
    user, alongside source_method/row_index (already covered) and a UTC timestamp.

    `GET /api/core/inventory` deliberately strips `user_id` from audit-history entries in
    its list response (`_bound_inventory_extra_data_for_list_response`, backend.py — an
    "operator UI only" redaction), so that half of AC25 can only be proven by reading the
    row directly — this is the DB-level counterpart to
    test_csv_commit_happy_path_creates_item_with_audit_history in
    tests/e2e/test_inventory_csv_flow.py, which proves the rest of the entry via the API.
    """
    name = f"CSV Audit User {uuid4()}"
    before = datetime.now(UTC) - timedelta(seconds=1)
    resp = app_client.post(
        "/api/core/inventory/csv-commit",
        json={"rows": [{"row_index": 2, "name": name, "quantity": "10", "unit": "kg"}]},
    )
    assert resp.status_code == 200, resp.data
    created_id = UUID(resp.get_json()["created"][0]["id"])

    stored = db.query(InventoryItem).filter(InventoryItem.id == created_id).one()
    entry = stored.extra_data["inventory_audit_history"][-1]
    assert entry["user_id"] == str(user.id), "AC25 requires the acting user on every CSV-created audit entry"
    # Parsed, not just suffix-checked: `endswith("Z")` is satisfied by the literal string
    # "Z" (test-evaluator round 3). Pin it to the actual request window instead.
    stamped = datetime.strptime(entry["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert before <= stamped <= datetime.now(UTC) + timedelta(seconds=1), (
        f"AC25 timestamp {entry['timestamp_utc']!r} is outside the request window"
    )


# --------------------------------------------------------------------------------------
# AC31/AC32 — reconcile via-execution (Path B): success path and cross-org isolation.
# `tests/test_reconciliation_routes.py` covers Path B's six 400 request-validation paths
# but never a success, and never a cross-org id — disclosed gaps in
# .agents/reports/inventory/review.md ("AC31/AC32 — reconcile via-execution (Path B),
# declared out of scope by the router[-focused test batch]").
# --------------------------------------------------------------------------------------


def _process_with_one_step(db, org_id, name_prefix="Recon"):
    """A real Process + Step, org-scoped — the minimum Path B needs to complete a step."""
    from app.core.db.models.step import Step

    process = ProcessFactory(org_id=org_id, name=f"{name_prefix} Process {uuid4()}")
    db.commit()
    step = Step(
        org_id=org_id,
        process_id=process.id,
        step_number=1,
        # chk_steps_position_grid requires position > 0 AND MOD(position, 1000) = 0.
        position=1000,
        name=f"{name_prefix} Step",
        inputs=[],
        outputs=[],
        execution_prompts=[],
    )
    db.add(step)
    db.commit()
    return process, step


def test_reconcile_via_execution_creates_execution_and_reduces_untracked_balance(db, app_client, org):
    """AC31: Path B requires untracked_item_id, process_id, step_id, output name, quantity
    and unit, and on success maps the untracked item onto a newly created execution output.
    Nothing anywhere in the suite exercises this success path — only its 400s."""
    process, step = _process_with_one_step(db, org.id)
    untracked = InventoryItemFactory(
        org_id=org.id, name="Untracked Widget", quantity="5", unit="kg", extra_data={"untracked": True}
    )
    db.commit()
    # Capture plain values: the request's teardown detaches these ORM objects (same trap
    # documented on the `org` fixture above), so touching .id on them afterwards raises
    # DetachedInstanceError rather than reading a stale value.
    untracked_id, process_id, step_id = untracked.id, process.id, step.id

    resp = app_client.post(
        "/api/core/inventory/reconcile/via-execution",
        json={
            "untracked_item_id": str(untracked_id),
            "process_id": str(process_id),
            "step_id": str(step_id),
            "output_name": "Reconciled Output",
            "output_quantity": 5,
            "output_unit": "kg",
        },
    )

    assert resp.status_code == 201, resp.data
    body = resp.get_json()
    assert body["inventory_created"] is True
    assert Decimal(body["reconciled_amount"]) == Decimal("5")
    assert Decimal(body["remaining_untracked_balance"]) == Decimal("0")

    refreshed_untracked = db.query(InventoryItem).filter(InventoryItem.id == untracked_id).one()
    assert refreshed_untracked.quantity == Decimal("0")
    created = (
        db.query(InventoryItem).filter(InventoryItem.org_id == org.id, InventoryItem.name == "Reconciled Output").one()
    )
    assert created.quantity == Decimal("5")
    assert str(created.source_execution_id) == body["execution_id"]


def test_reconcile_via_execution_rejects_untracked_item_id_from_another_org(db, app_client, org, other_org):
    """AC32: an untracked_item_id belonging to another org must not resolve — no execution
    or inventory row created against the caller's org from a neighbour's id."""
    process, step = _process_with_one_step(db, org.id)
    foreign_untracked = InventoryItemFactory(
        org_id=other_org.id, name="Neighbour Untracked", quantity="5", unit="kg", extra_data={"untracked": True}
    )
    db.commit()
    foreign_untracked_id, process_id, step_id = foreign_untracked.id, process.id, step.id

    resp = app_client.post(
        "/api/core/inventory/reconcile/via-execution",
        json={
            "untracked_item_id": str(foreign_untracked_id),
            "process_id": str(process_id),
            "step_id": str(step_id),
            "output_name": "Should Not Exist",
            "output_quantity": 5,
            "output_unit": "kg",
        },
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "Untracked item not found"
    # Verifying a NEIGHBOUR org's row deliberately reads across the tenant line -- the global
    # filter would otherwise scope this query to whatever org app_client's login left active
    # (see tenant_scope.py), hiding the very row this assertion needs to see.
    with unscoped():
        refreshed_foreign = db.query(InventoryItem).filter(InventoryItem.id == foreign_untracked_id).one()
    assert refreshed_foreign.quantity == Decimal("5"), "neighbour's item must be untouched"
    from app.core.db.models.execution import Execution

    assert db.query(Execution).filter(Execution.process_id == process_id).count() == 0, (
        "a rejected reconciliation must not create an execution"
    )


def test_reconcile_via_execution_rejects_process_id_from_another_org(db, app_client, org, other_org):
    """AC32/AC33: a process_id belonging to another org must not resolve — never a 500
    that leaks a stack trace, never an execution created against the wrong tenant's
    process graph.

    [REGRESSION] `create_execution` raises a bare `ValueError` for a cross-org
    process_id, and `reconcile_via_execution` re-raised it uncaught — an unhandled
    exception through the route, not the 400 every other id-ownership check on this
    surface returns. Fixed by catching that ValueError in reconciliation_service.py and
    returning the same "not found or access denied" shape as the untracked-item check
    right above it.
    """
    foreign_process, foreign_step = _process_with_one_step(db, other_org.id, name_prefix="Neighbour")
    untracked = InventoryItemFactory(
        org_id=org.id, name="Untracked Widget", quantity="5", unit="kg", extra_data={"untracked": True}
    )
    db.commit()
    untracked_id, foreign_process_id, foreign_step_id = untracked.id, foreign_process.id, foreign_step.id

    resp = app_client.post(
        "/api/core/inventory/reconcile/via-execution",
        json={
            "untracked_item_id": str(untracked_id),
            "process_id": str(foreign_process_id),
            "step_id": str(foreign_step_id),
            "output_name": "Should Not Exist",
            "output_quantity": 5,
            "output_unit": "kg",
        },
    )

    assert resp.status_code == 400, resp.data
    assert resp.get_json()["error"] == "Process not found or access denied"
    body_text = resp.get_data(as_text=True)
    assert "Traceback" not in body_text
    refreshed_untracked = db.query(InventoryItem).filter(InventoryItem.id == untracked_id).one()
    assert refreshed_untracked.quantity == Decimal("5"), "no partial reconciliation on a rejected process"
    from app.core.db.models.execution import Execution

    assert db.query(Execution).filter(Execution.process_id == foreign_process_id).count() == 0


# --------------------------------------------------------------------------------------
# EntityEventSummary.org_id — disclosed as a gap in .agents/reports/inventory/review.md:
# "defense-in-depth only; security-audit established the pre-fix query was not
# exploitable" (entity_id is entity_event_summaries' primary key, so the org_id filter
# on the list_inventory_items enrichment query at backend.py:2691 is redundant given the
# item ids it filters on are already org-scoped — but the enrichment path itself, the
# `event_summary` field on GET /api/core/inventory, had zero test coverage before this).
# --------------------------------------------------------------------------------------


def test_list_inventory_enriches_items_with_their_own_org_event_summary(db, app_client, org, other_org):
    """GET /api/core/inventory attaches event_summary (from entity_event_summaries, kept
    current by EventWriter on every inventory_item event) to each item in the response,
    and only ever the caller's own org's summaries — never a neighbour's, even though the
    enrichment query joins by entity_id across the whole table."""
    item = InventoryItemFactory(org_id=org.id, name="Summarized Item", quantity="5", unit="kg")
    neighbour_item = InventoryItemFactory(org_id=other_org.id, name="Neighbour Item", quantity="5", unit="kg")
    db.commit()
    item_id, neighbour_item_id = item.id, neighbour_item.id

    from app.core.db.models.entity_event_summary import EntityEventSummary

    own_summary = db.query(EntityEventSummary).filter(EntityEventSummary.entity_id == item_id).one()
    assert own_summary.org_id == org.id, "creating an item must upsert its own org-scoped summary row"
    neighbour_summary = db.query(EntityEventSummary).filter(EntityEventSummary.entity_id == neighbour_item_id).one()
    assert neighbour_summary.org_id == other_org.id

    resp = app_client.post(
        f"/api/core/inventory/{item_id}/adjust",
        json={"new_quantity": "8"},
    )
    assert resp.status_code == 200, resp.data

    resp = app_client.get("/api/core/inventory")
    assert resp.status_code == 200, resp.data
    by_id = {row["id"]: row for row in resp.get_json()["inventory_items"]}
    assert str(item_id) in by_id, "the caller's own item must be in its own org's list"
    assert by_id[str(item_id)]["event_summary"] is not None, (
        "the enrichment query must attach the item's own event summary"
    )
    neighbour_ids = {row["id"] for row in resp.get_json()["inventory_items"]}
    assert str(neighbour_item_id) not in neighbour_ids, "another org's item must never appear in this org's list"
