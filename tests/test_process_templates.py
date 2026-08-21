"""Tests for the industry process template catalogue.

See .agents/specs/process_templates.md for the AC definitions these tests are named
against. Covers: capability/module policy resolution (AC2-4), catalogue read shaping
(AC5, AC10), the scratch/template chooser (AC1), copy-into-tenant (AC6, AC7),
execution lineage through a copied template (AC8), the sample_only WORK_IN_PROGRESS
override (AC9), the catalogue page and wizard resume (AC12, AC13), and analytics
events (AC11).
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest

from app.core.db import db_session
from app.core.db.models.audit_log import AuditLog
from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process, ProcessCategory
from app.core.db.models.process_version import ProcessVersion
from app.core.db.models.step import Step
from app.core.db.models.user import User
from app.core.db.repositories.process_repo import ProcessRepository
from app.features.compliant.models.compliance_profile import ComplianceProfile
from app.features.compliant.service import ComplianceService
from app.features.process_templates.catalog import registry
from app.features.process_templates.catalog.registry import ProcessTemplate, TemplateOutput
from app.features.process_templates.services import process_templates_service as service
from tests.factories import DEFAULT_TEST_PASSWORD, OrganisationFactory, UserFactory


def _purge_org(db, org_id):
    """Delete every org-scoped row this test file might have created, in FK-safe
    (child-before-parent) order, then the org itself. None of these tables cascade
    from `organisations` at the DB level, so a plain `Organisation` delete 409s with a
    FK violation the moment a test has created a process/execution/etc for the org.
    """
    db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete(synchronize_session=False)
    db.query(EntityEvent).filter(EntityEvent.org_id == org_id).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.org_id == org_id).delete(synchronize_session=False)
    db.query(ExecutionStep).filter(ExecutionStep.org_id == org_id).delete(synchronize_session=False)
    db.query(Execution).filter(Execution.org_id == org_id).delete(synchronize_session=False)
    db.query(ProcessVersion).filter(ProcessVersion.org_id == org_id).delete(synchronize_session=False)
    db.query(Step).filter(Step.org_id == org_id).delete(synchronize_session=False)
    db.query(Process).filter(Process.org_id == org_id).delete(synchronize_session=False)
    db.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).delete(synchronize_session=False)
    db.query(User).filter(User.org_id == org_id).delete(synchronize_session=False)
    db.query(Organisation).filter(Organisation.id == org_id).delete(synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------


@pytest.fixture()
def db():
    session = db_session()
    try:
        yield session
    finally:
        session.close()
        db_session.remove()


@pytest.fixture()
def org(db):
    o = OrganisationFactory()
    db.commit()
    yield o
    _purge_org(db, o.id)


@pytest.fixture()
def user(db, org):
    # uuid-suffixed, not the factory's bare sequence: the shared test DB persists across
    # runs/sessions, and a plain `test-user-N@...` can collide with a leftover row from an
    # earlier run whose cleanup didn't happen (e.g. this file's own FK-ordering bug, fixed
    # after the fact — the DB doesn't retroactively forget what it already wrote).
    u = UserFactory(org_id=org.id, email=f"process-templates-test-{uuid4().hex}@example.test")
    db.commit()
    return u


def _enable_compliant(db, org_id, industry_module="nz_alcohol"):
    ComplianceService(db).upsert_profile(org_id, {"enabled": True, "industry_module": industry_module})


@pytest.fixture()
def app_client(db, org, user):
    """Authenticated Flask test client for an org with NO Compliant profile."""
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
                json={"email": user.email, "password": DEFAULT_TEST_PASSWORD},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


@pytest.fixture()
def compliant_org(db):
    o = OrganisationFactory()
    _enable_compliant(db, o.id)
    db.commit()
    yield o
    _purge_org(db, o.id)


@pytest.fixture()
def compliant_user(db, compliant_org):
    u = UserFactory(org_id=compliant_org.id, email=f"process-templates-test-{uuid4().hex}@example.test")
    db.commit()
    return u


@pytest.fixture()
def compliant_app_client(db, compliant_org, compliant_user):
    """Authenticated Flask test client for an org WITH Compliant + nz_alcohol enabled."""
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
                json={"email": compliant_user.email, "password": DEFAULT_TEST_PASSWORD},
                content_type="application/json",
            )
            assert resp.status_code in (200, 201), f"Login failed: {resp.data}"
            yield client


# ---------------------------------------------------------------------------------
# AC2-AC4: capability/module policy (pure registry/service, no Flask)
# ---------------------------------------------------------------------------------


class TestCapabilityPolicy:
    def test_ac2_all_three_families_permitted_when_compliant_and_nz_alcohol(self):
        families = registry.resolve_permitted_families(compliant_enabled=True, industry_module="nz_alcohol")
        assert set(families) == {"distillery", "brewery", "winery_vineyard"}

    def test_ac2_empty_when_not_enabled(self):
        assert registry.resolve_permitted_families(compliant_enabled=False, industry_module="nz_alcohol") == []

    def test_ac2_empty_when_wrong_module(self):
        assert registry.resolve_permitted_families(compliant_enabled=True, industry_module="food_manufacturing") == []

    def test_ac4_new_capability_module_mapping_requires_no_route_or_service_change(self, db, compliant_org):
        """Registering a synthetic second module/family proves the seam is generic
        data, not an `if nz_alcohol` branch — no route/service code changes here.
        """
        synthetic_family = f"synthetic_family_{uuid4().hex[:8]}"
        synthetic_template_id = f"synthetic_template_{uuid4().hex[:8]}"
        try:
            registry.register_family(
                synthetic_family,
                required_capability="compliant",
                industry_modules=("synthetic_module",),
                name="Synthetic Family",
                description="Test-only family.",
            )
            registry.register_template(
                ProcessTemplate(
                    id=synthetic_template_id,
                    family=synthetic_family,
                    name="Synthetic Template",
                    description="Test-only template.",
                    traceability_shape="a → b",
                    category=ProcessCategory.OTHER,
                    version=1,
                    step_name="Synthetic step",
                    outputs=(TemplateOutput(name="Out", unit="units"),),
                )
            )
            ComplianceService(db).upsert_profile(
                compliant_org.id, {"enabled": True, "industry_module": "synthetic_module"}
            )
            db.commit()

            result = service.list_catalog(db, compliant_org.id)
            template_ids = {t["id"] for t in result["templates"]}
            assert synthetic_template_id in template_ids
            detail = service.get_template_detail(db, compliant_org.id, synthetic_template_id)
            assert detail is not None
            assert detail["family"] == synthetic_family
        finally:
            registry.unregister_template(synthetic_template_id)
            registry.unregister_family(synthetic_family)
            # Restore this org's profile so it doesn't leak into other tests via compliant_org fixture teardown.
            _enable_compliant(db, compliant_org.id)
            db.commit()


# ---------------------------------------------------------------------------------
# AC1: scratch/template chooser
# ---------------------------------------------------------------------------------


class TestChooser:
    def test_ac1_chooser_renders_at_its_own_url(self, app_client):
        resp = app_client.get("/core/flows/create/start")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Start from scratch" in body
        assert "Start from a template" in body

    def test_ac1_chooser_scratch_card_links_to_unmodified_flows_create(self, app_client):
        body = app_client.get("/core/flows/create/start").get_data(as_text=True)
        assert 'href="/core/flows/create"' in body

    def test_ac1_existing_flows_create_route_is_unmodified(self, app_client, db, org):
        """The wizard's own long-established entry route must still behave exactly as
        before this feature — no chooser branch, no `?scratch=1` special-casing (see
        AC1: an earlier version of this branched `/core/flows/create` itself and broke
        four pre-existing e2e tests that treat it as an unconditional redirect).
        """
        no_id_resp = app_client.get("/core/flows/create")
        assert no_id_resp.status_code in (301, 302)
        assert no_id_resp.headers["Location"].endswith("/core/flows/create/process-overview?fresh=1")

        process = ProcessRepository(db).create_process(org_id=org.id, name="Existing process")
        db.commit()
        id_resp = app_client.get(f"/core/flows/create?id={process.id}")
        assert id_resp.status_code in (301, 302)
        assert "process-overview" in id_resp.headers["Location"]


# ---------------------------------------------------------------------------------
# AC2, AC3, AC5, AC10: catalogue API
# ---------------------------------------------------------------------------------


class TestCatalogApi:
    def test_ac2_list_returns_families_and_templates_when_compliant_enabled(self, compliant_app_client):
        resp = compliant_app_client.get("/api/core/process-templates")
        assert resp.status_code == 200
        body = resp.get_json()
        family_keys = {f["key"] for f in body["families"]}
        assert family_keys == {"distillery", "brewery", "winery_vineyard"}
        assert len(body["templates"]) == 20  # 8 distillery + 6 brewery + 6 winery

    def test_ac2_list_returns_no_families_when_not_compliant(self, app_client):
        resp = app_client.get("/api/core/process-templates")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["families"] == []
        assert body["templates"] == []

    def test_ac3_detail_404_for_org_without_permitted_family(self, app_client):
        resp = app_client.get("/api/core/process-templates/distillery_receive_ingredient_lot")
        assert resp.status_code == 404

    def test_ac3_detail_200_for_permitted_org(self, compliant_app_client):
        resp = compliant_app_client.get("/api/core/process-templates/distillery_receive_ingredient_lot")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["name"] == "Receive ingredient lot"
        assert body["step"]["outputs"][0]["name"] == "Raw material lot"

    def test_ac5_list_filtered_by_family(self, compliant_app_client):
        resp = compliant_app_client.get("/api/core/process-templates?family=brewery")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["templates"]
        assert all(t["family"] == "brewery" for t in body["templates"])

    def test_ac5_unknown_family_filter_returns_empty_not_400(self, compliant_app_client):
        resp = compliant_app_client.get("/api/core/process-templates?family=does-not-exist")
        assert resp.status_code == 200
        assert resp.get_json()["templates"] == []

    def test_ac10_advisory_present_in_list_and_detail(self, compliant_app_client):
        list_resp = compliant_app_client.get("/api/core/process-templates").get_json()
        assert all(t["advisory"] == registry.TEMPLATE_CUSTOMISE_ADVISORY for t in list_resp["templates"])
        detail_resp = compliant_app_client.get(
            "/api/core/process-templates/distillery_receive_ingredient_lot"
        ).get_json()
        assert detail_resp["advisory"] == registry.TEMPLATE_CUSTOMISE_ADVISORY


# ---------------------------------------------------------------------------------
# AC6, AC7: copy-into-tenant
# ---------------------------------------------------------------------------------


class TestCopyTemplate:
    def test_ac6_copy_creates_draft_process_with_step_and_provenance(self, compliant_app_client, db):
        resp = compliant_app_client.post("/api/core/process-templates/distillery_receive_ingredient_lot/copy")
        assert resp.status_code == 201
        process_id = resp.get_json()["process_id"]
        assert set(resp.get_json().keys()) == {"process_id"}

        process = db.query(Process).filter(Process.id == process_id).one()
        assert process.is_draft is True
        assert "Created from: Receive ingredient lot v1" in process.description

        steps = db.query(Step).filter(Step.process_id == process.id).all()
        assert len(steps) == 1
        assert steps[0].name == "Receive ingredient lot"
        assert steps[0].outputs[0]["name"] == "Raw material lot"

    def test_ac6_copy_404_for_org_without_permitted_family(self, app_client):
        resp = app_client.post("/api/core/process-templates/distillery_receive_ingredient_lot/copy")
        assert resp.status_code == 404

    def test_ac7_copy_is_tenant_scoped(self, compliant_app_client, db, compliant_org):
        """Cross-org read proven at the repository layer (not a second HTTP session):
        two independently-created `create_app()` instances each wrap the whole fixture
        body in their own `with flask_app.app_context():` (matching the established
        app_client pattern elsewhere in this suite), and nesting two of those across
        one test trips Flask's context-stack assertions. The repository call is what
        AC7 actually claims holds (`ProcessRepository.get_process_by_id`'s org filter,
        no new isolation logic) — proving it directly is both simpler and more precise.
        """
        resp = compliant_app_client.post("/api/core/process-templates/distillery_receive_ingredient_lot/copy")
        process_id = UUID(resp.get_json()["process_id"])

        other_org = OrganisationFactory()
        db.commit()
        try:
            repo = ProcessRepository(db)
            assert repo.get_process_by_id(process_id, org_id=other_org.id) is None
            assert repo.get_process_by_id(process_id, org_id=compliant_org.id) is not None
        finally:
            _purge_org(db, other_org.id)

    def test_ac7_editing_copy_does_not_mutate_catalog(self, compliant_app_client, db):
        resp = compliant_app_client.post("/api/core/process-templates/distillery_receive_ingredient_lot/copy")
        process_id = resp.get_json()["process_id"]

        compliant_app_client.put(
            f"/api/core/processes/{process_id}",
            json={"name": "My Customised Intake"},
        )

        template = registry.get_template_by_id("distillery_receive_ingredient_lot")
        assert template.name == "Receive ingredient lot"  # catalog untouched

        detail = compliant_app_client.get("/api/core/process-templates/distillery_receive_ingredient_lot").get_json()
        assert detail["name"] == "Receive ingredient lot"


# ---------------------------------------------------------------------------------
# AC8: execution lineage through a copied template
# ---------------------------------------------------------------------------------


class TestExecutionLineage:
    def test_ac8_completed_execution_creates_source_linked_inventory(self, compliant_app_client, db):
        copy_resp = compliant_app_client.post("/api/core/process-templates/distillery_receive_ingredient_lot/copy")
        process_id = copy_resp.get_json()["process_id"]

        exec_resp = compliant_app_client.post("/api/core/executions", json={"process_id": process_id})
        assert exec_resp.status_code == 201
        execution_id = exec_resp.get_json()["id"]

        get_resp = compliant_app_client.get(f"/api/core/executions/{execution_id}")
        step = get_resp.get_json()["execution_steps"][0]
        execution_step_id = step["id"]

        complete_resp = compliant_app_client.post(
            f"/api/core/executions/{execution_id}/steps/{execution_step_id}/complete",
            json={
                "actual_inputs": [],
                "actual_outputs": [{"name": "Raw material lot", "quantity": 5, "unit": "kg"}],
                # The template's required execution prompts (Supplier, Supplier batch)
                # must be filled — execution_prompt_rules.validate_execution_prompts
                # 400s a required prompt with no matching execution_data entry.
                "execution_data": {"Supplier": "Test Supplier Co", "Supplier batch": "TB-001"},
            },
        )
        assert complete_resp.status_code == 200, complete_resp.get_json()

        item = db.query(InventoryItem).filter(InventoryItem.source_execution_step_id == execution_step_id).one()
        assert str(item.source_execution_step_id) == execution_step_id
        assert item.inventory_type == InventoryType.FINAL_PRODUCT.value  # single step is terminal, not sample_only


# ---------------------------------------------------------------------------------
# AC9: sample_only output forces WORK_IN_PROGRESS
# ---------------------------------------------------------------------------------


class TestSampleOnlyOutput:
    def _build_single_step_process(self, db, org_id, *, sample_only: bool):
        repo = ProcessRepository(db)
        process = repo.create_process(org_id=org_id, name="Sample-only test process", category=ProcessCategory.OTHER)
        repo.add_step(
            process_id=process.id,
            org_id=org_id,
            step_number=1,
            position=1000,
            name="Only step",
            outputs=[
                {
                    "name": "Trial output",
                    "quantity": 1,
                    "unit": "mL",
                    "extra_data": ({"sample_only": True} if sample_only else {}),
                }
            ],
        )
        db.commit()
        return process

    def test_ac9_sample_only_output_is_work_in_progress_even_though_terminal(
        self, compliant_app_client, db, compliant_org
    ):
        process = self._build_single_step_process(db, compliant_org.id, sample_only=True)

        exec_resp = compliant_app_client.post("/api/core/executions", json={"process_id": str(process.id)})
        execution_id = exec_resp.get_json()["id"]
        step = compliant_app_client.get(f"/api/core/executions/{execution_id}").get_json()["execution_steps"][0]

        compliant_app_client.post(
            f"/api/core/executions/{execution_id}/steps/{step['id']}/complete",
            json={
                "actual_inputs": [],
                "actual_outputs": [{"name": "Trial output", "quantity": 1, "unit": "mL"}],
                "execution_data": {},
            },
        )

        item = db.query(InventoryItem).filter(InventoryItem.source_execution_step_id == step["id"]).one()
        assert item.inventory_type == InventoryType.WORK_IN_PROGRESS.value

    def test_ac9_control_without_sample_only_flag_terminal_step_is_final_product(
        self, compliant_app_client, db, compliant_org
    ):
        """Regression guard for the mechanism AC9 relies on: without the flag, a
        single (therefore terminal) step's output is FINAL_PRODUCT as before.
        """
        process = self._build_single_step_process(db, compliant_org.id, sample_only=False)

        exec_resp = compliant_app_client.post("/api/core/executions", json={"process_id": str(process.id)})
        execution_id = exec_resp.get_json()["id"]
        step = compliant_app_client.get(f"/api/core/executions/{execution_id}").get_json()["execution_steps"][0]

        compliant_app_client.post(
            f"/api/core/executions/{execution_id}/steps/{step['id']}/complete",
            json={
                "actual_inputs": [],
                "actual_outputs": [{"name": "Trial output", "quantity": 1, "unit": "mL"}],
                "execution_data": {},
            },
        )

        item = db.query(InventoryItem).filter(InventoryItem.source_execution_step_id == step["id"]).one()
        assert item.inventory_type == InventoryType.FINAL_PRODUCT.value


# ---------------------------------------------------------------------------------
# AC12, AC13: catalogue page and wizard resume
# ---------------------------------------------------------------------------------


class TestCatalogPageAndResume:
    def test_ac12_catalog_page_renders_for_permitted_org(self, compliant_app_client):
        resp = compliant_app_client.get("/core/flows/create/template-catalog")
        assert resp.status_code == 200

    def test_ac12_catalog_page_renders_even_without_permitted_families(self, app_client):
        resp = app_client.get("/core/flows/create/template-catalog")
        assert resp.status_code == 200

    def test_ac13_wizard_resumes_on_copied_draft(self, compliant_app_client):
        copy_resp = compliant_app_client.post("/api/core/process-templates/distillery_receive_ingredient_lot/copy")
        process_id = copy_resp.get_json()["process_id"]

        resp = compliant_app_client.get(f"/core/flows/create/summary?id={process_id}")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------------
# Observability: structured log lines (observability skill's per-feature instrumentation)
# ---------------------------------------------------------------------------------


class _LogRecordCollector(logging.Handler):
    """Collects raw LogRecords for direct inspection of the structlog event dict.
    Same renderer-independent technique test_dilution_calculator.py uses.
    """

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class TestObservabilityLogging:
    def test_access_denied_logged_for_unpermitted_template_family(self, app_client):
        collector = _LogRecordCollector()
        root_logger = logging.getLogger()
        root_logger.addHandler(collector)
        try:
            resp = app_client.get("/api/core/process-templates/distillery_receive_ingredient_lot")
        finally:
            root_logger.removeHandler(collector)

        assert resp.status_code == 404
        denied = [r.msg for r in collector.records if isinstance(r.msg, dict) and r.msg.get("event") == "access_denied"]
        assert denied, f"Expected an access_denied log record, got: {collector.records}"
        assert denied[0]["level"] == "warning"
        assert denied[0]["reason"] == "template_family_not_permitted"
        assert denied[0]["template_id"] == "distillery_receive_ingredient_lot"

    def test_template_copied_logged_on_success(self, compliant_app_client):
        collector = _LogRecordCollector()
        root_logger = logging.getLogger()
        root_logger.addHandler(collector)
        try:
            resp = compliant_app_client.post("/api/core/process-templates/distillery_receive_ingredient_lot/copy")
        finally:
            root_logger.removeHandler(collector)

        assert resp.status_code == 201
        copied = [
            r.msg
            for r in collector.records
            if isinstance(r.msg, dict) and r.msg.get("event") == "process_templates_template_copied"
        ]
        assert copied, f"Expected a process_templates_template_copied log record, got: {collector.records}"
        assert copied[0]["level"] == "info"
        assert copied[0]["template_id"] == "distillery_receive_ingredient_lot"
        assert copied[0]["family"] == "distillery"


# ---------------------------------------------------------------------------------
# AC11: analytics events
# ---------------------------------------------------------------------------------


class TestAnalyticsEvents:
    def test_ac11_list_call_emits_catalog_viewed(self, compliant_app_client, db, compliant_org):
        compliant_app_client.get("/api/core/process-templates")
        events = (
            db.query(EntityEvent)
            .filter(
                EntityEvent.org_id == compliant_org.id,
                EntityEvent.event_type == "process_templates.catalog_viewed",
            )
            .all()
        )
        assert len(events) >= 1

    def test_ac11_detail_call_emits_template_selected(self, compliant_app_client, db, compliant_org):
        compliant_app_client.get("/api/core/process-templates/distillery_receive_ingredient_lot")
        events = (
            db.query(EntityEvent)
            .filter(
                EntityEvent.org_id == compliant_org.id,
                EntityEvent.event_type == "process_templates.template_selected",
            )
            .all()
        )
        assert len(events) >= 1
        assert events[-1].payload["template_id"] == "distillery_receive_ingredient_lot"

    def test_ac11_copy_emits_template_copied_with_payload(self, compliant_app_client, db, compliant_org):
        resp = compliant_app_client.post("/api/core/process-templates/distillery_receive_ingredient_lot/copy")
        process_id = resp.get_json()["process_id"]
        events = (
            db.query(EntityEvent)
            .filter(
                EntityEvent.org_id == compliant_org.id,
                EntityEvent.event_type == "process_templates.template_copied",
            )
            .all()
        )
        assert len(events) == 1
        assert events[0].payload["template_id"] == "distillery_receive_ingredient_lot"
        assert events[0].payload["family"] == "distillery"
        assert events[0].payload["process_id"] == process_id
