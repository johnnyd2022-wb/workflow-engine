"""Mock data for demo user - mirrors the structure from mockData.js"""

# Demo user email
DEMO_USER_EMAIL = "demo@whistlebird.co.nz"

# Mock processes - converted from mockData.js
MOCK_PROCESSES = [
    {
        "id": "proc-001",
        "name": "Pharmaceutical Tablet Manufacturing",
        "description": "End-to-end tablet production from raw materials to packaged product",
        "category": "manufacturing",
        "steps": [
            {
                "id": "step-001",
                "step_number": 1,
                "name": "Raw Material Weighing",
                "description": "Weigh and verify all raw materials according to batch record",
                "inputs": [
                    {
                        "id": "inp-001",
                        "name": "API (Active Ingredient)",
                        "quantity": 50,
                        "unit": "kg",
                        "isStatic": False,
                    },
                    {"id": "inp-002", "name": "Excipient A", "quantity": 25, "unit": "kg", "isStatic": False},
                    {"id": "inp-003", "name": "Excipient B", "quantity": 15, "unit": "kg", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-001", "name": "Weighed Materials", "quantity": 90, "unit": "kg", "isStatic": False},
                ],
            },
            {
                "id": "step-002",
                "step_number": 2,
                "name": "Blending",
                "description": "Blend weighed materials in V-blender for homogeneity",
                "inputs": [
                    {"id": "inp-004", "name": "Weighed Materials", "quantity": 90, "unit": "kg", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-002", "name": "Blended Powder", "quantity": 89.5, "unit": "kg", "isStatic": True},
                ],
            },
            {
                "id": "step-003",
                "step_number": 3,
                "name": "Granulation",
                "description": "Wet granulation process with binder solution",
                "inputs": [
                    {"id": "inp-005", "name": "Blended Powder", "quantity": 89.5, "unit": "kg", "isStatic": True},
                    {"id": "inp-006", "name": "Binder Solution", "quantity": 15, "unit": "L", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-003", "name": "Wet Granules", "quantity": 100, "unit": "kg", "isStatic": True},
                ],
            },
            {
                "id": "step-004",
                "step_number": 4,
                "name": "Drying",
                "description": "Fluid bed drying to target moisture content",
                "inputs": [
                    {"id": "inp-007", "name": "Wet Granules", "quantity": 100, "unit": "kg", "isStatic": True},
                ],
                "outputs": [
                    {"id": "out-004", "name": "Dried Granules", "quantity": 88, "unit": "kg", "isStatic": True},
                ],
            },
            {
                "id": "step-005",
                "step_number": 5,
                "name": "Compression",
                "description": "Tablet compression using rotary press",
                "inputs": [
                    {"id": "inp-008", "name": "Dried Granules", "quantity": 88, "unit": "kg", "isStatic": True},
                ],
                "outputs": [
                    {"id": "out-005", "name": "Uncoated Tablets", "quantity": 175000, "unit": "pcs", "isStatic": True},
                ],
            },
            {
                "id": "step-006",
                "step_number": 6,
                "name": "Coating",
                "description": "Film coating application",
                "inputs": [
                    {"id": "inp-009", "name": "Uncoated Tablets", "quantity": 175000, "unit": "pcs", "isStatic": True},
                    {"id": "inp-010", "name": "Coating Solution", "quantity": 8, "unit": "L", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-006", "name": "Coated Tablets", "quantity": 174500, "unit": "pcs", "isStatic": True},
                ],
            },
        ],
        "active_executions": 2,
        "completed_executions": 1,
        "created_at": "2024-01-15T00:00:00Z",
    },
    {
        "id": "proc-002",
        "name": "Food Grade Oil Refining",
        "description": "Crude oil refining process for food-grade applications",
        "category": "chemical",
        "steps": [
            {
                "id": "step-007",
                "step_number": 1,
                "name": "Degumming",
                "description": "Remove phospholipids and gums from crude oil",
                "inputs": [
                    {"id": "inp-011", "name": "Crude Oil", "quantity": 1000, "unit": "L", "isStatic": False},
                    {"id": "inp-012", "name": "Phosphoric Acid", "quantity": 2, "unit": "L", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-007", "name": "Degummed Oil", "quantity": 980, "unit": "L", "isStatic": True},
                ],
            },
            {
                "id": "step-008",
                "step_number": 2,
                "name": "Neutralization",
                "description": "Neutralize free fatty acids",
                "inputs": [
                    {"id": "inp-013", "name": "Degummed Oil", "quantity": 980, "unit": "L", "isStatic": True},
                    {"id": "inp-014", "name": "Sodium Hydroxide", "quantity": 5, "unit": "kg", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-008", "name": "Neutralized Oil", "quantity": 960, "unit": "L", "isStatic": True},
                ],
            },
            {
                "id": "step-009",
                "step_number": 3,
                "name": "Bleaching",
                "description": "Remove color pigments and impurities",
                "inputs": [
                    {"id": "inp-015", "name": "Neutralized Oil", "quantity": 960, "unit": "L", "isStatic": True},
                    {"id": "inp-016", "name": "Bleaching Earth", "quantity": 10, "unit": "kg", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-009", "name": "Bleached Oil", "quantity": 950, "unit": "L", "isStatic": True},
                ],
            },
            {
                "id": "step-010",
                "step_number": 4,
                "name": "Deodorization",
                "description": "Remove odors and volatile compounds",
                "inputs": [
                    {"id": "inp-017", "name": "Bleached Oil", "quantity": 950, "unit": "L", "isStatic": True},
                ],
                "outputs": [
                    {"id": "out-010", "name": "Refined Oil", "quantity": 940, "unit": "L", "isStatic": True},
                ],
            },
        ],
        "active_executions": 1,
        "completed_executions": 3,
        "created_at": "2024-02-20T00:00:00Z",
    },
    {
        "id": "proc-003",
        "name": "Electronic Component Assembly",
        "description": "PCB assembly and testing workflow",
        "category": "manufacturing",
        "steps": [
            {
                "id": "step-011",
                "step_number": 1,
                "name": "Solder Paste Application",
                "description": "Apply solder paste to PCB pads",
                "inputs": [
                    {"id": "inp-018", "name": "Bare PCB", "quantity": 100, "unit": "pcs", "isStatic": False},
                    {"id": "inp-019", "name": "Solder Paste", "quantity": 50, "unit": "g", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-011", "name": "Pasted PCB", "quantity": 100, "unit": "pcs", "isStatic": False},
                ],
            },
            {
                "id": "step-012",
                "step_number": 2,
                "name": "Component Placement",
                "description": "Place SMD components on PCB",
                "inputs": [
                    {"id": "inp-020", "name": "Pasted PCB", "quantity": 100, "unit": "pcs", "isStatic": False},
                    {
                        "id": "inp-021",
                        "name": "SMD Components Kit",
                        "quantity": 100,
                        "unit": "units",
                        "isStatic": False,
                    },
                ],
                "outputs": [
                    {"id": "out-012", "name": "Populated PCB", "quantity": 100, "unit": "pcs", "isStatic": False},
                ],
            },
            {
                "id": "step-013",
                "step_number": 3,
                "name": "Reflow Soldering",
                "description": "Reflow solder in oven",
                "inputs": [
                    {"id": "inp-022", "name": "Populated PCB", "quantity": 100, "unit": "pcs", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-013", "name": "Soldered PCB", "quantity": 99, "unit": "pcs", "isStatic": True},
                ],
            },
            {
                "id": "step-014",
                "step_number": 4,
                "name": "Inspection & Testing",
                "description": "AOI and functional testing",
                "inputs": [
                    {"id": "inp-023", "name": "Soldered PCB", "quantity": 99, "unit": "pcs", "isStatic": True},
                ],
                "outputs": [
                    {"id": "out-014", "name": "Tested PCB (Pass)", "quantity": 97, "unit": "pcs", "isStatic": True},
                    {"id": "out-015", "name": "Tested PCB (Fail)", "quantity": 2, "unit": "pcs", "isStatic": True},
                ],
            },
        ],
        "active_executions": 1,
        "completed_executions": 5,
        "created_at": "2024-03-10T00:00:00Z",
    },
]

# Mock executions - converted from mockData.js
# Note: Converting 'in-flight' to 'in_progress' and 'currentStep' number to current_step object
MOCK_EXECUTIONS = [
    {
        "id": "exec-001",
        "process_id": "proc-001",
        "status": "in_progress",
        "current_step": {"step_number": 4, "step_id": "step-004", "name": "Drying"},
        "started_at": "2024-12-28T08:00:00Z",
        "completed_at": None,
        "progress": 66.67,
    },
    {
        "id": "exec-002",
        "process_id": "proc-001",
        "status": "in_progress",
        "current_step": {"step_number": 2, "step_id": "step-002", "name": "Blending"},
        "started_at": "2024-12-30T08:00:00Z",
        "completed_at": None,
        "progress": 16.67,
    },
    {
        "id": "exec-003",
        "process_id": "proc-002",
        "status": "in_progress",
        "current_step": {"step_number": 2, "step_id": "step-008", "name": "Neutralization"},
        "started_at": "2024-12-31T06:00:00Z",
        "completed_at": None,
        "progress": 25.0,
    },
    {
        "id": "exec-004",
        "process_id": "proc-003",
        "status": "in_progress",
        "current_step": {"step_number": 3, "step_id": "step-013", "name": "Reflow Soldering"},
        "started_at": "2024-12-31T06:00:00Z",
        "completed_at": None,
        "progress": 50.0,
    },
    {
        "id": "exec-005",
        "process_id": "proc-001",
        "status": "completed",
        "current_step": {"step_number": 6, "step_id": "step-006", "name": "Coating"},
        "started_at": "2024-12-01T08:00:00Z",
        "completed_at": "2024-12-02T16:00:00Z",
        "progress": 100.0,
    },
    {
        "id": "exec-006",
        "process_id": "proc-002",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-010", "name": "Deodorization"},
        "started_at": "2024-12-10T08:00:00Z",
        "completed_at": "2024-12-11T16:00:00Z",
        "progress": 100.0,
    },
    {
        "id": "exec-007",
        "process_id": "proc-002",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-010", "name": "Deodorization"},
        "started_at": "2024-12-15T08:00:00Z",
        "completed_at": "2024-12-16T16:00:00Z",
        "progress": 100.0,
    },
    {
        "id": "exec-008",
        "process_id": "proc-002",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-010", "name": "Deodorization"},
        "started_at": "2024-12-20T08:00:00Z",
        "completed_at": "2024-12-21T16:00:00Z",
        "progress": 100.0,
    },
    {
        "id": "exec-009",
        "process_id": "proc-003",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-014", "name": "Inspection & Testing"},
        "started_at": "2024-12-22T06:00:00Z",
        "completed_at": "2024-12-22T14:00:00Z",
        "progress": 100.0,
    },
    {
        "id": "exec-010",
        "process_id": "proc-003",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-014", "name": "Inspection & Testing"},
        "started_at": "2024-12-24T06:00:00Z",
        "completed_at": "2024-12-24T14:00:00Z",
        "progress": 100.0,
    },
    {
        "id": "exec-011",
        "process_id": "proc-003",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-014", "name": "Inspection & Testing"},
        "started_at": "2024-12-26T06:00:00Z",
        "completed_at": "2024-12-26T14:00:00Z",
        "progress": 100.0,
    },
    {
        "id": "exec-012",
        "process_id": "proc-003",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-014", "name": "Inspection & Testing"},
        "started_at": "2024-12-28T06:00:00Z",
        "completed_at": "2024-12-28T14:00:00Z",
        "progress": 100.0,
    },
    {
        "id": "exec-013",
        "process_id": "proc-003",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-014", "name": "Inspection & Testing"},
        "started_at": "2024-12-29T06:00:00Z",
        "completed_at": "2024-12-29T14:00:00Z",
        "progress": 100.0,
    },
]

# Mock inventory - converted from mockData.js
# Converting 'type' field to 'inventory_type' and mapping values
MOCK_INVENTORY = [
    # Raw materials
    {
        "id": "inv-001",
        "name": "API (Active Ingredient)",
        "quantity": "500",
        "unit": "kg",
        "inventory_type": "raw_material",
        "supplier": "PharmaChem Inc",
        "purchase_date": "2024-12-01",
        "supplier_batch_number": "PC-2024-1201",
        "expiry_date": "2026-12-01",
        "created_at": "2024-12-01T00:00:00Z",
    },
    {
        "id": "inv-002",
        "name": "Excipient A",
        "quantity": "250",
        "unit": "kg",
        "inventory_type": "raw_material",
        "supplier": "ChemSupply Co",
        "purchase_date": "2024-11-15",
        "supplier_batch_number": "CS-2024-1115",
        "expiry_date": "2025-11-15",
        "created_at": "2024-11-15T00:00:00Z",
    },
    {
        "id": "inv-003",
        "name": "Excipient B",
        "quantity": "180",
        "unit": "kg",
        "inventory_type": "raw_material",
        "supplier": "ChemSupply Co",
        "purchase_date": "2024-11-15",
        "supplier_batch_number": "CS-2024-1116",
        "expiry_date": "2025-11-15",
        "created_at": "2024-11-15T00:00:00Z",
    },
    {
        "id": "inv-004",
        "name": "Binder Solution",
        "quantity": "120",
        "unit": "L",
        "inventory_type": "raw_material",
        "supplier": "ChemSupply Co",
        "purchase_date": "2024-11-20",
        "supplier_batch_number": "CS-2024-1120",
        "expiry_date": None,
        "created_at": "2024-11-20T00:00:00Z",
    },
    {
        "id": "inv-005",
        "name": "Coating Solution",
        "quantity": "80",
        "unit": "L",
        "inventory_type": "raw_material",
        "supplier": "CoatChem Ltd",
        "purchase_date": "2024-11-25",
        "supplier_batch_number": "CC-2024-1125",
        "expiry_date": None,
        "created_at": "2024-11-25T00:00:00Z",
    },
    {
        "id": "inv-006",
        "name": "Crude Oil",
        "quantity": "5000",
        "unit": "L",
        "inventory_type": "raw_material",
        "supplier": "OilSource Ltd",
        "purchase_date": "2024-12-10",
        "supplier_batch_number": "OS-2024-1210",
        "expiry_date": None,
        "created_at": "2024-12-10T00:00:00Z",
    },
    {
        "id": "inv-007",
        "name": "Phosphoric Acid",
        "quantity": "42",
        "unit": "L",
        "inventory_type": "raw_material",
        "supplier": "ChemSupply Co",
        "purchase_date": "2024-12-10",
        "supplier_batch_number": "CS-2024-1210",
        "expiry_date": None,
        "created_at": "2024-12-10T00:00:00Z",
    },
    {
        "id": "inv-008",
        "name": "Sodium Hydroxide",
        "quantity": "80",
        "unit": "kg",
        "inventory_type": "raw_material",
        "supplier": "ChemSupply Co",
        "purchase_date": "2024-12-10",
        "supplier_batch_number": "CS-2024-1211",
        "expiry_date": None,
        "created_at": "2024-12-10T00:00:00Z",
    },
    {
        "id": "inv-009",
        "name": "Bleaching Earth",
        "quantity": "160",
        "unit": "kg",
        "inventory_type": "raw_material",
        "supplier": "MineralCorp",
        "purchase_date": "2024-12-10",
        "supplier_batch_number": "MC-2024-1210",
        "expiry_date": None,
        "created_at": "2024-12-10T00:00:00Z",
    },
    {
        "id": "inv-010",
        "name": "Bare PCB",
        "quantity": "1000",
        "unit": "pcs",
        "inventory_type": "raw_material",
        "supplier": "PCB Masters",
        "purchase_date": "2024-12-20",
        "supplier_batch_number": "PM-2024-1220",
        "expiry_date": None,
        "created_at": "2024-12-20T00:00:00Z",
    },
    {
        "id": "inv-011",
        "name": "SMD Components Kit",
        "quantity": "850",
        "unit": "units",
        "inventory_type": "raw_material",
        "supplier": "ElectroParts",
        "purchase_date": "2024-12-22",
        "supplier_batch_number": "EP-2024-1222",
        "expiry_date": None,
        "created_at": "2024-12-22T00:00:00Z",
    },
    {
        "id": "inv-012",
        "name": "Solder Paste",
        "quantity": "200",
        "unit": "g",
        "inventory_type": "raw_material",
        "supplier": "SolderTech",
        "purchase_date": "2024-12-20",
        "supplier_batch_number": "ST-2024-1220",
        "expiry_date": None,
        "created_at": "2024-12-20T00:00:00Z",
    },
    # Intermediate products (work_in_progress)
    {
        "id": "inv-013",
        "name": "Wet Granules",
        "quantity": "99",
        "unit": "kg",
        "inventory_type": "work_in_progress",
        "supplier": None,
        "purchase_date": None,
        "supplier_batch_number": None,
        "expiry_date": None,
        "source_execution_id": "exec-001",
        "source_step_name": "Granulation",
        "created_at": "2024-12-28T14:00:00Z",
    },
    {
        "id": "inv-014",
        "name": "Weighed Materials",
        "quantity": "90",
        "unit": "kg",
        "inventory_type": "work_in_progress",
        "supplier": None,
        "purchase_date": None,
        "supplier_batch_number": None,
        "expiry_date": None,
        "source_execution_id": "exec-002",
        "source_step_name": "Raw Material Weighing",
        "created_at": "2024-12-30T09:45:00Z",
    },
    {
        "id": "inv-015",
        "name": "Degummed Oil",
        "quantity": "978",
        "unit": "L",
        "inventory_type": "work_in_progress",
        "supplier": None,
        "purchase_date": None,
        "supplier_batch_number": None,
        "expiry_date": None,
        "source_execution_id": "exec-003",
        "source_step_name": "Degumming",
        "created_at": "2024-12-31T10:00:00Z",
    },
    {
        "id": "inv-016",
        "name": "Populated PCB",
        "quantity": "100",
        "unit": "pcs",
        "inventory_type": "work_in_progress",
        "supplier": None,
        "purchase_date": None,
        "supplier_batch_number": None,
        "expiry_date": None,
        "source_execution_id": "exec-004",
        "source_step_name": "Component Placement",
        "created_at": "2024-12-31T09:00:00Z",
    },
    # Final products
    {
        "id": "inv-017",
        "name": "Coated Tablets",
        "quantity": "173800",
        "unit": "pcs",
        "inventory_type": "final_product",
        "supplier": None,
        "purchase_date": None,
        "supplier_batch_number": None,
        "expiry_date": None,
        "source_execution_id": "exec-005",
        "source_step_name": "Coating",
        "created_at": "2024-12-02T16:00:00Z",
    },
    {
        "id": "inv-018",
        "name": "Refined Oil",
        "quantity": "2820",
        "unit": "L",
        "inventory_type": "final_product",
        "supplier": None,
        "purchase_date": None,
        "supplier_batch_number": None,
        "expiry_date": None,
        "source_execution_id": "exec-006",
        "source_step_name": "Deodorization",
        "created_at": "2024-12-21T16:00:00Z",
    },
    {
        "id": "inv-019",
        "name": "Tested PCB (Pass)",
        "quantity": "485",
        "unit": "pcs",
        "inventory_type": "final_product",
        "supplier": None,
        "purchase_date": None,
        "supplier_batch_number": None,
        "expiry_date": None,
        "source_execution_id": "exec-009",
        "source_step_name": "Inspection & Testing",
        "created_at": "2024-12-29T14:00:00Z",
    },
]


def is_demo_user(user_email: str | None) -> bool:
    """Check if the user is the demo user"""
    return user_email == DEMO_USER_EMAIL


def get_mock_processes():
    """Get all mock processes"""
    return MOCK_PROCESSES.copy()


def get_mock_process(process_id: str):
    """Get a specific mock process by ID"""
    for process in MOCK_PROCESSES:
        if process["id"] == process_id:
            return process.copy()
    return None


def get_mock_executions(process_id: str | None = None):
    """Get mock executions, optionally filtered by process_id"""
    executions = MOCK_EXECUTIONS.copy()
    if process_id:
        executions = [e for e in executions if e["process_id"] == process_id]
    return executions


def get_mock_inventory(inventory_type: str | None = None, process_id: str | None = None):
    """Get mock inventory items, optionally filtered by type or process_id"""
    all_items = MOCK_INVENTORY.copy()

    # Filter by inventory_type if provided
    if inventory_type:
        # Map frontend types to backend types
        type_map = {
            "raw_material": "raw_material",
            "work_in_progress": "work_in_progress",
            "final_product": "final_product",
            "raw": "raw_material",
            "intermediate": "work_in_progress",
            "final": "final_product",
        }
        mapped_type = type_map.get(inventory_type, inventory_type)
        all_items = [item for item in all_items if item["inventory_type"] == mapped_type]

    # Filter by process_id if provided
    if process_id:
        # Note: We don't have process_id in inventory items directly, but we can filter by source_execution_id
        # For now, return all items if process_id filter is requested
        # This could be enhanced if needed
        pass

    return all_items


def get_mock_metrics():
    """Get mock metrics"""
    total_processes = len(MOCK_PROCESSES)
    active_executions = sum(1 for e in MOCK_EXECUTIONS if e["status"] == "in_progress")
    completed_executions = sum(1 for e in MOCK_EXECUTIONS if e["status"] == "completed")

    raw_materials = len([i for i in MOCK_INVENTORY if i["inventory_type"] == "raw_material"])
    wip = len([i for i in MOCK_INVENTORY if i["inventory_type"] == "work_in_progress"])
    final_products = len([i for i in MOCK_INVENTORY if i["inventory_type"] == "final_product"])
    total_inventory = raw_materials + wip + final_products

    return {
        "total_processes": total_processes,
        "active_executions": active_executions,
        "completed_executions": completed_executions,
        "inventory_items": {
            "total": total_inventory,
            "raw_materials": raw_materials,
            "work_in_progress": wip,
            "final_products": final_products,
        },
    }
