@core_bp.route("/api/core/inventory/trace/<raw_material_id>", methods=["GET"])
@requires_auth
def trace_raw_material(raw_material_id: str):
    """Trace forward from a raw material to find all connected intermediates and final products

    Uses DAG traversal to find all inventory items that trace back to this raw material.
    Returns only items with quantity > 0, except for the raw material itself (if consumed).
    """
    org_id = UUID(g.org_id)
    try:
        raw_material_uuid = UUID(raw_material_id)
    except ValueError:
        return jsonify({"error": "Invalid raw material ID"}), 400

    # Import models
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.process import Process

    # Get the raw material
    raw_material = (
        db_session.query(InventoryItem)
        .filter(InventoryItem.id == raw_material_uuid, InventoryItem.org_id == org_id)
        .first()
    )

    if not raw_material:
        return jsonify({"error": "Raw material not found"}), 404

    # Helper function to trace forward from an inventory item
    def trace_forward(inventory_item_id, visited_step_ids=None, depth=0):
        """Recursively trace forward through execution steps to find connected inventory items

        Args:
            inventory_item_id: UUID of inventory item to trace from
            visited_step_ids: Set of visited execution step IDs to prevent cycles
            depth: Current recursion depth (for safety limits)

        Returns:
            Set of inventory item IDs that are connected
        """
        max_dag_depth = 50
        if depth > max_dag_depth:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"DAG forward traversal depth limit ({max_dag_depth}) reached")
            return set()

        if visited_step_ids is None:
            visited_step_ids = set()

        connected_items = set()

        # Find all execution steps that use this inventory item as input
        # Filter by org_id through the execution relationship
        from app.core.db.models.execution import Execution

        all_execution_steps = (
            db_session.query(ExecutionStep)
            .join(Execution, ExecutionStep.execution_id == Execution.id)
            .filter(Execution.org_id == org_id)
            .all()
        )
        steps_using_item = []

        for step in all_execution_steps:
            if step.id in visited_step_ids:
                continue
            if not step.actual_inputs:
                continue

            # Check if this step uses the inventory item
            uses_item = False
            for input_data in step.actual_inputs:
                input_item_id = input_data.get("inventory_item_id")
                if input_item_id and str(input_item_id) == str(inventory_item_id):
                    uses_item = True
                    break
                # Also check by name (for backward compatibility)
                input_name = input_data.get("name")
                if input_name:
                    # Convert inventory_item_id to UUID if it's a string
                    item_id_uuid = UUID(inventory_item_id) if isinstance(inventory_item_id, str) else inventory_item_id
                    item = (
                        db_session.query(InventoryItem)
                        .filter(InventoryItem.id == item_id_uuid)
                        .filter(InventoryItem.org_id == org_id)
                        .first()
                    )
                    if item and input_name.lower() == item.name.lower():
                        uses_item = True
                        break

            if uses_item:
                steps_using_item.append(step)
                visited_step_ids.add(step.id)

        # For each step that uses this item, find all inventory items it produces
        for step in steps_using_item:
            # Find all inventory items produced by this step
            # Don't filter by quantity here - we want to trace through all items
            # Filtering happens later when building the response
            produced_items = (
                db_session.query(InventoryItem)
                .filter(InventoryItem.source_execution_step_id == step.id, InventoryItem.org_id == org_id)
                .all()
            )

            for produced_item in produced_items:
                connected_items.add(produced_item.id)
                # Recursively trace forward from this produced item
                next_items = trace_forward(produced_item.id, visited_step_ids, depth + 1)
                connected_items.update(next_items)

        return connected_items

    # Trace forward from the raw material
    connected_item_ids = trace_forward(raw_material_uuid)

    # Helper function to trace backwards from an inventory item to find raw materials
    # This ensures we get direct connections based on execution_id
    def trace_backward(inventory_item_id, visited_item_ids=None, depth=0):
        """Recursively trace backwards through execution steps to find raw materials

        Args:
            inventory_item_id: UUID of inventory item to trace from
            visited_item_ids: Set of visited inventory item IDs to prevent cycles
            depth: Current recursion depth (for safety limits)

        Returns:
            Set of raw material IDs that this item traces back to
        """
        max_dag_depth = 50
        if depth > max_dag_depth:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"DAG backward traversal depth limit ({max_dag_depth}) reached")
            return set()

        if visited_item_ids is None:
            visited_item_ids = set()

        # Convert to string for set comparison
        item_id_str = str(inventory_item_id)
        if item_id_str in visited_item_ids:
            return set()  # Cycle detected
        visited_item_ids.add(item_id_str)

        raw_material_ids = set()

        # Get the inventory item - convert to UUID if needed
        item_id_uuid = UUID(inventory_item_id) if isinstance(inventory_item_id, str) else inventory_item_id
        item = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id == item_id_uuid)
            .filter(InventoryItem.org_id == org_id)
            .first()
        )

        if not item or not item.source_execution_step_id:
            return raw_material_ids

        # If this is a raw material, return it
        if item.inventory_type == InventoryType.RAW_MATERIAL.value:
            raw_material_ids.add(item.id)
            return raw_material_ids

        # Get the execution step that produced this item
        execution_step = (
            db_session.query(ExecutionStep).filter(ExecutionStep.id == item.source_execution_step_id).first()
        )

        if not execution_step or not execution_step.actual_inputs:
            return raw_material_ids

        # Check each input to see if it's a raw material or needs further tracing
        for input_data in execution_step.actual_inputs:
            input_item_id = input_data.get("inventory_item_id")
            if not input_item_id:
                continue

            # Get the input inventory item - convert to UUID if needed
            input_item_id_uuid = UUID(input_item_id) if isinstance(input_item_id, str) else input_item_id
            input_item = (
                db_session.query(InventoryItem)
                .filter(InventoryItem.id == input_item_id_uuid)
                .filter(InventoryItem.org_id == org_id)
                .first()
            )

            if not input_item:
                continue

            # If it's a raw material, add it
            if input_item.inventory_type == InventoryType.RAW_MATERIAL.value:
                raw_material_ids.add(input_item.id)
            else:
                # Recursively trace backwards from this intermediate
                prev_raw_materials = trace_backward(input_item.id, visited_item_ids, depth + 1)
                raw_material_ids.update(prev_raw_materials)

        return raw_material_ids

    # Build connection map: for each connected item, find which raw materials it traces back to
    # Only include connections where the raw material matches our traced raw material
    connections = []  # List of {from_id, to_id, execution_id} tuples

    # Get all connected inventory items
    connected_items = []
    if connected_item_ids:
        items = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id.in_(connected_item_ids), InventoryItem.org_id == org_id)
            .all()
        )

        for item in items:
            # Filter: only include items with quantity > 0, OR the raw material itself (for traceability)
            try:
                qty_str = str(item.quantity).strip() if item.quantity else "0"
                quantity_decimal = Decimal(qty_str)
                # Include if quantity > 0, or if it's the raw material itself (for consumed traceability)
                if quantity_decimal > 0 or item.id == raw_material_uuid:
                    # Build extra_data similar to list_inventory
                    extra_data = item.extra_data if item.extra_data else {}

                    # Get execution prompts from execution step if not in extra_data
                    if not extra_data.get("execution_prompts") and item.source_execution_step_id:
                        try:
                            execution_step = (
                                db_session.query(ExecutionStep)
                                .filter(ExecutionStep.id == item.source_execution_step_id)
                                .first()
                            )
                            if execution_step and execution_step.execution_data:
                                execution_prompts = {}
                                internal_fields = {"completed_by_email", "completed_by_user_id", "completed_at"}
                                for key, value in execution_step.execution_data.items():
                                    if key not in internal_fields and value is not None and value != "":
                                        execution_prompts[key] = value
                                if execution_prompts:
                                    extra_data["execution_prompts"] = execution_prompts

                                # Include variable inputs and outputs
                                if not extra_data.get("variable_inputs") and execution_step.actual_inputs:
                                    extra_data["variable_inputs"] = execution_step.actual_inputs
                                if not extra_data.get("variable_output") and execution_step.actual_outputs:
                                    output_name = item.name
                                    matching_output = next(
                                        (o for o in execution_step.actual_outputs if o.get("name") == output_name), None
                                    )
                                    if matching_output:
                                        extra_data["variable_output"] = matching_output
                        except Exception:
                            pass

                    # Get process name
                    process_name = None
                    if item.source_execution_id:
                        try:
                            execution = (
                                db_session.query(Execution).filter(Execution.id == item.source_execution_id).first()
                            )
                            if execution and execution.process_id:
                                process = db_session.query(Process).filter(Process.id == execution.process_id).first()
                                if process:
                                    process_name = process.name
                        except Exception:
                            pass

                    # Trace backwards to verify this item connects to our raw material
                    traced_raw_materials = trace_backward(item.id)

                    # Only include if it traces back to our raw material
                    if raw_material_uuid in traced_raw_materials:
                        # Add connection: raw material -> this item (based on execution_id)
                        if item.source_execution_id:
                            connections.append(
                                {
                                    "from_id": str(raw_material_uuid),
                                    "to_id": str(item.id),
                                    "execution_id": str(item.source_execution_id),
                                }
                            )

                        connected_items.append(
                            {
                                "id": str(item.id),
                                "name": item.name,
                                "quantity": item.quantity,
                                "unit": item.unit,
                                "inventory_type": item.inventory_type,
                                "supplier": item.supplier,
                                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                                "supplier_batch_number": item.supplier_batch_number,
                                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                                "source_execution_id": str(item.source_execution_id)
                                if item.source_execution_id
                                else None,
                                "source_execution_step_id": str(item.source_execution_step_id)
                                if item.source_execution_step_id
                                else None,
                                "source_step_name": item.source_step_name,
                                "process_name": process_name,
                                "created_at": item.created_at.isoformat() if item.created_at else None,
                                "extra_data": extra_data,
                            }
                        )
            except (InvalidOperation, ValueError, TypeError):
                continue

    # Build intermediate-to-output connections using execution_id as the core tracing mechanism
    # Items in the same execution with sequential steps are connected through the execution flow
    #
    # Strategy: Group all connected items by execution_id, then within each execution,
    # connect items based on step sequence and actual_inputs verification
    non_raw_items = [item for item in connected_items if item["inventory_type"] != InventoryType.RAW_MATERIAL.value]

    # Group items by execution_id
    items_by_execution = {}
    for item in non_raw_items:
        exec_id = item.get("source_execution_id")
        if exec_id:
            if exec_id not in items_by_execution:
                items_by_execution[exec_id] = []
            items_by_execution[exec_id].append(item)

    # For each execution, build connections based on step sequence
    for exec_id, items in items_by_execution.items():
        if len(items) < 2:
            continue  # Need at least 2 items to have a connection

        # Get step numbers for all items in this execution
        step_info = {}
        for item in items:
            step_id = item.get("source_execution_step_id")
            if step_id:
                step = db_session.query(ExecutionStep).filter(ExecutionStep.id == UUID(step_id)).first()
                if step:
                    step_info[item["id"]] = {
                        "item": item,
                        "step": step,
                        "step_number": step.step_number,
                    }

        # Sort items by step number
        sorted_items = sorted(step_info.values(), key=lambda x: x["step_number"])

        # Connect items based on actual_inputs - the step that produces an output
        # should reference its inputs via inventory_item_id
        for i, later_info in enumerate(sorted_items):
            later_step = later_info["step"]
            later_item = later_info["item"]

            if not later_step.actual_inputs:
                continue

            # Check which earlier items were used as inputs to this step
            for earlier_info in sorted_items[:i]:
                earlier_item = earlier_info["item"]

                # Verify the later step actually used this earlier item as input
                uses_earlier = any(
                    input_data.get("inventory_item_id")
                    and str(input_data.get("inventory_item_id")) == earlier_item["id"]
                    for input_data in later_step.actual_inputs
                )

                if uses_earlier:
                    # Add connection if not already exists
                    if not any(
                        c["from_id"] == earlier_item["id"] and c["to_id"] == later_item["id"] for c in connections
                    ):
                        connections.append(
                            {
                                "from_id": earlier_item["id"],
                                "to_id": later_item["id"],
                                "execution_id": exec_id,
                            }
                        )

    # Always include the raw material itself (even if consumed) for traceability
    raw_material_data = {
        "id": str(raw_material.id),
        "name": raw_material.name,
        "quantity": raw_material.quantity,
        "unit": raw_material.unit,
        "inventory_type": raw_material.inventory_type,
        "supplier": raw_material.supplier,
        "purchase_date": raw_material.purchase_date.isoformat() if raw_material.purchase_date else None,
        "supplier_batch_number": raw_material.supplier_batch_number,
        "expiry_date": raw_material.expiry_date.isoformat() if raw_material.expiry_date else None,
        "source_execution_id": str(raw_material.source_execution_id) if raw_material.source_execution_id else None,
        "source_execution_step_id": str(raw_material.source_execution_step_id)
        if raw_material.source_execution_step_id
        else None,
        "source_step_name": raw_material.source_step_name,
        "process_name": None,
        "created_at": raw_material.created_at.isoformat() if raw_material.created_at else None,
        "extra_data": raw_material.extra_data if raw_material.extra_data else {},
    }

    # Check if raw material is already in connected_items
    if not any(item["id"] == str(raw_material.id) for item in connected_items):
        connected_items.insert(0, raw_material_data)

    # Separate into intermediates and finals
    intermediates = [item for item in connected_items if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value]
    finals = [item for item in connected_items if item["inventory_type"] == InventoryType.FINAL_PRODUCT.value]

    return jsonify(
        {
            "raw_material": raw_material_data,
            "intermediates": intermediates,
            "finals": finals,
            "all_items": connected_items,
            "connections": connections,  # Direct connections based on execution_id
        }
    ), 200


@core_bp.route("/api/core/inventory/trace-backward/<inventory_item_id>", methods=["GET"])
@requires_auth
def trace_inventory_backward(inventory_item_id: str):
    """Trace backward from any inventory item (raw, intermediate, or final) to find all source items

    Uses DAG traversal to find all inventory items that contributed to this item.
    Returns only items with quantity > 0, except for the traced item itself (if consumed).
    """
    org_id = UUID(g.org_id)
    try:
        item_uuid = UUID(inventory_item_id)
    except ValueError:
        return jsonify({"error": "Invalid inventory item ID"}), 400

    # Import models
    from app.core.db.models.execution import Execution
    from app.core.db.models.execution_step import ExecutionStep
    from app.core.db.models.inventory_item import InventoryItem
    from app.core.db.models.process import Process

    # Get the inventory item
    traced_item = (
        db_session.query(InventoryItem).filter(InventoryItem.id == item_uuid, InventoryItem.org_id == org_id).first()
    )

    if not traced_item:
        return jsonify({"error": "Inventory item not found"}), 404

    # Helper function to trace backward from an inventory item
    def trace_backward(inventory_item_id, visited_item_ids=None, depth=0):
        """Recursively trace backwards through execution steps to find source items

        Args:
            inventory_item_id: UUID of inventory item to trace from
            visited_item_ids: Set of visited inventory item IDs to prevent cycles
            depth: Current recursion depth (for safety limits)

        Returns:
            Set of source inventory item IDs (raw materials and intermediates)
        """
        max_dag_depth = 50
        if depth > max_dag_depth:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"DAG backward traversal depth limit ({max_dag_depth}) reached")
            return set()

        if visited_item_ids is None:
            visited_item_ids = set()

        # Convert to string for set comparison
        item_id_str = str(inventory_item_id)
        if item_id_str in visited_item_ids:
            return set()  # Cycle detected
        visited_item_ids.add(item_id_str)

        source_item_ids = set()

        # Get the inventory item - convert to UUID if needed
        item_id_uuid = UUID(inventory_item_id) if isinstance(inventory_item_id, str) else inventory_item_id
        item = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id == item_id_uuid)
            .filter(InventoryItem.org_id == org_id)
            .first()
        )

        if not item or not item.source_execution_step_id:
            return source_item_ids

        # Get the execution step that produced this item
        execution_step = (
            db_session.query(ExecutionStep).filter(ExecutionStep.id == item.source_execution_step_id).first()
        )

        if not execution_step or not execution_step.actual_inputs:
            return source_item_ids

        # Check each input to find source items
        for input_data in execution_step.actual_inputs:
            input_item_id = input_data.get("inventory_item_id")
            if not input_item_id:
                continue

            # Get the input inventory item - convert to UUID if needed
            input_item_id_uuid = UUID(input_item_id) if isinstance(input_item_id, str) else input_item_id
            input_item = (
                db_session.query(InventoryItem)
                .filter(InventoryItem.id == input_item_id_uuid)
                .filter(InventoryItem.org_id == org_id)
                .first()
            )

            if not input_item:
                continue

            # Add this source item
            source_item_ids.add(input_item.id)
            # Recursively trace backwards from this source item
            prev_source_items = trace_backward(input_item.id, visited_item_ids, depth + 1)
            source_item_ids.update(prev_source_items)

        return source_item_ids

    # Trace backward from the item
    source_item_ids = trace_backward(item_uuid)

    # Build connection map: for each source item, create connection to traced item
    connections = []  # List of {from_id, to_id, execution_id} tuples

    # Get all source inventory items
    source_items = []
    if source_item_ids:
        items = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.id.in_(source_item_ids), InventoryItem.org_id == org_id)
            .all()
        )

        for item in items:
            # Filter: only include items with quantity > 0, OR the traced item itself (for traceability)
            try:
                qty_str = str(item.quantity).strip() if item.quantity else "0"
                quantity_decimal = Decimal(qty_str)
                # Include if quantity > 0, or if it's the traced item itself (for consumed traceability)
                if quantity_decimal > 0 or item.id == item_uuid:
                    # Build extra_data similar to list_inventory
                    extra_data = item.extra_data if item.extra_data else {}

                    # Get execution prompts from execution step if not in extra_data
                    if not extra_data.get("execution_prompts") and item.source_execution_step_id:
                        try:
                            execution_step = (
                                db_session.query(ExecutionStep)
                                .filter(ExecutionStep.id == item.source_execution_step_id)
                                .first()
                            )
                            if execution_step and execution_step.execution_data:
                                execution_prompts = {}
                                internal_fields = {"completed_by_email", "completed_by_user_id", "completed_at"}
                                for key, value in execution_step.execution_data.items():
                                    if key not in internal_fields and value is not None and value != "":
                                        execution_prompts[key] = value
                                if execution_prompts:
                                    extra_data["execution_prompts"] = execution_prompts

                                # Include variable inputs and outputs
                                if not extra_data.get("variable_inputs") and execution_step.actual_inputs:
                                    extra_data["variable_inputs"] = execution_step.actual_inputs
                                if not extra_data.get("variable_output") and execution_step.actual_outputs:
                                    output_name = item.name
                                    matching_output = next(
                                        (o for o in execution_step.actual_outputs if o.get("name") == output_name), None
                                    )
                                    if matching_output:
                                        extra_data["variable_output"] = matching_output
                        except Exception:
                            pass

                    # Get process name
                    process_name = None
                    if item.source_execution_id:
                        try:
                            execution = (
                                db_session.query(Execution).filter(Execution.id == item.source_execution_id).first()
                            )
                            if execution and execution.process_id:
                                process = db_session.query(Process).filter(Process.id == execution.process_id).first()
                                if process:
                                    process_name = process.name
                        except Exception:
                            pass

                    # Add connection: source item -> traced item (based on execution_id)
                    # Use the traced item's execution_id if available
                    if traced_item.source_execution_id:
                        connections.append(
                            {
                                "from_id": str(item.id),
                                "to_id": str(traced_item.id),
                                "execution_id": str(traced_item.source_execution_id),
                            }
                        )

                    source_items.append(
                        {
                            "id": str(item.id),
                            "name": item.name,
                            "quantity": item.quantity,
                            "unit": item.unit,
                            "inventory_type": item.inventory_type,
                            "supplier": item.supplier,
                            "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                            "supplier_batch_number": item.supplier_batch_number,
                            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                            "source_execution_id": str(item.source_execution_id) if item.source_execution_id else None,
                            "source_execution_step_id": str(item.source_execution_step_id)
                            if item.source_execution_step_id
                            else None,
                            "source_step_name": item.source_step_name,
                            "process_name": process_name,
                            "created_at": item.created_at.isoformat() if item.created_at else None,
                            "extra_data": extra_data,
                        }
                    )
            except (InvalidOperation, ValueError, TypeError):
                continue

    # Always include the traced item itself (even if consumed) for traceability
    traced_item_extra_data = traced_item.extra_data if traced_item.extra_data else {}
    if not traced_item_extra_data.get("execution_prompts") and traced_item.source_execution_step_id:
        try:
            execution_step = (
                db_session.query(ExecutionStep).filter(ExecutionStep.id == traced_item.source_execution_step_id).first()
            )
            if execution_step and execution_step.execution_data:
                execution_prompts = {}
                internal_fields = {"completed_by_email", "completed_by_user_id", "completed_at"}
                for key, value in execution_step.execution_data.items():
                    if key not in internal_fields and value is not None and value != "":
                        execution_prompts[key] = value
                if execution_prompts:
                    traced_item_extra_data["execution_prompts"] = execution_prompts
        except Exception:
            pass

    traced_item_data = {
        "id": str(traced_item.id),
        "name": traced_item.name,
        "quantity": traced_item.quantity,
        "unit": traced_item.unit,
        "inventory_type": traced_item.inventory_type,
        "supplier": traced_item.supplier,
        "purchase_date": traced_item.purchase_date.isoformat() if traced_item.purchase_date else None,
        "supplier_batch_number": traced_item.supplier_batch_number,
        "expiry_date": traced_item.expiry_date.isoformat() if traced_item.expiry_date else None,
        "source_execution_id": str(traced_item.source_execution_id) if traced_item.source_execution_id else None,
        "source_execution_step_id": str(traced_item.source_execution_step_id)
        if traced_item.source_execution_step_id
        else None,
        "source_step_name": traced_item.source_step_name,
        "process_name": None,
        "created_at": traced_item.created_at.isoformat() if traced_item.created_at else None,
        "extra_data": traced_item_extra_data,
    }

    # Check if traced item is already in source_items
    # Exclude the traced item from source_items if it's already there (to avoid duplicates)
    # The traced item will be returned separately in the response
    source_items_without_traced = [item for item in source_items if item["id"] != str(traced_item.id)]

    # Separate into raw materials and intermediates (excluding the traced item itself)
    raw_materials = [
        item for item in source_items_without_traced if item["inventory_type"] == InventoryType.RAW_MATERIAL.value
    ]
    intermediates = [
        item for item in source_items_without_traced if item["inventory_type"] == InventoryType.WORK_IN_PROGRESS.value
    ]

    return jsonify(
        {
            "traced_item": traced_item_data,
            "raw_materials": raw_materials,
            "intermediates": intermediates,
            "all_items": source_items_without_traced,  # Exclude traced item to avoid duplicates
            "connections": connections,  # Direct connections based on execution_id
        }
    ), 200

