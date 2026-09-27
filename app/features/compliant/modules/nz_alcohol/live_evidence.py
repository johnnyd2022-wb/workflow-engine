"""Live NP3 evidence projected from Core's operational DAG.

This module deliberately produces *observations*, not persisted compliance records.  Core
continues to own executions, inventory, files and lineage; Compliant contributes the
domain interpretation and retains the Core IDs used for every audit-register row.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.dagtraversal import DAGTracer
from app.core.db.models.execution_evidence import EVIDENCE_STATUS_ACTIVE, ExecutionEvidence
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.inventory_item import InventoryItem, InventoryType


def _limited_ids(values: Iterable[UUID | str | None], limit: int = 25) -> list[str]:
    """Return stable, bounded source IDs for UI/CSV and avoid unbounded audit payloads."""
    return sorted({str(value) for value in values if value is not None})[:limit]


def _observation(
    control_id: str,
    title: str,
    source_kind: str,
    source_refs: list[str],
    observed_at: Any,
    detail: str,
) -> dict[str, Any]:
    destinations = {
        "core-dag": ("/core/sourcemap?show=check-needed", "Open source map trace"),
        "core-execution": ("/core/executions/live", "Open live executions"),
        "core-evidence-file": ("/core/executions/live", "Open execution evidence"),
        "core-inventory": ("/core/inventory/view", "Open inventory records"),
    }
    workspace_url, workspace_label = destinations[source_kind]
    return {
        "control_id": control_id,
        "title": title,
        "source_kind": source_kind,
        "source_refs": source_refs,
        "observed_at": observed_at,
        "detail": detail,
        # Stable human destinations make the live dashboard useful to an auditor without
        # requiring them to interpret internal UUIDs. IDs remain available as provenance.
        "workspace_url": workspace_url,
        "workspace_label": workspace_label,
    }


def derive_np3_core_evidence(session: Session, org_id: UUID) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project the Core facts that can honestly support NP3 controls today.

    The traceability observation starts at manufactured final-product inventory and walks
    backwards through the actual execution DAG.  This is intentionally different from
    merely counting executions: it proves that Core has a connected product-to-input
    lineage slice and gives the register stable entity IDs for drill-down.
    """
    observations: list[dict[str, Any]] = []

    final_products = (
        session.query(InventoryItem)
        .join(ExecutionStep, ExecutionStep.id == InventoryItem.source_execution_step_id)
        .filter(
            InventoryItem.org_id == org_id,
            InventoryItem.inventory_type == InventoryType.FINAL_PRODUCT.value,
            InventoryItem.source_execution_step_id.isnot(None),
            ExecutionStep.org_id == org_id,
            ExecutionStep.status == ExecutionStepStatus.COMPLETED,
        )
        .order_by(InventoryItem.created_at.desc())
        .limit(100)
        .all()
    )
    dag_edges = 0
    if final_products:
        trace = DAGTracer(org_id=org_id, session=session).traverse(
            start_nodes=[item.id for item in final_products],
            direction="backward",
            include_quantity_filter=False,
        )
        dag_edges = trace.metadata.edges_count
        # A final product with a producing step is a useful source pointer; a connected
        # DAG edge is the stronger traceability fact.  Keep the distinction visible in
        # the description rather than inventing a pass from disconnected data.
        refs = _limited_ids(
            [item.id for item in final_products]
            + [item.source_execution_step_id for item in final_products]
            + [edge["execution_id"] for edge in trace.edges if edge.get("execution_id")]
        )
        if trace.edges:
            observations.append(
                _observation(
                    "trace-and-recall",
                    f"Core DAG trace across {len(final_products)} final-product batch(es)",
                    "core-dag",
                    refs,
                    max((item.updated_at for item in final_products), default=None),
                    f"{len(trace.nodes)} inventory nodes and {len(trace.edges)} lineage edges are connected in Core.",
                )
            )

    completed_steps = (
        session.query(ExecutionStep)
        .filter(
            ExecutionStep.org_id == org_id,
            ExecutionStep.status == ExecutionStepStatus.COMPLETED,
        )
        .order_by(ExecutionStep.completed_at.desc())
        .limit(100)
        .all()
    )
    recorded_steps = [
        step for step in completed_steps if step.actual_inputs or step.actual_outputs or step.execution_data
    ]
    if recorded_steps:
        observations.append(
            _observation(
                "documentation-record-keeping",
                f"{len(recorded_steps)} completed Core step record(s) with operational data",
                "core-execution",
                _limited_ids(step.id for step in recorded_steps),
                max((step.completed_at for step in recorded_steps), default=None),
                "Completed step inputs, outputs or execution prompts are retained in Core.",
            )
        )

    active_files = (
        session.query(ExecutionEvidence)
        .filter(
            ExecutionEvidence.org_id == org_id,
            ExecutionEvidence.evidence_status == EVIDENCE_STATUS_ACTIVE,
        )
        .order_by(ExecutionEvidence.created_at.desc())
        .limit(100)
        .all()
    )
    if active_files:
        observations.append(
            _observation(
                "documentation-record-keeping",
                f"{len(active_files)} active Core evidence file(s)",
                "core-evidence-file",
                _limited_ids(file.id for file in active_files),
                max((file.created_at for file in active_files), default=None),
                "Files remain stored and integrity-checked by Core evidence storage.",
            )
        )

    raw_materials = (
        session.query(InventoryItem)
        .filter(
            InventoryItem.org_id == org_id,
            InventoryItem.inventory_type == InventoryType.RAW_MATERIAL.value,
        )
        .order_by(InventoryItem.updated_at.desc())
        .limit(250)
        .all()
    )
    supplied_materials = [item for item in raw_materials if (item.supplier or "").strip()]
    if supplied_materials:
        observations.append(
            _observation(
                "suppliers-and-purchasing",
                f"{len(supplied_materials)} raw-material record(s) identify a supplier",
                "core-inventory",
                _limited_ids(item.id for item in supplied_materials),
                max((item.updated_at for item in supplied_materials), default=None),
                "Core inventory records preserve the supplier attached to each material entry.",
            )
        )
    received_materials = [
        item
        for item in supplied_materials
        if (item.supplier_batch_number or "").strip() and item.purchase_date is not None
    ]
    if received_materials:
        observations.append(
            _observation(
                "receiving-food",
                f"{len(received_materials)} received raw-material record(s) include supplier, batch and date",
                "core-inventory",
                _limited_ids(item.id for item in received_materials),
                max((item.updated_at for item in received_materials), default=None),
                "Core inventory records preserve supplier, supplier batch and purchase date for these entries.",
            )
        )

    summary = {
        "dag_traced_final_products": len(final_products),
        "dag_lineage_edges": dag_edges,
        "completed_steps_with_operational_data": len(recorded_steps),
        "active_evidence_files": len(active_files),
        "supplier_identified_materials": len(supplied_materials),
        "received_materials_with_batch_and_date": len(received_materials),
        "derived_observations": len(observations),
    }
    return observations, summary
