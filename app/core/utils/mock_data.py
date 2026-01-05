"""Mock data for demo user - mirrors the structure from mockData.js"""

# Demo user email
DEMO_USER_EMAIL = "demo@whistlebird.co.nz"

# Mock processes
MOCK_PROCESSES = [
    {
        "id": "proc-001",
        "name": "Widget Assembly Line A",
        "description": "Primary assembly process for consumer widgets",
        "category": "manufacturing",
        "steps": [
            {
                "id": "step-001",
                "step_number": 1,
                "name": "Raw Material Intake",
                "description": "Receive and quality check incoming materials",
                "inputs": [
                    {"id": "in-001", "name": "Aluminum Sheets", "quantity": 100, "unit": "kg", "isStatic": False},
                    {"id": "in-002", "name": "Plastic Pellets", "quantity": 50, "unit": "kg", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-001", "name": "Verified Materials", "quantity": 145, "unit": "kg", "isStatic": False},
                ],
            },
            {
                "id": "step-002",
                "step_number": 2,
                "name": "Component Fabrication",
                "description": "Machine and mold individual components",
                "inputs": [
                    {"id": "in-003", "name": "Verified Materials", "quantity": 145, "unit": "kg", "isStatic": False},
                    {"id": "in-004", "name": "Machine Time", "quantity": 4, "unit": "hr", "isStatic": True},
                ],
                "outputs": [
                    {"id": "out-002", "name": "Aluminum Parts", "quantity": 200, "unit": "pcs", "isStatic": False},
                    {"id": "out-003", "name": "Plastic Housings", "quantity": 200, "unit": "pcs", "isStatic": False},
                ],
            },
            {
                "id": "step-003",
                "step_number": 3,
                "name": "Assembly",
                "description": "Combine components into finished widgets",
                "inputs": [
                    {"id": "in-005", "name": "Aluminum Parts", "quantity": 200, "unit": "pcs", "isStatic": False},
                    {"id": "in-006", "name": "Plastic Housings", "quantity": 200, "unit": "pcs", "isStatic": False},
                    {"id": "in-007", "name": "Screws", "quantity": 800, "unit": "pcs", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-004", "name": "Assembled Widgets", "quantity": 200, "unit": "units", "isStatic": False},
                ],
            },
            {
                "id": "step-004",
                "step_number": 4,
                "name": "Quality Control",
                "description": "Inspect and test finished products",
                "inputs": [
                    {"id": "in-008", "name": "Assembled Widgets", "quantity": 200, "unit": "units", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-005", "name": "Approved Widgets", "quantity": 195, "unit": "units", "isStatic": False},
                    {"id": "out-006", "name": "Rejected Units", "quantity": 5, "unit": "units", "isStatic": False},
                ],
            },
        ],
        "active_executions": 3,
        "completed_executions": 47,
        "created_at": "2024-01-15T00:00:00Z",
    },
    {
        "id": "proc-002",
        "name": "Chemical Batch Processing",
        "description": "Controlled chemical mixing and reaction process",
        "category": "chemical",
        "steps": [
            {
                "id": "step-005",
                "step_number": 1,
                "name": "Ingredient Preparation",
                "description": "Measure and prepare chemical ingredients",
                "inputs": [
                    {"id": "in-009", "name": "Chemical A", "quantity": 25, "unit": "L", "isStatic": False},
                    {"id": "in-010", "name": "Chemical B", "quantity": 15, "unit": "L", "isStatic": False},
                    {"id": "in-011", "name": "Catalyst", "quantity": 500, "unit": "mL", "isStatic": True},
                ],
                "outputs": [
                    {"id": "out-007", "name": "Prepared Mix", "quantity": 40, "unit": "L", "isStatic": False},
                ],
            },
            {
                "id": "step-006",
                "step_number": 2,
                "name": "Reaction Phase",
                "description": "Controlled reaction at specified temperature",
                "inputs": [
                    {"id": "in-012", "name": "Prepared Mix", "quantity": 40, "unit": "L", "isStatic": False},
                    {"id": "in-013", "name": "Reaction Time", "quantity": 2, "unit": "hr", "isStatic": True},
                    {"id": "in-014", "name": "Temperature", "quantity": 85, "unit": "C", "isStatic": True},
                ],
                "outputs": [
                    {"id": "out-008", "name": "Reacted Compound", "quantity": 38, "unit": "L", "isStatic": False},
                ],
            },
        ],
        "active_executions": 1,
        "completed_executions": 124,
        "created_at": "2024-02-20T00:00:00Z",
    },
    {
        "id": "proc-003",
        "name": "Packaging Line B",
        "description": "Secondary packaging for bulk orders",
        "category": "packaging",
        "steps": [
            {
                "id": "step-007",
                "step_number": 1,
                "name": "Product Sorting",
                "description": "Sort products by size and type",
                "inputs": [
                    {"id": "in-015", "name": "Mixed Products", "quantity": 500, "unit": "units", "isStatic": False},
                ],
                "outputs": [
                    {"id": "out-009", "name": "Sorted Products", "quantity": 500, "unit": "units", "isStatic": False},
                ],
            },
        ],
        "active_executions": 2,
        "completed_executions": 89,
        "created_at": "2024-03-10T00:00:00Z",
    },
]

# Mock executions
MOCK_EXECUTIONS = [
    {
        "id": "exec-001",
        "process_id": "proc-001",
        "status": "in_progress",
        "current_step": {"step_number": 2, "step_id": "step-002", "name": "Component Fabrication"},
        "started_at": "2024-12-28T09:00:00Z",
        "completed_at": None,
        "progress": 25.0,
    },
    {
        "id": "exec-002",
        "process_id": "proc-001",
        "status": "in_progress",
        "current_step": {"step_number": 3, "step_id": "step-003", "name": "Assembly"},
        "started_at": "2024-12-27T14:30:00Z",
        "completed_at": None,
        "progress": 50.0,
    },
    {
        "id": "exec-003",
        "process_id": "proc-001",
        "status": "completed",
        "current_step": {"step_number": 4, "step_id": "step-004", "name": "Quality Control"},
        "started_at": "2024-12-26T08:00:00Z",
        "completed_at": "2024-12-26T16:45:00Z",
        "progress": 100.0,
    },
]

# Mock inventory
MOCK_INVENTORY = {
    "raw_material": [
        {
            "id": "inv-001",
            "name": "Aluminum Sheets",
            "quantity": "2500",
            "unit": "kg",
            "inventory_type": "raw_material",
            "supplier": "MetalCorp Inc.",
            "purchase_date": "2024-12-15",
            "supplier_batch_number": "AL-2024-1215",
            "expiry_date": None,
            "created_at": "2024-12-15T00:00:00Z",
        },
        {
            "id": "inv-002",
            "name": "Plastic Pellets",
            "quantity": "1800",
            "unit": "kg",
            "inventory_type": "raw_material",
            "supplier": "PolymerWorld",
            "purchase_date": "2024-12-18",
            "supplier_batch_number": "PP-2024-1218",
            "expiry_date": None,
            "created_at": "2024-12-18T00:00:00Z",
        },
        {
            "id": "inv-003",
            "name": "Chemical A",
            "quantity": "450",
            "unit": "L",
            "inventory_type": "raw_material",
            "supplier": "ChemSupply Co.",
            "purchase_date": "2024-12-20",
            "supplier_batch_number": "CA-2024-1220",
            "expiry_date": "2025-06-20",
            "created_at": "2024-12-20T00:00:00Z",
        },
        {
            "id": "inv-004",
            "name": "Chemical B",
            "quantity": "280",
            "unit": "L",
            "inventory_type": "raw_material",
            "supplier": "ChemSupply Co.",
            "purchase_date": "2024-12-20",
            "supplier_batch_number": "CB-2024-1220",
            "expiry_date": "2025-06-20",
            "created_at": "2024-12-20T00:00:00Z",
        },
        {
            "id": "inv-005",
            "name": "Screws (M3)",
            "quantity": "50000",
            "unit": "pcs",
            "inventory_type": "raw_material",
            "supplier": "FastenerPro",
            "purchase_date": "2024-12-10",
            "supplier_batch_number": "SC-2024-1210",
            "expiry_date": None,
            "created_at": "2024-12-10T00:00:00Z",
        },
    ],
    "work_in_progress": [
        {
            "id": "inv-006",
            "name": "Aluminum Parts",
            "quantity": "850",
            "unit": "pcs",
            "inventory_type": "work_in_progress",
            "supplier": None,
            "purchase_date": None,
            "supplier_batch_number": None,
            "expiry_date": None,
            "source_step_name": "Component Fabrication",
            "created_at": "2024-12-27T00:00:00Z",
        },
        {
            "id": "inv-007",
            "name": "Plastic Housings",
            "quantity": "920",
            "unit": "pcs",
            "inventory_type": "work_in_progress",
            "supplier": None,
            "purchase_date": None,
            "supplier_batch_number": None,
            "expiry_date": None,
            "source_step_name": "Component Fabrication",
            "created_at": "2024-12-27T00:00:00Z",
        },
        {
            "id": "inv-008",
            "name": "Reacted Compound",
            "quantity": "156",
            "unit": "L",
            "inventory_type": "work_in_progress",
            "supplier": None,
            "purchase_date": None,
            "supplier_batch_number": None,
            "expiry_date": None,
            "source_step_name": "Reaction Phase",
            "created_at": "2024-12-28T00:00:00Z",
        },
    ],
    "final_product": [
        {
            "id": "inv-009",
            "name": "Approved Widgets",
            "quantity": "4250",
            "unit": "units",
            "inventory_type": "final_product",
            "supplier": None,
            "purchase_date": None,
            "supplier_batch_number": None,
            "expiry_date": None,
            "source_step_name": "Quality Control",
            "created_at": "2024-12-28T00:00:00Z",
        },
        {
            "id": "inv-010",
            "name": "Packaged Bulk Orders",
            "quantity": "89",
            "unit": "boxes",
            "inventory_type": "final_product",
            "supplier": None,
            "purchase_date": None,
            "supplier_batch_number": None,
            "expiry_date": None,
            "source_step_name": "Product Sorting",
            "created_at": "2024-12-28T00:00:00Z",
        },
    ],
}


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
    """Get mock inventory items, optionally filtered by type"""
    all_items = []
    all_items.extend(MOCK_INVENTORY["raw_material"])
    all_items.extend(MOCK_INVENTORY["work_in_progress"])
    all_items.extend(MOCK_INVENTORY["final_product"])

    if inventory_type:
        type_key = inventory_type
        if type_key in MOCK_INVENTORY:
            all_items = MOCK_INVENTORY[type_key].copy()

    return all_items


def get_mock_metrics():
    """Get mock metrics"""
    total_processes = len(MOCK_PROCESSES)
    active_executions = sum(1 for e in MOCK_EXECUTIONS if e["status"] == "in_progress")
    completed_executions = sum(1 for e in MOCK_EXECUTIONS if e["status"] == "completed")

    raw_materials = len(MOCK_INVENTORY["raw_material"])
    wip = len(MOCK_INVENTORY["work_in_progress"])
    final_products = len(MOCK_INVENTORY["final_product"])
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
