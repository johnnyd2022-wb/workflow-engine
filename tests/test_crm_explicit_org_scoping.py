"""CRM queries name their own ``org_id`` instead of leaning on the ambient tenant filter.

``.agents/reports/crm/security-tenant-audit.md`` F3: line-item replace/read, sync-job updates,
the task's contact lookup and the ``Session.get()`` calls in sales traceability had no
``org_id`` predicate of their own. The global filter fails open with no tenant context (admin
CLI, background jobs) and ``Session.get()`` can answer from the identity map without a query,
so these tests run with no tenant context: a missing predicate reaches the other tenant's row.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.db.models.entity_event import EntityEvent
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_movement import InventoryMovement
from app.core.db.models.organisation import Organisation
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.features.crm.models.crm_task import CRMTask
from app.features.crm.models.product_mapping import ProductMapping
from app.features.crm.models.sales_fifo_allocation import SalesFifoAllocation
from app.features.crm.models.xero_contact import XeroContact
from app.features.crm.models.xero_invoice import XeroInvoice
from app.features.crm.models.xero_invoice_line_item import XeroInvoiceLineItem
from app.features.crm.models.xero_sync_job import XeroSyncJob
from app.features.crm.repositories.xero_invoice_repo import XeroInvoiceRepository
from app.features.crm.repositories.xero_sync_job_repo import XeroSyncJobRepository
from app.features.crm.services import sales_traceability_service as traceability
from app.features.crm.services.crm_service import _serialise_task
from app.features.crm.services.sales_traceability_service import SalesTraceabilityService
from tests import test_crm as crm_fixtures
from tests.dag_traversal_helpers import clear_org_synthetic_data
from tests.factories import ExecutionFactory, InventoryItemFactory, ProcessFactory

db = crm_fixtures.db
org = crm_fixtures.org


@pytest.fixture(autouse=True)
def other_org(db, org):
    """A second tenant, in every test so that both orgs' rows are purged on the way out
    (their ``org_id`` FKs don't cascade, and ``org``'s own teardown deletes only the org)."""
    org_b = OrganisationRepository(db).create_org(f"Scoping Org B {uuid4()}")
    db.commit()
    yield org_b

    db.rollback()
    for org_id in (org.id, org_b.id):
        db.query(SalesFifoAllocation).filter(SalesFifoAllocation.org_id == org_id).delete(synchronize_session=False)
        db.query(InventoryMovement).filter(InventoryMovement.org_id == org_id).delete(synchronize_session=False)
        db.query(EntityEvent).filter(EntityEvent.org_id == org_id).delete(synchronize_session=False)
        db.query(CRMTask).filter(CRMTask.org_id == org_id).delete(synchronize_session=False)
        db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.org_id == org_id).delete(synchronize_session=False)
        db.query(XeroInvoice).filter(XeroInvoice.org_id == org_id).delete(synchronize_session=False)
        db.query(XeroSyncJob).filter(XeroSyncJob.org_id == org_id).delete(synchronize_session=False)
        db.query(XeroContact).filter(XeroContact.org_id == org_id).delete(synchronize_session=False)
        db.query(ProductMapping).filter(ProductMapping.org_id == org_id).delete(synchronize_session=False)
        db.commit()
        clear_org_synthetic_data(db, org_id)
    db.query(Organisation).filter(Organisation.id == org_b.id).delete(synchronize_session=False)
    db.commit()


def _invoice_with_two_lines(db, org_id):
    invoice = XeroInvoice(
        org_id=org_id, xero_invoice_id=f"inv-{uuid4()}", xero_tenant_id="t", invoice_type="ACCREC", status="AUTHORISED"
    )
    db.add(invoice)
    db.flush()
    for n in (1, 2):
        db.add(
            XeroInvoiceLineItem(
                org_id=org_id, invoice_id=invoice.id, xero_line_item_id=f"line-{n}", description=f"Gin {n}"
            )
        )
    db.commit()
    return invoice


def _contact(db, org_id, name):
    contact = XeroContact(org_id=org_id, xero_contact_id=f"xc-{uuid4()}", name=name, email_address=f"{uuid4()}@x.test")
    db.add(contact)
    db.commit()
    return contact


def _line_count(db, invoice_id):
    db.expire_all()
    return db.query(XeroInvoiceLineItem).filter(XeroInvoiceLineItem.invoice_id == invoice_id).count()


class TestInvoiceLineItems:
    def test_replacing_lines_for_one_org_leaves_another_orgs_invoice_alone(self, db, org, other_org):
        theirs = _invoice_with_two_lines(db, other_org.id)

        XeroInvoiceRepository(db).replace_line_items(theirs.id, org.id, [])
        db.commit()

        assert _line_count(db, theirs.id) == 2

    def test_replacing_lines_for_the_owning_org_still_replaces_them(self, db, org):
        """[CONTROL]"""
        mine = _invoice_with_two_lines(db, org.id)

        XeroInvoiceRepository(db).replace_line_items(mine.id, org.id, [{"description": "Only line"}])
        db.commit()

        assert _line_count(db, mine.id) == 1

    def test_another_orgs_invoice_lines_are_not_read(self, db, org, other_org):
        theirs = _invoice_with_two_lines(db, other_org.id)

        assert XeroInvoiceRepository(db).get_line_items(theirs.id, org.id) == []

    def test_the_owning_orgs_invoice_lines_are_read(self, db, org):
        """[CONTROL]"""
        mine = _invoice_with_two_lines(db, org.id)

        assert len(XeroInvoiceRepository(db).get_line_items(mine.id, org.id)) == 2


class TestSyncJobs:
    @staticmethod
    def _job(db, org_id):
        job = XeroSyncJobRepository(db).create(org_id, "t", "full", "test")
        db.commit()
        return job

    MARKS = {
        "completed": lambda repo, job_id, org_id: repo.mark_completed(job_id, org_id, 1, 2),
        "failed": lambda repo, job_id, org_id: repo.mark_failed(job_id, org_id, "boom"),
        "partial": lambda repo, job_id, org_id: repo.mark_partial(job_id, org_id, 1, 2, "some failed"),
    }

    @pytest.mark.parametrize("outcome", MARKS)
    def test_one_orgs_sync_cannot_close_another_orgs_job(self, db, org, other_org, outcome):
        theirs = self._job(db, other_org.id)

        self.MARKS[outcome](XeroSyncJobRepository(db), theirs.id, org.id)
        db.commit()

        db.refresh(theirs)
        assert theirs.status == "running"

    @pytest.mark.parametrize("outcome", MARKS)
    def test_an_org_still_closes_its_own_job(self, db, org, outcome):
        """[CONTROL]"""
        mine = self._job(db, org.id)

        self.MARKS[outcome](XeroSyncJobRepository(db), mine.id, org.id)
        db.commit()

        db.refresh(mine)
        assert mine.status == outcome


class TestSyncJobWiring:
    """``_finalise_job`` hands the job id and org to the repository in the right slots: the repository
    tests above call it directly, so a swapped argument there would leave the job "running" unnoticed."""

    @staticmethod
    def _sync(db, org, monkeypatch, *, contacts, invoices):
        from app.features.crm.services import xero_api_client as xero_api_client_module
        from app.features.crm.services.xero_sync_service import XeroSyncService
        from tests.test_crm_contact_sync import _connect

        def reply(outcome):
            def get(self, **kwargs):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

            return get

        _connect(db, org.id)
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_contacts", reply(contacts))
        monkeypatch.setattr(xero_api_client_module.XeroAPIClient, "get_all_invoices", reply(invoices))
        XeroSyncService(db).incremental_sync(org.id, triggered_by="test")
        db.expire_all()
        return XeroSyncJobRepository(db).get_latest(org.id)

    def test_a_clean_sync_closes_its_job_as_completed(self, db, org, monkeypatch):
        from tests.test_xero_sync_service import _xero_contact

        job = self._sync(db, org, monkeypatch, contacts=[_xero_contact("xc-1", "Harbour Spirits Co.")], invoices=[])

        assert (job.status, job.contacts_synced) == ("completed", 1)

    def test_a_sync_that_lost_its_invoices_closes_its_job_as_partial(self, db, org, monkeypatch):
        from tests.test_xero_sync_service import _xero_contact

        job = self._sync(
            db,
            org,
            monkeypatch,
            contacts=[_xero_contact("xc-1", "Harbour Spirits Co.")],
            invoices=RuntimeError("Invoices timed out"),
        )

        assert (job.status, job.contacts_synced) == ("partial", 1)

    def test_a_sync_that_got_nothing_closes_its_job_as_failed(self, db, org, monkeypatch):
        job = self._sync(
            db, org, monkeypatch, contacts=RuntimeError("Xero is down"), invoices=RuntimeError("Xero is down")
        )

        assert job.status == "failed"
        assert "Xero is down" in job.error_message


class TestTaskContact:
    @staticmethod
    def _task(db, org_id, contact_id):
        task = CRMTask(org_id=org_id, title="Call", contact_id=contact_id)
        db.add(task)
        db.commit()
        return task

    def test_a_task_never_shows_another_orgs_contact(self, db, org, other_org):
        theirs = _contact(db, other_org.id, "Rival Spirits Ltd")
        task = self._task(db, org.id, theirs.id)

        shown = _serialise_task(task, db=db)

        assert (shown["contact_name"], shown["contact_email"]) == (None, None)

    def test_a_task_shows_its_own_orgs_contact(self, db, org):
        """[CONTROL]"""
        mine = _contact(db, org.id, "Harbour Spirits Co.")
        task = self._task(db, org.id, mine.id)

        assert _serialise_task(task, db=db)["contact_name"] == "Harbour Spirits Co."


class TestSalesTraceability:
    @staticmethod
    def _batch(db, org_id, *, name="Gin - final product", batch="LOT-1", **extra):
        item = InventoryItemFactory(
            org_id=org_id,
            name=name,
            quantity="10",
            unit="units",
            inventory_type="final_product",
            supplier_batch_number=batch,
            **extra,
        )
        db.commit()
        return item

    @staticmethod
    def _completed_step(db, org_id, completed: datetime):
        process = ProcessFactory(org_id=org_id)
        ProcessRepository(db).add_step(
            org_id=org_id, process_id=process.id, step_number=1, position=1000, name="Bottle", inputs=[], outputs=[]
        )
        db.commit()
        execution = ExecutionFactory(org_id=org_id, process_id=process.id)
        db.commit()
        step = db.query(ExecutionStep).filter(ExecutionStep.execution_id == execution.id).one()
        step.completed_at = completed
        db.commit()
        return step

    def test_a_batch_is_not_pre_sold_by_another_orgs_batch(self, db, org, other_org):
        theirs = self._batch(db, other_org.id)  # made today, i.e. after the invoice date below

        assert traceability._is_presold(db, org.id, theirs.id, date(2020, 1, 1)) is False

    def test_a_batch_is_pre_sold_when_made_after_the_invoice(self, db, org):
        """[CONTROL]"""
        mine = self._batch(db, org.id)

        assert traceability._is_presold(db, org.id, mine.id, date(2020, 1, 1)) is True

    def test_a_batch_is_not_dated_from_another_orgs_production_step(self, db, org, other_org):
        step = self._completed_step(db, other_org.id, datetime(2020, 1, 1, tzinfo=UTC))
        mine = self._batch(db, org.id, extra_data={"bottled_on": "2026-05-05"})
        mine.source_execution_step_id = step.id
        db.commit()

        assert traceability._made_on(db, mine) == date(2026, 5, 5)

    def test_a_batch_is_dated_from_its_own_production_step(self, db, org):
        """[CONTROL]"""
        step = self._completed_step(db, org.id, datetime(2020, 1, 1, tzinfo=UTC))
        mine = self._batch(db, org.id, extra_data={"bottled_on": "2026-05-05"})
        mine.source_execution_step_id = step.id
        db.commit()

        assert traceability._made_on(db, mine) == date(2020, 1, 1)

    @staticmethod
    def _pending_review_on(db, org_id, batch_item, invoice_id="inv-1"):
        """An allocation of ``org_id``'s sale waiting for review, drawn from ``batch_item``."""
        mapping = ProductMapping(
            org_id=org_id, biz_e_product_name="Gin - final product", xero_description_pattern="Gin", match_type="exact"
        )
        db.add(mapping)
        db.add(
            XeroInvoice(
                org_id=org_id,
                xero_invoice_id=invoice_id,
                xero_tenant_id="t",
                invoice_type="ACCREC",
                status="AUTHORISED",
                date=date(2026, 9, 1),
            )
        )
        db.flush()
        db.add(
            SalesFifoAllocation(
                org_id=org_id,
                xero_invoice_id=invoice_id,
                xero_line_key="line-1",
                inventory_item_id=batch_item.id,
                product_mapping_id=mapping.id,
                product_name="Gin - final product",
                quantity=Decimal("1"),
                unit="units",
                status="pending_review",
            )
        )
        db.commit()

    @staticmethod
    def _queued_lots(db, org_id):
        queue = SalesTraceabilityService(db).review_queue(org_id)
        return [b["batch"] for line in queue["pending_review"] for b in line["batches"]]

    def test_the_review_queue_does_not_name_another_orgs_batch(self, db, org, other_org):
        """A pending allocation pointing at another org's batch (bad data) must not print its lot."""
        theirs = self._batch(db, other_org.id, batch="RIVAL-SECRET-LOT")
        self._pending_review_on(db, org.id, theirs)

        assert self._queued_lots(db, org.id) == [None]

    def test_the_review_queue_names_the_orgs_own_batch(self, db, org):
        """[CONTROL]"""
        mine = self._batch(db, org.id, batch="OWN-LOT-7")
        self._pending_review_on(db, org.id, mine)

        assert self._queued_lots(db, org.id) == ["OWN-LOT-7"]

    def test_assigning_another_orgs_batch_is_refused_and_leaves_its_stock(self, db, org, other_org):
        """[CONTROL] already held by ``consume_final_product_lot``; the explicit lookup after it is belt and braces."""
        theirs = self._batch(db, other_org.id)
        mapping = ProductMapping(
            org_id=org.id, biz_e_product_name="Gin - final product", xero_description_pattern="Gin", match_type="exact"
        )
        db.add(mapping)
        invoice = XeroInvoice(
            org_id=org.id,
            xero_invoice_id="inv-2",
            xero_tenant_id="t",
            invoice_type="ACCREC",
            status="AUTHORISED",
            date=date(2026, 9, 1),
        )
        db.add(invoice)
        db.flush()
        db.add(
            XeroInvoiceLineItem(
                org_id=org.id,
                invoice_id=invoice.id,
                xero_line_item_id="line-1",
                description="Gin",
                quantity=Decimal("1"),
            )
        )
        db.commit()
        picks = [{"inventory_item_id": str(theirs.id), "quantity": "1"}]

        with pytest.raises(ValueError, match="finished product in this organisation"):
            SalesTraceabilityService(db).assign_line(org.id, "inv-2", "line-1", picks)

        db.rollback()
        db.refresh(theirs)
        assert Decimal(str(theirs.quantity)) == Decimal("10")


class TestMappingSourceOutputs:
    """F2's ownership check reads steps and stock; with no tenant context only its own ``org_id``
    predicates keep another tenant's output from counting as the caller's."""

    @staticmethod
    def _map(db, org_id, output_id):
        from app.features.crm.services.crm_service import CRMService

        return CRMService(db).create_mapping(
            org_id,
            {
                "biz_e_product_name": f"Mapped {uuid4()}",
                "xero_description_pattern": f"Pattern {uuid4()}",
                "biz_e_source_output_id": str(output_id),
            },
            None,
        )

    def test_another_orgs_output_is_not_this_orgs_product(self, db, org, other_org):
        """Declared by their step and carried by their stock, so both lookups are tempted."""
        output_id, step = crm_fixtures._declared_product_output(db, other_org.id)
        crm_fixtures._stock_of_output(db, other_org.id, step, output_id)

        with pytest.raises(ValueError, match="not a product output in this organisation"):
            self._map(db, org.id, output_id)

        assert db.query(ProductMapping).filter(ProductMapping.org_id == org.id).count() == 0

    def test_another_orgs_stock_alone_is_not_this_orgs_product(self, db, org, other_org):
        """Their step stops declaring it, leaving only stock to vouch for the id."""
        output_id, step = crm_fixtures._declared_product_output(db, other_org.id)
        crm_fixtures._stock_of_output(db, other_org.id, step, output_id)
        step.outputs = []
        db.commit()

        with pytest.raises(ValueError, match="not a product output in this organisation"):
            self._map(db, org.id, output_id)

    def test_the_owning_orgs_output_is_accepted(self, db, org):
        """[CONTROL]"""
        output_id, _ = crm_fixtures._declared_product_output(db, org.id)

        assert self._map(db, org.id, output_id)["biz_e_source_output_id"] == str(output_id)
