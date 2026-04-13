"""
Shared test helpers for DAG traversal test suite (production-grade guarantees).

- Invariant assertions (node/edge consistency, uniqueness, execution integrity)
- Synthetic DAG builders (deterministic, small graphs; no demo/seed data)
- Query counting for N+1 regression detection

Do NOT modify DAG traversal implementation (dagtraversal.py).
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.dagtraversal import TraversalResult
from app.core.db.models.execution import Execution
from app.core.db.models.execution_step import ExecutionStep
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.process import Process, ProcessCategory
from app.core.db.models.step import Step
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository

# ---------------------------------------------------------------------------
# 1. Graph correctness invariant assertions
# ---------------------------------------------------------------------------


def assert_traversal_invariants(result: TraversalResult) -> None:
    """
    Enforce graph correctness invariants on every traversal result.
    - Every edge.from_id and edge.to_id exist in nodes
    - Nodes unique by id; edges unique by (from_id, to_id, execution_id)
    - Every edge has valid execution_id (present; empty string allowed for display)
    """
    node_ids = {n["id"] for n in result.nodes}
    # Node uniqueness by id
    assert len(result.nodes) == len(node_ids), "Nodes must be unique by id"
    # No dangling edges
    for edge in result.edges:
        from_id = edge.get("from_id")
        to_id = edge.get("to_id")
        assert from_id is not None, "Edge must have from_id"
        assert to_id is not None, "Edge must have to_id"
        assert from_id in node_ids, f"Edge from_id {from_id} must exist in nodes"
        assert to_id in node_ids, f"Edge to_id {to_id} must exist in nodes"
        assert "execution_id" in edge, "Edge must have execution_id"
    # Edge uniqueness by (from_id, to_id, execution_id)
    edge_keys = {(e["from_id"], e["to_id"], e.get("execution_id", "")) for e in result.edges}
    assert len(result.edges) == len(edge_keys), "Edges must be unique by (from_id, to_id, execution_id)"


# ---------------------------------------------------------------------------
# 2. Synthetic DAG builders (deterministic; tests only)
# ---------------------------------------------------------------------------


def clear_org_synthetic_data(db: Session, org_id: UUID) -> None:
    """Remove all processes, executions, inventory for an org. Use in test teardown for synthetic DAGs."""
    db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete()
    exec_ids = [row[0] for row in db.query(Execution.id).filter(Execution.org_id == org_id).all()]
    if exec_ids:
        db.query(ExecutionStep).filter(ExecutionStep.execution_id.in_(exec_ids)).delete(synchronize_session=False)
    db.query(Execution).filter(Execution.org_id == org_id).delete()
    process_ids = [p.id for p in db.query(Process.id).filter(Process.org_id == org_id).all()]
    if process_ids:
        db.query(Step).filter(Step.process_id.in_(process_ids)).delete(synchronize_session=False)
    db.query(Process).filter(Process.org_id == org_id).delete()
    db.commit()


def build_linear_dag(db: Session, org_id: UUID):
    """
    Build minimal linear DAG: R1 -> W1 -> F1.
    Returns dict with ids: r1_id, w1_id, f1_id, process_id, execution_id.
    """
    process_repo = ProcessRepository(db)
    inv_repo = InventoryRepository(db)
    exec_repo = ExecutionRepository(db)

    process = process_repo.create_process(
        org_id=org_id,
        name="Linear Test Process",
        description="R1->W1->F1",
        category=ProcessCategory.MANUFACTURING,
        is_draft=False,
    )
    process_repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=1,
        position=1000,
        name="Step1",
        inputs=[{"name": "R1", "quantity": 1, "unit": "kg"}],
        outputs=[{"name": "W1", "quantity": 1, "unit": "kg"}],
    )
    process_repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=2,
        position=2000,
        name="Step2",
        inputs=[{"name": "W1", "quantity": 1, "unit": "kg"}],
        outputs=[{"name": "F1", "quantity": 1, "unit": "kg"}],
    )
    r1 = inv_repo.create_inventory_item(
        org_id=org_id,
        name="R1",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        source_execution_id=None,
        source_execution_step_id=None,
    )
    execution = exec_repo.create_execution(org_id=org_id, process_id=process.id)
    exec_steps = (
        db.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.step_number)
        .all()
    )
    # Step 1: R1 -> W1
    exec_repo.complete_step(
        execution_step_id=exec_steps[0].id,
        org_id=org_id,
        actual_inputs=[{"name": "R1", "quantity": 1, "unit": "kg", "inventory_item_id": str(r1.id)}],
        actual_outputs=[{"name": "W1", "quantity": 1, "unit": "kg"}],
    )
    w1 = inv_repo.create_inventory_item(
        org_id=org_id,
        name="W1",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.WORK_IN_PROGRESS.value,
        source_execution_id=execution.id,
        source_execution_step_id=exec_steps[0].id,
        source_step_name="Step1",
    )
    # Step 2: W1 -> F1
    exec_repo.complete_step(
        execution_step_id=exec_steps[1].id,
        org_id=org_id,
        actual_inputs=[{"name": "W1", "quantity": 1, "unit": "kg", "inventory_item_id": str(w1.id)}],
        actual_outputs=[{"name": "F1", "quantity": 1, "unit": "kg"}],
    )
    f1 = inv_repo.create_inventory_item(
        org_id=org_id,
        name="F1",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.FINAL_PRODUCT.value,
        source_execution_id=execution.id,
        source_execution_step_id=exec_steps[1].id,
        source_step_name="Step2",
    )
    return {
        "org_id": org_id,
        "r1_id": r1.id,
        "w1_id": w1.id,
        "f1_id": f1.id,
        "process_id": process.id,
        "execution_id": execution.id,
    }


def build_branching_dag(db: Session, org_id: UUID):
    """
    Build branching DAG: R1 -> W1 -> F1 and R1 -> W2.
    Returns dict with ids: r1_id, w1_id, w2_id, f1_id, ...
    """
    process_repo = ProcessRepository(db)
    inv_repo = InventoryRepository(db)
    exec_repo = ExecutionRepository(db)
    process = process_repo.create_process(
        org_id=org_id,
        name="Branch Test Process",
        description="R1->W1->F1, R1->W2",
        category=ProcessCategory.MANUFACTURING,
        is_draft=False,
    )
    process_repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=1,
        name="R1_to_W1",
        inputs=[{"name": "R1", "quantity": 1, "unit": "kg"}],
        outputs=[{"name": "W1", "quantity": 1, "unit": "kg"}],
    )
    process_repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=2,
        name="R1_to_W2",
        inputs=[{"name": "R1", "quantity": 1, "unit": "kg"}],
        outputs=[{"name": "W2", "quantity": 1, "unit": "kg"}],
    )
    process_repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=3,
        name="W1_to_F1",
        inputs=[{"name": "W1", "quantity": 1, "unit": "kg"}],
        outputs=[{"name": "F1", "quantity": 1, "unit": "kg"}],
    )
    r1 = inv_repo.create_inventory_item(
        org_id=org_id,
        name="R1",
        quantity="2",
        unit="kg",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        source_execution_id=None,
        source_execution_step_id=None,
    )
    execution = exec_repo.create_execution(org_id=org_id, process_id=process.id)
    exec_steps = (
        db.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.step_number)
        .all()
    )
    exec_repo.complete_step(
        execution_step_id=exec_steps[0].id,
        org_id=org_id,
        actual_inputs=[{"name": "R1", "quantity": 1, "unit": "kg", "inventory_item_id": str(r1.id)}],
        actual_outputs=[{"name": "W1", "quantity": 1, "unit": "kg"}],
    )
    w1 = inv_repo.create_inventory_item(
        org_id=org_id,
        name="W1",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.WORK_IN_PROGRESS.value,
        source_execution_id=execution.id,
        source_execution_step_id=exec_steps[0].id,
        source_step_name="R1_to_W1",
    )
    exec_repo.complete_step(
        execution_step_id=exec_steps[1].id,
        org_id=org_id,
        actual_inputs=[{"name": "R1", "quantity": 1, "unit": "kg", "inventory_item_id": str(r1.id)}],
        actual_outputs=[{"name": "W2", "quantity": 1, "unit": "kg"}],
    )
    w2 = inv_repo.create_inventory_item(
        org_id=org_id,
        name="W2",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.WORK_IN_PROGRESS.value,
        source_execution_id=execution.id,
        source_execution_step_id=exec_steps[1].id,
        source_step_name="R1_to_W2",
    )
    exec_repo.complete_step(
        execution_step_id=exec_steps[2].id,
        org_id=org_id,
        actual_inputs=[{"name": "W1", "quantity": 1, "unit": "kg", "inventory_item_id": str(w1.id)}],
        actual_outputs=[{"name": "F1", "quantity": 1, "unit": "kg"}],
    )
    f1 = inv_repo.create_inventory_item(
        org_id=org_id,
        name="F1",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.FINAL_PRODUCT.value,
        source_execution_id=execution.id,
        source_execution_step_id=exec_steps[2].id,
        source_step_name="W1_to_F1",
    )
    return {
        "org_id": org_id,
        "r1_id": r1.id,
        "w1_id": w1.id,
        "w2_id": w2.id,
        "f1_id": f1.id,
        "process_id": process.id,
        "execution_id": execution.id,
    }


def build_large_linear_chain(db: Session, org_id: UUID, length: int = 30):
    """
    Build a linear chain of length nodes: R0 -> W1 -> W2 -> ... -> W(length-1).
    Used to assert traversal terminates without recursion/stack overflow.
    Returns dict with first_id, last_id, all_ids, org_id.
    """
    process_repo = ProcessRepository(db)
    inv_repo = InventoryRepository(db)
    exec_repo = ExecutionRepository(db)
    process = process_repo.create_process(
        org_id=org_id,
        name="Long Chain Process",
        description="Linear chain",
        category=ProcessCategory.MANUFACTURING,
        is_draft=False,
    )
    for i in range(length):
        process_repo.add_step(
            process_id=process.id,
            org_id=org_id,
            step_number=i + 1,
            name=f"Step{i}",
            inputs=[{"name": f"N{i}", "quantity": 1, "unit": "kg"}],
            outputs=[{"name": f"N{i+1}", "quantity": 1, "unit": "kg"}],
        )
    r0 = inv_repo.create_inventory_item(
        org_id=org_id,
        name="N0",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        source_execution_id=None,
        source_execution_step_id=None,
    )
    execution = exec_repo.create_execution(org_id=org_id, process_id=process.id)
    exec_steps = (
        db.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.step_number)
        .all()
    )
    prev = r0
    all_ids = [r0.id]
    for i, exec_step in enumerate(exec_steps):
        exec_repo.complete_step(
            execution_step_id=exec_step.id,
            org_id=org_id,
            actual_inputs=[{"name": f"N{i}", "quantity": 1, "unit": "kg", "inventory_item_id": str(prev.id)}],
            actual_outputs=[{"name": f"N{i+1}", "quantity": 1, "unit": "kg"}],
        )
        is_final = i == len(exec_steps) - 1
        inv_type = InventoryType.FINAL_PRODUCT.value if is_final else InventoryType.WORK_IN_PROGRESS.value
        next_item = inv_repo.create_inventory_item(
            org_id=org_id,
            name=f"N{i+1}",
            quantity="1",
            unit="kg",
            inventory_type=inv_type,
            source_execution_id=execution.id,
            source_execution_step_id=exec_step.id,
            source_step_name=f"Step{i}",
        )
        prev = next_item
        all_ids.append(next_item.id)
    return {"org_id": org_id, "first_id": r0.id, "last_id": prev.id, "all_ids": all_ids}


def build_id_only_lineage_dag(db: Session, org_id: UUID):
    """
    Build two raw materials with the SAME name "SameName", different IDs.
    Only one is used in a linear chain. Traversal must use IDs, not names.
    Returns dict: used_raw_id, unused_raw_id, final_id, org_id.
    """
    process_repo = ProcessRepository(db)
    inv_repo = InventoryRepository(db)
    exec_repo = ExecutionRepository(db)
    used_raw = inv_repo.create_inventory_item(
        org_id=org_id,
        name="SameName",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        source_execution_id=None,
        source_execution_step_id=None,
    )
    unused_raw = inv_repo.create_inventory_item(
        org_id=org_id,
        name="SameName",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        source_execution_id=None,
        source_execution_step_id=None,
    )
    process = process_repo.create_process(
        org_id=org_id,
        name="ID Lineage Process",
        description="Uses only one SameName",
        category=ProcessCategory.MANUFACTURING,
        is_draft=False,
    )
    process_repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=1,
        name="Step1",
        inputs=[{"name": "SameName", "quantity": 1, "unit": "kg"}],
        outputs=[{"name": "Output", "quantity": 1, "unit": "kg"}],
    )
    execution = exec_repo.create_execution(org_id=org_id, process_id=process.id)
    exec_steps = (
        db.query(ExecutionStep)
        .filter(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.step_number)
        .all()
    )
    exec_repo.complete_step(
        execution_step_id=exec_steps[0].id,
        org_id=org_id,
        actual_inputs=[{"name": "SameName", "quantity": 1, "unit": "kg", "inventory_item_id": str(used_raw.id)}],
        actual_outputs=[{"name": "Output", "quantity": 1, "unit": "kg"}],
    )
    final_item = inv_repo.create_inventory_item(
        org_id=org_id,
        name="Output",
        quantity="1",
        unit="kg",
        inventory_type=InventoryType.FINAL_PRODUCT.value,
        source_execution_id=execution.id,
        source_execution_step_id=exec_steps[0].id,
        source_step_name="Step1",
    )
    return {
        "org_id": org_id,
        "used_raw_id": used_raw.id,
        "unused_raw_id": unused_raw.id,
        "final_id": final_item.id,
    }


# ---------------------------------------------------------------------------
# 3. Query count instrumentation (N+1 regression guard)
# ---------------------------------------------------------------------------


class QueryCounter:
    """Count SQL executes during a block. Use as regression sentinel for N+1."""

    def __init__(self, session: Session):
        self.session = session
        self.count = 0
        self._handler = None

    def __enter__(self):
        from sqlalchemy import event

        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            self.count += 1

        self._handler = after_cursor_execute
        event.listen(self.session.get_bind(), "after_cursor_execute", self._handler)
        return self

    def __exit__(self, *args):
        from sqlalchemy import event

        if self._handler:
            event.remove(self.session.get_bind(), "after_cursor_execute", self._handler)
        return False
