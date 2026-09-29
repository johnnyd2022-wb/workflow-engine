"""Scheduling input, without guessing allocations or treating due dates as forecasts."""

from app.features.contract_manufacturing.services.orders import ContractOrderService


def contract_demand(db, org_id):
    """Confirmed line IDs are stable demand IDs; the planner owns fulfilled quantities.

    Product keys are workflow output IDs. Unmapped lines stay explicit (None), so the
    planner cannot silently match products by name. No stock or WIP is deducted here.
    """
    return [
        {
            "demand_id": str(line.id),
            "source": "contract_order_line",
            "order_id": str(order.id),
            "customer_id": str(order.customer_id),
            "product_key": str(line.source_output_id) if line.source_output_id else None,
            "product_name": line.product_name,
            "quantity": format(line.quantity, "f"),
            "unit": line.unit,
            "due_date": order.due_date.isoformat(),
            "materials_source": line.materials_source,
            "process_id": str(line.process_id) if line.process_id else None,
            "process_version_id": str(line.process_version_id) if line.process_version_id else None,
            "execution_ids": [str(link.execution_id) for link in line.batches],
            "planned_ready_date": None,
            "forecast_ready_date": None,
        }
        for order in ContractOrderService(db, org_id).orders(status="confirmed")
        for line in order.lines
    ]
