"""
Reset and populate database with sample data for demo user demo@whistlebird.co.nz only.

Used for product demos and for tests (e.g. DAG traversal tests) that run against real DB.
Theme: distillery (inputs, outputs, processes, inventory with full metadata).
Includes at least one expired raw material so check-needed signal is triggered.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.db.models.execution import Execution, ExecutionStatus
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.inventory_item import InventoryItem, InventoryType
from app.core.db.models.process import Process, ProcessCategory
from app.core.db.models.step import Step
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.user_repo import UserRepository

DEMO_USER_EMAIL = "demo@whistlebird.co.nz"


def reset_demo_db(db: Session) -> dict:
    """
    Reset and populate DB with distillery-themed sample data for demo@whistlebird.co.nz only.

    - Deletes all processes, executions, and inventory for that user's org.
    - Creates one process "Distillery Spirit Production" with steps.
    - Creates raw materials (all fields filled); one has expiry in the past (triggers check-needed).
    - Creates one completed execution with WIP and final inventory linked via source_execution_id/step.

    Returns dict with keys: success (bool), message (str), and optionally error (str).
    """
    user_repo = UserRepository(db)
    user = user_repo.get_user_by_email(DEMO_USER_EMAIL)
    if not user:
        return {
            "success": False,
            "message": f"User {DEMO_USER_EMAIL} not found. Create the demo user first.",
            "error": "USER_NOT_FOUND",
        }
    org_id = user.org_id

    # Delete in order: inventory (refs execution/execution_step), then execution_steps (refs execution), then executions, then processes
    db.query(InventoryItem).filter(InventoryItem.org_id == org_id).delete()
    from app.core.db.models.execution import Execution as ExecModel

    exec_ids = [e.id for e in db.query(ExecModel.id).filter(ExecModel.org_id == org_id).all()]
    if exec_ids:
        db.query(ExecutionStep).filter(ExecutionStep.execution_id.in_(exec_ids)).delete(synchronize_session=False)
    db.query(ExecModel).filter(ExecModel.org_id == org_id).delete()
    # Delete process definition steps before processes (steps.steps_process_id_fkey)
    process_ids = [p.id for p in db.query(Process.id).filter(Process.org_id == org_id).all()]
    if process_ids:
        db.query(Step).filter(Step.process_id.in_(process_ids)).delete(synchronize_session=False)
    db.query(Process).filter(Process.org_id == org_id).delete()
    db.commit()

    # Create process: Distillery Spirit Production
    process_repo = ProcessRepository(db)
    inv_repo = InventoryRepository(db)
    exec_repo = ExecutionRepository(db)

    process = process_repo.create_process(
        org_id=org_id,
        name="Distillery Spirit Production",
        description="End-to-end spirit production from malted barley to bottled whisky",
        category=ProcessCategory.MANUFACTURING,
        is_draft=False,
    )

    # Steps: Mashing, Fermentation, Distillation, Maturation, Bottling
    steps_spec = [
        {
            "step_number": 1,
            "name": "Mashing",
            "description": "Mash malted barley with hot water to extract sugars",
            "inputs": [{"name": "Malted Barley", "quantity": 500, "unit": "kg"}, {"name": "Water", "quantity": 2000, "unit": "L"}],
            "outputs": [{"name": "Mash", "quantity": 2400, "unit": "L"}],
            "execution_prompts": [{"label": "Mash temperature (°C)", "type": "number", "required": True}],
        },
        {
            "step_number": 2,
            "name": "Fermentation",
            "description": "Ferment mash with yeast to produce wash",
            "inputs": [{"name": "Mash", "quantity": 2400, "unit": "L"}, {"name": "Yeast", "quantity": 10, "unit": "kg"}],
            "outputs": [{"name": "Wash", "quantity": 2300, "unit": "L"}],
            "execution_prompts": [{"label": "Fermentation days", "type": "number", "required": True}],
        },
        {
            "step_number": 3,
            "name": "Distillation",
            "description": "Double pot still distillation to produce new-make spirit",
            "inputs": [{"name": "Wash", "quantity": 2300, "unit": "L"}],
            "outputs": [{"name": "New-Make Spirit", "quantity": 350, "unit": "L"}],
            "execution_prompts": [{"label": "Cut points (ABV)", "type": "text", "required": False}],
        },
        {
            "step_number": 4,
            "name": "Maturation",
            "description": "Mature spirit in oak casks",
            "inputs": [{"name": "New-Make Spirit", "quantity": 350, "unit": "L"}, {"name": "Oak Cask", "quantity": 1, "unit": "units"}],
            "outputs": [{"name": "Matured Spirit", "quantity": 320, "unit": "L"}],
            "execution_prompts": [{"label": "Cask type", "type": "text", "required": True}, {"label": "Years matured", "type": "number", "required": True}],
        },
        {
            "step_number": 5,
            "name": "Bottling",
            "description": "Bottle and label final product",
            "inputs": [{"name": "Matured Spirit", "quantity": 320, "unit": "L"}],
            "outputs": [{"name": "Bottled Whisky", "quantity": 400, "unit": "bottles"}],
            "execution_prompts": [{"label": "Batch number", "type": "text", "required": True}],
        },
    ]

    created_steps = []
    for spec in steps_spec:
        step = process_repo.add_step(
            process_id=process.id,
            org_id=org_id,
            step_number=spec["step_number"],
            name=spec["name"],
            description=spec.get("description"),
            inputs=spec.get("inputs", []),
            outputs=spec.get("outputs", []),
            execution_prompts=spec.get("execution_prompts", []),
        )
        created_steps.append(step)

    # Raw materials with all fields filled; create extra so we have leftover stock after the run.
    # One raw (Yeast) is expired 7 days ago so check-needed works regardless of timezone/server date.
    today = date.today()
    expiry_7_days_ago = today - timedelta(days=7)

    raw_barley = inv_repo.create_inventory_item(
        org_id=org_id,
        name="Malted Barley",
        quantity="1000",  # use 500 in step 1, leave 500 in stock
        unit="kg",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        supplier="Highland Malt Co.",
        purchase_date=date(today.year - 1, 6, 15),
        supplier_batch_number="WB-MALT-2024-001",
        expiry_date=date(today.year + 1, 12, 31),
        source_execution_id=None,
        source_execution_step_id=None,
        source_step_name=None,
        extra_data={"origin": "Scotland", "variety": "Concerto"},
    )
    raw_water = inv_repo.create_inventory_item(
        org_id=org_id,
        name="Water",
        quantity="4000",  # use 2000 in step 1, leave 2000 in stock
        unit="L",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        supplier="Local Spring",
        purchase_date=date(today.year, 1, 10),
        supplier_batch_number="WB-WAT-2025-001",
        expiry_date=None,
        source_execution_id=None,
        source_execution_step_id=None,
        source_step_name=None,
        extra_data={"source": "On-site spring", "pH": "7.2"},
    )
    # Expired raw material (7 days ago) -> triggers check-needed; 20 kg so 10 kg left after use
    raw_yeast = inv_repo.create_inventory_item(
        org_id=org_id,
        name="Yeast",
        quantity="20",
        unit="kg",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        supplier="Brewing Supplies Ltd",
        purchase_date=date(today.year - 1, 3, 1),
        supplier_batch_number="WB-YEAST-2024-003",
        expiry_date=expiry_7_days_ago,
        source_execution_id=None,
        source_execution_step_id=None,
        source_step_name=None,
        extra_data={"strain": "Distiller's yeast", "storage": "refrigerated"},
    )
    raw_oak = inv_repo.create_inventory_item(
        org_id=org_id,
        name="Oak Cask",
        quantity="2",  # use 1 in step 4, leave 1 in stock
        unit="units",
        inventory_type=InventoryType.RAW_MATERIAL.value,
        supplier="Cooperage NZ",
        purchase_date=date(today.year - 2, 5, 20),
        supplier_batch_number="WB-OAK-2023-012",
        expiry_date=None,
        source_execution_id=None,
        source_execution_step_id=None,
        source_step_name=None,
        extra_data={"toast_level": "medium", "capacity_l": 350},
    )

    # Actual quantities for this run: partial consumption so we have leftover raw + WIP (e.g. Mash).
    # Step 0: 500 barley, 2000 water -> 2400 Mash. Step 1: 1200 Mash, 5 yeast -> 1150 Wash (1200 Mash left).
    # Step 2: 1150 Wash -> 175 New-Make. Step 3: 175 New-Make, 1 oak -> 160 Matured. Step 4: 160 Matured -> 200 bottles.
    actual_run = [
        {"inputs": [{"name": "Malted Barley", "quantity": 500, "unit": "kg"}, {"name": "Water", "quantity": 2000, "unit": "L"}], "outputs": [{"name": "Mash", "quantity": 2400, "unit": "L"}]},
        {"inputs": [{"name": "Mash", "quantity": 1200, "unit": "L"}, {"name": "Yeast", "quantity": 5, "unit": "kg"}], "outputs": [{"name": "Wash", "quantity": 1150, "unit": "L"}]},
        {"inputs": [{"name": "Wash", "quantity": 1150, "unit": "L"}], "outputs": [{"name": "New-Make Spirit", "quantity": 175, "unit": "L"}]},
        {"inputs": [{"name": "New-Make Spirit", "quantity": 175, "unit": "L"}, {"name": "Oak Cask", "quantity": 1, "unit": "units"}], "outputs": [{"name": "Matured Spirit", "quantity": 160, "unit": "L"}]},
        {"inputs": [{"name": "Matured Spirit", "quantity": 160, "unit": "L"}], "outputs": [{"name": "Bottled Whisky", "quantity": 200, "unit": "bottles"}]},
    ]

    # Create execution and complete each step, creating WIP/final inventory and linking
    execution = exec_repo.create_execution(org_id=org_id, process_id=process.id)
    execution_steps = (
        db.query(ExecutionStep).filter(ExecutionStep.execution_id == execution.id).order_by(ExecutionStep.step_number).all()
    )

    # Track created output items by name for use as inputs in next steps
    output_items_by_name = {
        "Malted Barley": raw_barley,
        "Water": raw_water,
        "Yeast": raw_yeast,
        "Oak Cask": raw_oak,
    }

    for i, exec_step in enumerate(execution_steps):
        step_spec = steps_spec[i]
        run_spec = actual_run[i]
        step = created_steps[i]
        actual_inputs = []
        for inp in run_spec.get("inputs", []):
            iname = inp.get("name")
            item = output_items_by_name.get(iname)
            if item:
                actual_inputs.append({
                    "name": iname,
                    "quantity": inp.get("quantity"),
                    "unit": inp.get("unit"),
                    "inventory_item_id": str(item.id),
                })
        actual_outputs = [{"name": o["name"], "quantity": o["quantity"], "unit": o["unit"]} for o in run_spec.get("outputs", [])]
        execution_data = {"Mash temperature (°C)": 64} if i == 0 else {}
        if i == 1:
            execution_data["Fermentation days"] = 5
        if i == 3:
            execution_data["Cask type"] = "Ex-Bourbon"
            execution_data["Years matured"] = 3
        if i == 4:
            execution_data["Batch number"] = "WB-2025-001"

        exec_repo.complete_step(
            execution_step_id=exec_step.id,
            org_id=org_id,
            actual_inputs=actual_inputs,
            actual_outputs=actual_outputs,
            execution_data=execution_data,
        )

        # Create output inventory items (backend normally does this; we do it here for reset)
        is_terminal = i == len(execution_steps) - 1
        inv_type = InventoryType.FINAL_PRODUCT.value if is_terminal else InventoryType.WORK_IN_PROGRESS.value
        for out in actual_outputs:
            oname = out.get("name")
            oqty = str(out.get("quantity", 0))
            ounit = out.get("unit", "units")
            extra = {"execution_prompts": execution_data, "variable_inputs": actual_inputs, "variable_output": out}
            new_item = inv_repo.create_inventory_item(
                org_id=org_id,
                name=oname,
                quantity=oqty,
                unit=ounit,
                inventory_type=inv_type,
                supplier=None,
                purchase_date=None,
                supplier_batch_number=None,
                expiry_date=None,
                source_execution_id=execution.id,
                source_execution_step_id=exec_step.id,
                source_step_name=step.name,
                extra_data=extra,
            )
            output_items_by_name[oname] = new_item

        # Consume input quantities (decrement)
        for ai in actual_inputs:
            inv_id = ai.get("inventory_item_id")
            if not inv_id:
                continue
            inv = inv_repo.get_inventory_item_by_id(UUID(inv_id), org_id)
            if inv and inv.quantity:
                try:
                    current = Decimal(str(inv.quantity))
                    consumed = Decimal(str(ai.get("quantity", 0)))
                    new_qty = max(Decimal("0"), current - consumed)
                    inv.quantity = str(new_qty.normalize())
                    db.commit()
                except Exception:
                    pass

    return {
        "success": True,
        "message": f"Demo DB reset for {DEMO_USER_EMAIL}: 1 process, 5 steps, 1 execution, inventory with distillery data (including expired raw for check-needed).",
    }
