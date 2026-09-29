"""Trusted order writes: validate every reference before storing it."""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.orm import selectinload

from app.core.backend.event_writer import EventWriter
from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.process import Process
from app.core.db.models.process_version import ProcessVersion
from app.core.utils.unit_conversion import is_count_unit
from app.features.contract_manufacturing.models.orders import (
    DUTY_RESPONSIBILITIES,
    MATERIALS_SOURCES,
    ORDER_STATUSES,
    ContractCustomer,
    ContractOrder,
    ContractOrderExecution,
    ContractOrderLine,
)
from app.features.crm.models.xero_contact import XeroContact


class OrderError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def identifier(value, field):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise OrderError(f"{field} must be a UUID") from None


def text_value(value, field, limit, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise OrderError(f"{field} must be text")
    value = value.strip()
    if not value and not required:
        return None
    if not value or len(value) > limit:
        raise OrderError(f"{field} is required (up to {limit} characters)")
    return value


def object_body(data, allowed):
    if not isinstance(data, dict):
        raise OrderError("JSON object required")
    if set(data) - set(allowed):
        raise OrderError("Unknown fields: " + ", ".join(sorted(set(data) - set(allowed))))


class ContractOrderService:
    def __init__(self, db, org_id):
        if not isinstance(org_id, UUID):
            raise OrderError("Authenticated organisation required", 403)
        self.db, self.org_id = db, org_id

    def _event(self, kind, entity, row, payload):
        # Preserve each declaration in the transactional event, rather than only the
        # mutable row or a quantity-only audit entry.
        if isinstance(row, ContractOrder):
            payload = {
                **payload,
                "reference": row.reference,
                "customer_id": str(row.customer_id),
                "due_date": row.due_date.isoformat(),
                "status": row.status,
                "duty_responsibility": row.duty_responsibility,
                "customer_cca_reference": row.customer_cca_reference,
            }
        elif isinstance(row, ContractOrderLine):
            payload = {
                **payload,
                "product_name": row.product_name,
                "quantity": str(row.quantity),
                "unit": row.unit,
                "materials_source": row.materials_source,
                "spec_reference": row.spec_reference,
                "process_id": str(row.process_id) if row.process_id else None,
                "process_version_id": str(row.process_version_id) if row.process_version_id else None,
                "source_output_id": str(row.source_output_id) if row.source_output_id else None,
            }
        elif isinstance(row, ContractCustomer):
            payload = {**payload, "crm_contact_id": str(row.crm_contact_id) if row.crm_contact_id else None}
        EventWriter(self.db, self.org_id).emit(
            event_type=f"contract.{kind}", entity_type=entity, entity_id=row.id, payload=payload
        )

    def customers(self):
        return (
            self.db.query(ContractCustomer)
            .filter(ContractCustomer.org_id == self.org_id)
            .order_by(ContractCustomer.name)
            .all()
        )

    def crm_choices(self):
        return [
            {"id": str(row.id), "name": row.name}
            for row in self.db.query(XeroContact)
            .filter(XeroContact.org_id == self.org_id)
            .order_by(XeroContact.name)
            .all()
        ]

    def recipe_choices(self):
        versions = (
            self.db.query(ProcessVersion)
            .filter(ProcessVersion.org_id == self.org_id)
            .order_by(ProcessVersion.created_at.desc())
            .all()
        )
        return [
            {
                "value": f"{version.id}|{output.get('id') or ''}",
                "label": f"{version.snapshot.get('name', 'Workflow')} v{version.version_number} · {output.get('name', 'Output')}",
            }
            for version in versions
            for step in version.snapshot.get("steps", [])
            for output in step.get("outputs") or []
            if isinstance(output, dict)
        ]

    def batch_choices(self):
        assigned = self.db.query(ContractOrderExecution.execution_id).filter(
            ContractOrderExecution.org_id == self.org_id
        )
        return [
            {"id": str(row.id), "label": f"{row.process.name} · {row.started_at.date()} · {str(row.id)[:8]}"}
            for row in self.db.query(Execution)
            .filter(
                Execution.org_id == self.org_id,
                ~Execution.id.in_(assigned),
                Execution.status.notin_([ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]),
            )
            .order_by(Execution.started_at.desc())
            .all()
        ]

    def customer(self, customer_id):
        row = (
            self.db.query(ContractCustomer)
            .filter(
                ContractCustomer.org_id == self.org_id, ContractCustomer.id == identifier(customer_id, "customer_id")
            )
            .first()
        )
        if row is None:
            raise OrderError("Customer not found", 404)
        return row

    def save_customer(self, data, customer_id=None):
        object_body(data, {"name", "crm_contact_id", "is_active"})
        row = self.customer(customer_id) if customer_id else ContractCustomer(org_id=self.org_id)
        if "name" in data or customer_id is None:
            row.name = text_value(data.get("name"), "name", 255)
        if "is_active" in data:
            if not isinstance(data["is_active"], bool):
                raise OrderError("is_active must be a boolean")
            row.is_active = data["is_active"]
        if "crm_contact_id" in data:
            contact_id = identifier(data["crm_contact_id"], "crm_contact_id") if data["crm_contact_id"] else None
            if (
                contact_id
                and self.db.query(XeroContact.id)
                .filter(XeroContact.org_id == self.org_id, XeroContact.id == contact_id)
                .first()
                is None
            ):
                raise OrderError("CRM contact not found", 404)
            row.crm_contact_id = contact_id
        self.db.add(row)
        self.db.flush()
        self._event("customer_saved", "contract_customer", row, {"name": row.name, "is_active": row.is_active})
        return row

    def orders(self, customer_id=None, status=None):
        query = self.db.query(ContractOrder).filter(ContractOrder.org_id == self.org_id)
        if customer_id:
            self.customer(customer_id)
            query = query.filter(ContractOrder.customer_id == identifier(customer_id, "customer_id"))
        if status:
            if status not in ORDER_STATUSES:
                raise OrderError("Unknown order status")
            query = query.filter(ContractOrder.status == status)
        return (
            query.options(
                selectinload(ContractOrder.customer),
                selectinload(ContractOrder.lines)
                .selectinload(ContractOrderLine.batches)
                .selectinload(ContractOrderExecution.execution),
            )
            .order_by(ContractOrder.due_date, ContractOrder.created_at)
            .all()
        )

    def order(self, order_id, lock=False):
        query = self.db.query(ContractOrder).filter(
            ContractOrder.org_id == self.org_id, ContractOrder.id == identifier(order_id, "order_id")
        )
        row = query.with_for_update().populate_existing().first() if lock else query.first()
        if row is None:
            raise OrderError("Order not found", 404)
        return row

    def _order_fields(self, data, row, creating=False):
        if "reference" in data or creating:
            row.reference = text_value(data.get("reference"), "reference", 100)
        if "due_date" in data or creating:
            try:
                row.due_date = date.fromisoformat(data.get("due_date"))
            except (ValueError, TypeError):
                raise OrderError("due_date must be YYYY-MM-DD") from None
        if "duty_responsibility" in data or creating:
            duty = data.get("duty_responsibility")
            if duty not in DUTY_RESPONSIBILITIES:
                raise OrderError("Choose the order's duty responsibility")
            row.duty_responsibility = duty
        if "customer_cca_reference" in data:
            row.customer_cca_reference = text_value(
                data["customer_cca_reference"], "customer_cca_reference", 255, False
            )
        if row.duty_responsibility != "producer_licensee" and not row.customer_cca_reference:
            raise OrderError("Customer licensee or underbond orders require the customer's CCA reference")
        if "status" in data or creating:
            status = data.get("status", "draft")
            if status not in ORDER_STATUSES:
                raise OrderError("Unknown order status")
            if creating and status not in {"draft", "confirmed"}:
                raise OrderError("New orders must be draft or confirmed")
            if not creating and row.status in {"completed", "cancelled"} and status != row.status:
                raise OrderError("Closed orders cannot be reopened", 409)
            if status == "completed":
                links = [link for line in row.lines for link in line.batches]
                if not links or any(link.execution.status != ExecutionStatus.COMPLETED for link in links):
                    raise OrderError("Complete the linked batches before completing the order", 409)
            row.status = status

    def create_order(self, data):
        object_body(
            data,
            {
                "customer_id",
                "reference",
                "due_date",
                "status",
                "duty_responsibility",
                "customer_cca_reference",
                "lines",
            },
        )
        customer = self.customer(data.get("customer_id"))
        if not customer.is_active:
            raise OrderError("Customer is inactive", 409)
        lines = data.get("lines")
        if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
            raise OrderError("An order needs between 1 and 100 lines")
        row = ContractOrder(org_id=self.org_id, customer_id=customer.id)
        self._order_fields(data, row, True)
        self.db.add(row)
        self.db.flush()
        for line in lines:
            self.add_line(row.id, line)
        self._event(
            "order_created", "contract_order", row, {"customer_id": str(customer.id), "reference": row.reference}
        )
        return row

    def update_order(self, order_id, data):
        object_body(data, {"reference", "due_date", "status", "duty_responsibility", "customer_cca_reference"})
        row = self.order(order_id, lock=True)
        if row.status in {"completed", "cancelled"}:
            raise OrderError("Closed orders cannot be changed", 409)
        if any(line.batches for line in row.lines) and set(data) & {"duty_responsibility", "customer_cca_reference"}:
            raise OrderError("Duty declarations cannot change after a batch is linked", 409)
        if any(line.batches for line in row.lines) and data.get("status") == "draft":
            raise OrderError("A batch-linked order cannot return to draft", 409)
        self._order_fields(data, row)
        self.db.flush()
        self._event(
            "order_updated", "contract_order", row, {"status": row.status, "due_date": row.due_date.isoformat()}
        )
        return row

    def line(self, order_id, line_id):
        self.order(order_id)
        row = (
            self.db.query(ContractOrderLine)
            .filter(
                ContractOrderLine.org_id == self.org_id,
                ContractOrderLine.order_id == identifier(order_id, "order_id"),
                ContractOrderLine.id == identifier(line_id, "line_id"),
            )
            .first()
        )
        if row is None:
            raise OrderError("Order line not found", 404)
        return row

    def _line_fields(self, row, data, creating=False):
        object_body(
            data,
            {
                "product_name",
                "quantity",
                "unit",
                "materials_source",
                "spec_reference",
                "process_id",
                "process_version_id",
                "source_output_id",
            },
        )
        for field, limit in (("product_name", 255), ("unit", 50)):
            if field in data or creating:
                setattr(row, field, text_value(data.get(field), field, limit))
        if "quantity" in data or creating:
            try:
                quantity = Decimal(str(data.get("quantity")))
            except (InvalidOperation, ValueError, TypeError):
                raise OrderError("quantity must be a positive decimal") from None
            if not quantity.is_finite() or quantity <= 0 or quantity >= Decimal("100000000000000"):
                raise OrderError("quantity must be a positive decimal within storage limits")
            if quantity != quantity.quantize(Decimal("0.0001")):
                raise OrderError("quantity supports at most four decimal places")
            row.quantity = quantity
        if is_count_unit(row.unit) and row.quantity != row.quantity.to_integral_value():
            raise OrderError("Counted products require a whole quantity")
        if "materials_source" in data or creating:
            source = data.get("materials_source")
            if source not in MATERIALS_SOURCES:
                raise OrderError("Choose producer, customer or mixed materials")
            row.materials_source = source
        if "spec_reference" in data:
            row.spec_reference = text_value(data["spec_reference"], "spec_reference", 500, False)
        for field in ("process_id", "process_version_id", "source_output_id"):
            if field in data:
                setattr(row, field, identifier(data[field], field) if data[field] else None)
        if (
            row.process_id
            and self.db.query(Process.id).filter(Process.org_id == self.org_id, Process.id == row.process_id).first()
            is None
        ):
            raise OrderError("Workflow not found", 404)
        version = None
        if row.process_version_id:
            version = (
                self.db.query(ProcessVersion)
                .filter(ProcessVersion.org_id == self.org_id, ProcessVersion.id == row.process_version_id)
                .first()
            )
            if version is None or (row.process_id and row.process_id != version.process_id):
                raise OrderError("Recipe version does not belong to this workflow", 404)
            row.process_id = version.process_id
        if row.source_output_id:
            outputs = [
                output
                for step in (version.snapshot.get("steps", []) if version else [])
                for output in (step.get("outputs") or [])
                if isinstance(output, dict)
            ]
            if not any(str(output.get("id")) == str(row.source_output_id) for output in outputs):
                raise OrderError("Product output must belong to the selected recipe version")

    def add_line(self, order_id, data):
        order = self.order(order_id, lock=True)
        if order.status in {"completed", "cancelled"}:
            raise OrderError("Closed orders cannot gain lines", 409)
        row = ContractOrderLine(org_id=self.org_id, order_id=order.id)
        self._line_fields(row, data, True)
        self.db.add(row)
        self.db.flush()
        self._event(
            "line_created", "contract_order_line", row, {"order_id": str(order.id), "quantity": str(row.quantity)}
        )
        return row

    def update_line(self, order_id, line_id, data):
        order = self.order(order_id, lock=True)
        row = self.line(order.id, line_id)
        if order.status in {"completed", "cancelled"} or row.batches:
            raise OrderError("Closed or batch-linked lines cannot be changed", 409)
        self._line_fields(row, data)
        self.db.flush()
        self._event(
            "line_updated", "contract_order_line", row, {"order_id": str(order.id), "quantity": str(row.quantity)}
        )
        return row

    def link_batch(self, order_id, line_id, execution_id):
        # Production locks execution before its contract scope. Protect both an
        # existing assignment and its absence with the same order of locks.
        execution = (
            self.db.query(Execution)
            .filter(Execution.org_id == self.org_id, Execution.id == identifier(execution_id, "execution_id"))
            .with_for_update()
            .populate_existing()
            .first()
        )
        if execution is None:
            raise OrderError("Batch not found", 404)
        order = self.order(order_id, lock=True)
        line = self.line(order.id, line_id)
        if order.status != "confirmed":
            raise OrderError("Confirm the order before linking batches", 409)
        if execution.status in {ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}:
            raise OrderError("Failed or cancelled batches cannot be linked", 409)
        if line.process_id and line.process_id != execution.process_id:
            raise OrderError("Batch does not use the order line's workflow")
        # The legacy model omits the mapped version column; read the creation event's
        # immutable version snapshot instead of trusting a caller's claimed version.
        if line.process_version_id:
            from app.core.db.models.entity_event import EntityEvent

            event = (
                self.db.query(EntityEvent)
                .filter(
                    EntityEvent.org_id == self.org_id,
                    EntityEvent.entity_id == execution.id,
                    EntityEvent.event_type == "execution.created",
                    EntityEvent.entity_type == "execution",
                )
                .first()
            )
            if event is None or str((event.payload or {}).get("process_version_id")) != str(line.process_version_id):
                raise OrderError("Batch does not use the order line's recipe version")
        existing = (
            self.db.query(ContractOrderExecution)
            .filter(ContractOrderExecution.org_id == self.org_id, ContractOrderExecution.execution_id == execution.id)
            .first()
        )
        if existing:
            if existing.line_id == line.id:
                return existing
            raise OrderError("Batch is already linked to another order line", 409)
        row = ContractOrderExecution(org_id=self.org_id, order_id=order.id, line_id=line.id, execution_id=execution.id)
        self.db.add(row)
        self.db.flush()
        self._event(
            "batch_linked", "contract_order", order, {"line_id": str(line.id), "execution_id": str(execution.id)}
        )
        return row

    def unlink_batch(self, order_id, line_id, execution_id):
        execution = (
            self.db.query(Execution)
            .filter(Execution.org_id == self.org_id, Execution.id == identifier(execution_id, "execution_id"))
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if execution is None:
            raise OrderError("Batch not found", 404)
        order = self.order(order_id, lock=True)
        line = self.line(order.id, line_id)
        row = (
            self.db.query(ContractOrderExecution)
            .filter(
                ContractOrderExecution.org_id == self.org_id,
                ContractOrderExecution.order_id == order.id,
                ContractOrderExecution.line_id == line.id,
                ContractOrderExecution.execution_id == execution.id,
            )
            .first()
        )
        if row is None:
            raise OrderError("Batch link not found", 404)
        has_work = (
            self.db.query(ExecutionStep.id)
            .filter(
                ExecutionStep.org_id == self.org_id,
                ExecutionStep.execution_id == execution.id,
                ExecutionStep.status == ExecutionStepStatus.COMPLETED,
            )
            .first()
        )
        if order.status in {"completed", "cancelled"} or has_work or execution.status == ExecutionStatus.COMPLETED:
            raise OrderError("A closed order or worked batch keeps its historical association", 409)
        self.db.delete(row)
        self._event(
            "batch_unlinked", "contract_order", order, {"line_id": str(line.id), "execution_id": str(execution.id)}
        )
        self.db.flush()


def serialize_customer(row):
    return {
        "id": str(row.id),
        "name": row.name,
        "crm_contact_id": str(row.crm_contact_id) if row.crm_contact_id else None,
        "is_active": row.is_active,
    }


def serialize_line(row, production=False):
    result = {
        "id": str(row.id),
        "order_id": str(row.order_id),
        "product_name": row.product_name,
        "quantity": format(row.quantity, "f"),
        "unit": row.unit,
        "materials_source": row.materials_source,
        "batch_count": len(row.batches),
        "batches": [
            {"execution_id": str(link.execution_id), "status": link.execution.status.value} for link in row.batches
        ],
    }
    if production:
        result.update(
            spec_reference=row.spec_reference,
            process_id=str(row.process_id) if row.process_id else None,
            process_version_id=str(row.process_version_id) if row.process_version_id else None,
            source_output_id=str(row.source_output_id) if row.source_output_id else None,
        )
    return result


def serialize_order(row, production=False):
    return {
        "id": str(row.id),
        "customer_id": str(row.customer_id),
        "customer_name": row.customer.name,
        "reference": row.reference,
        "due_date": row.due_date.isoformat(),
        "status": row.status,
        "duty_responsibility": row.duty_responsibility,
        "customer_cca_reference": row.customer_cca_reference,
        "lines": [serialize_line(line, production) for line in row.lines],
        "planned_ready_date": None,
        "forecast_ready_date": None,
    }
