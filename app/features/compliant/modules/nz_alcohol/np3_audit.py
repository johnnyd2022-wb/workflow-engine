"""The verifier-confirmed NP3 audit view.

The topic list comes from the organisation's verification-confirmation email.  It is a
planning aid, not a substitute for the National Programme guidance or verifier judgement.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.features.compliant.modules.nz_alcohol.catalogue import control_reference, framework_by_slug

NP3_GUIDANCE_VERSION = "2025-v2"
NP3_GUIDANCE_URL = "https://www.mpi.govt.nz/dmsdocument/21853/direct"


def _playbook(section: str, page: int, proof: tuple[str, ...], fields: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    """A compact, check-specific evidence plan derived from the named MPI card.

    The product deliberately paraphrases the action to take; the official card remains
    one click away and is the source of truth for a verifier.
    """
    return {
        "section": section,
        "page": page,
        "guidance_url": f"{NP3_GUIDANCE_URL}#page={page}",
        "proof": list(proof),
        "fields": [{"key": key, "label": label} for key, label in fields],
    }


# Each audit check has a useful starting point instead of a one-size-fits-all note.
# Page numbers refer to the printed December 2025 NP3 guidance card pages.
NP3_EVIDENCE_PLAYBOOKS = {
    "registration-scope": _playbook(
        "Overview of getting started",
        12,
        ("Current registration and scope of operations", "Verifier confirmation and renewal/change correspondence"),
        (
            ("registration_reference", "Registration or scope-of-operations reference"),
            ("last_scope_review", "Date the scope and activities were last checked"),
        ),
    ),
    "corrective-actions": _playbook(
        "Taking action when something goes wrong",
        67,
        ("Incident or complaint log", "Containment, cause, corrective action and close-out evidence"),
        (
            ("incident_reference", "Incident or corrective-action reference"),
            ("close_out_date", "Date the action was verified closed"),
        ),
    ),
    "trace-and-recall": _playbook(
        "Sourcing, receiving and tracing food; Recalling food",
        35,
        (
            "Trace from a finished batch to inputs and customers",
            "Mock recall result, including time taken and improvement actions",
        ),
        (
            ("mock_recall_date", "Date of the latest mock recall"),
            ("trace_result", "Batch/lot traced and recall outcome"),
        ),
    ),
    "documentation-record-keeping": _playbook(
        "Checking the programme is working well",
        19,
        ("Current NP3 guidance accessible to staff", "Record index showing where required logs are held and retained"),
        (
            ("record_register_location", "Location of the record register"),
            ("retention_check_date", "Date retention and accessibility were checked"),
        ),
    ),
    "staff-competency": _playbook(
        "Ensuring staff are trained and competent",
        26,
        (
            "Training matrix covering managers, staff and relevant visitors",
            "Per-person training dates and evidence that practice has been observed",
        ),
        (
            ("training_register_reference", "Training register or matrix reference"),
            ("last_training_review", "Date staff training was last reviewed"),
            ("competency_observation", "How competence in practice was checked"),
        ),
    ),
    "delegation": _playbook(
        "Taking responsibility",
        12,
        (
            "Named people with food-safety responsibilities",
            "Delegation record showing authority, training and cover arrangements",
        ),
        (
            ("responsible_person", "Person responsible for this duty"),
            ("delegation_reference", "Delegation or responsibility record reference"),
        ),
    ),
    "operator-verification": _playbook(
        "Checking the programme is working well",
        19,
        ("Latest verifier report", "Completed responses to every verifier finding"),
        (
            ("verifier_report_reference", "Latest verifier report reference"),
            ("follow_up_status", "Status of verifier follow-up actions"),
        ),
    ),
    "personal-hygiene": _playbook(
        "Managing personal hygiene and health",
        32,
        ("Hygiene rules and suitable handwashing facilities", "Observed practice or supervisor check"),
        (
            ("hygiene_procedure", "Hygiene procedure or induction reference"),
            ("observation_date", "Date hygiene practice was last observed"),
        ),
    ),
    "health-and-sickness": _playbook(
        "Managing personal hygiene and health",
        32,
        (
            "Illness reporting and exclusion process",
            "Confidential absence/exclusion decision where food safety was affected",
        ),
        (
            ("illness_procedure", "Illness and exclusion procedure reference"),
            ("last_health_review", "Date this process was last reviewed"),
        ),
    ),
    "food-standards-composition": _playbook(
        "Allergens and knowing what is in your food",
        40,
        ("Current ingredient specifications and recipe/formula version", "Product-composition or standards review"),
        (
            ("product_or_recipe", "Product, recipe or formula reviewed"),
            ("standards_review_reference", "Composition/standards review reference"),
        ),
    ),
    "food-standards-microbiological": _playbook(
        "Preventing contamination of your food",
        43,
        ("Hazard assessment for the process", "Relevant sampling, test result or control verification"),
        (
            ("hazard_assessment", "Microbiological hazard assessment reference"),
            ("verification_result", "Latest test or verification result"),
        ),
    ),
    "time-temperature-processing": _playbook(
        "Thoroughly cooking or pasteurising food",
        46,
        ("Critical time/temperature limits for the process", "Batch logs and action taken for any deviation"),
        (
            ("process_step", "Process or product covered"),
            ("critical_limit", "Critical time/temperature limit"),
            ("log_reference", "Batch or temperature-log reference"),
        ),
    ),
    "cross-contamination": _playbook(
        "Preventing contamination of your food",
        43,
        ("Separation, scheduling or zoning controls", "Cleaning/changeover verification"),
        (
            ("control_method", "Separation or changeover control used"),
            ("verification_reference", "Verification or observation reference"),
        ),
    ),
    "equipment-design": _playbook(
        "Managing places and equipment",
        59,
        ("Food-contact equipment suitability and condition", "Cleaning, maintenance or replacement evidence"),
        (
            ("equipment_or_area", "Equipment or area reviewed"),
            ("suitability_check", "Suitability/condition check reference"),
        ),
    ),
    "suppliers-and-purchasing": _playbook(
        "Sourcing, receiving and tracing food",
        35,
        ("Approved supplier list and specifications", "Supplier approval or review evidence"),
        (("supplier_name", "Supplier reviewed"), ("approval_reference", "Supplier approval/specification reference")),
    ),
    "receiving-food": _playbook(
        "Sourcing, receiving and tracing food",
        35,
        (
            "Receiving checks for condition, temperature and identification",
            "Rejected or held delivery record where applicable",
        ),
        (
            ("receiving_log", "Receiving-check log reference"),
            ("last_delivery_check", "Date of the latest receiving check"),
        ),
    ),
    "allergen-management": _playbook(
        "Allergens and knowing what is in your food",
        40,
        ("Allergen/ingredient matrix and current label review", "Segregation, changeover or verification records"),
        (
            ("allergen_matrix", "Allergen matrix or ingredient review reference"),
            ("label_check", "Label/changeover verification reference"),
        ),
    ),
    "cooking-poultry": _playbook(
        "Thoroughly cooking or pasteurising food",
        46,
        ("Validated cooking limit for poultry", "Per-batch temperature/time record"),
        (("critical_limit", "Validated poultry cooking limit"), ("batch_log", "Latest poultry batch-log reference")),
    ),
    "defrosting-reheating": _playbook(
        "Defrosting and reheating food safely",
        48,
        ("Approved defrost/reheat method and limits", "Batch or temperature record"),
        (("method", "Defrosting/reheating method"), ("log_reference", "Latest process-log reference")),
    ),
    "storage-stock-rotation": _playbook(
        "Safe storage and display",
        37,
        ("Storage limits and stock-rotation method", "Storage check or stock-rotation record"),
        (("storage_area", "Storage area reviewed"), ("check_reference", "Storage/rotation check reference")),
    ),
    "cooling-freezing": _playbook(
        "Safe storage and display",
        37,
        ("Cooling/freezing limits for applicable food", "Batch cooling/freezing log and deviation action"),
        (("critical_limit", "Cooling/freezing limit"), ("log_reference", "Latest cooling/freezing log reference")),
    ),
    "display-temperature": _playbook(
        "Safe storage and display",
        37,
        ("Display temperature limits and checking frequency", "Display log and action when out of limit"),
        (("display_area", "Display area reviewed"), ("log_reference", "Latest display-temperature log reference")),
    ),
    "calibration": _playbook(
        "Checking measuring equipment",
        57,
        (
            "Register of food-safety measuring devices",
            "Calibration/check result and action for an out-of-tolerance device",
        ),
        (
            ("device_id", "Device ID or description"),
            ("calibration_reference", "Calibration/check record reference"),
            ("next_due_date", "Next calibration or check due date"),
        ),
    ),
    "transporting-food": _playbook(
        "Transporting food",
        66,
        ("Transport hygiene and temperature controls", "Dispatch/load check or carrier assurance"),
        (("transport_method", "Transport method or carrier"), ("dispatch_check", "Dispatch/transport check reference")),
    ),
    "food-labelling-advertising": _playbook(
        "Packaging and labelling your food",
        61,
        (
            "Approved current label/artwork and version",
            "Label review covering ingredients, allergens, lot/date and claims",
        ),
        (
            ("label_or_artwork", "Label/artwork version reviewed"),
            ("approval_reference", "Label approval or review reference"),
        ),
    ),
    "biological-hazards": _playbook(
        "Preventing contamination of your food",
        43,
        ("Process hazard assessment", "Control monitoring or verification result"),
        (("hazard", "Biological hazard considered"), ("control_verification", "Control or verification reference")),
    ),
    "chemical-hazards": _playbook(
        "Preventing contamination of your food",
        43,
        ("Chemical/cleaner/allergen hazard assessment", "Storage, use or residue control verification"),
        (("hazard", "Chemical hazard considered"), ("control_verification", "Control or verification reference")),
    ),
    "physical-hazards": _playbook(
        "Keeping foreign matter out of food",
        57,
        ("Foreign-matter risk assessment", "Inspection, maintenance or detection-control evidence"),
        (("hazard", "Physical hazard considered"), ("control_verification", "Control or inspection reference")),
    ),
    "importing-food": _playbook(
        "Sourcing, receiving and tracing food",
        35,
        (
            "Importer registration and supplier/consignment documents",
            "Relevant food-safety clearance or import controls",
        ),
        (
            ("import_reference", "Importer or consignment reference"),
            ("clearance_reference", "Clearance or supplier-assurance reference"),
        ),
    ),
    "cleaning-and-hygiene": _playbook(
        "Cleaning and sanitising",
        27,
        (
            "Cleaning schedule by area/equipment",
            "Completed checks and corrective action where cleaning was ineffective",
        ),
        (
            ("cleaning_schedule", "Cleaning schedule reference"),
            ("area_or_equipment", "Area/equipment checked"),
            ("verification_date", "Date cleaning effectiveness was checked"),
        ),
    ),
    "pest-animal-control": _playbook(
        "Controlling pests",
        29,
        ("Pest monitoring/service records", "Finding, treatment and close-out evidence"),
        (
            ("pest_control_reference", "Pest service or inspection reference"),
            ("last_inspection", "Date of last inspection"),
        ),
    ),
    "waste-management": _playbook(
        "Managing places and equipment",
        59,
        ("Waste handling and disposal controls", "Cleaning or contractor record that shows the controls operate"),
        (
            ("waste_control", "Waste handling/disposal method"),
            ("check_reference", "Waste-area inspection or service reference"),
        ),
    ),
    "premises-services": _playbook(
        "Managing places and equipment",
        59,
        ("Premises, facilities and essential-service suitability check", "Repair or maintenance action for a defect"),
        (
            ("area_or_service", "Premises area or essential service reviewed"),
            ("condition_check", "Condition/suitability check reference"),
        ),
    ),
    "water-supply": _playbook(
        "Ensuring your water is suitable",
        64,
        ("Water source and suitability assessment", "Relevant treatment, test or maintenance record"),
        (("water_source", "Water source reviewed"), ("water_assurance", "Test, treatment or assurance reference")),
    ),
    "maintenance": _playbook(
        "Maintaining equipment and facilities",
        30,
        ("Planned maintenance schedule", "Completed maintenance and food-safety release check"),
        (
            ("asset_or_area", "Asset or area maintained"),
            ("maintenance_reference", "Maintenance record/work-order reference"),
        ),
    ),
    "unsafe-unsuitable-food": _playbook(
        "Taking action when something goes wrong",
        67,
        (
            "Product isolation/disposition decision",
            "Investigation, verifier notification where needed, and prevention action",
        ),
        (
            ("affected_product", "Affected product or batch"),
            ("disposition", "Isolation, disposal, rework or recall decision"),
            ("incident_reference", "Incident/close-out reference"),
        ),
    ),
}


def evidence_playbook(control_id: str) -> dict[str, Any]:
    """Return an explicit fallback only for a new/unmapped future NP3 control."""
    return NP3_EVIDENCE_PLAYBOOKS.get(
        control_id,
        _playbook(
            "National Programme 3 Guidance",
            6,
            ("Explain the operating control and retain a reviewable supporting record.",),
            (("supporting_record", "Supporting record reference"),),
        ),
    )


NP3_AUDIT_CATEGORIES = (
    (
        "Confidence in management",
        (
            ("registration-scope", "Registration / scope of operations"),
            ("corrective-actions", "Improvements and corrective actions"),
            ("trace-and-recall", "Traceability, recall and complaints"),
            ("documentation-record-keeping", "Documentation and record keeping"),
            ("staff-competency", "Competency in management"),
            ("delegation", "Delegation"),
            ("operator-verification", "Operator verification"),
        ),
    ),
    (
        "Food safety behaviour",
        (
            ("staff-competency", "Staff competencies / training"),
            ("personal-hygiene", "Personal hygiene and behaviour"),
            ("health-and-sickness", "Health and sickness"),
            ("food-standards-composition", "Food standards: ingredients and composition"),
            ("food-standards-microbiological", "Food standards: microbiological"),
        ),
    ),
    (
        "Process control",
        (
            ("time-temperature-processing", "Time / temperature control (cooking / processing)"),
            ("cross-contamination", "Preventing cross contamination"),
            ("equipment-design", "Design and appropriate use of equipment"),
            ("suppliers-and-purchasing", "Suppliers and purchasing"),
            ("receiving-food", "Receiving food"),
            ("allergen-management", "Food allergen management"),
            ("cooking-poultry", "Cooking poultry"),
            ("defrosting-reheating", "Defrosting and reheating food"),
            ("storage-stock-rotation", "Storage and stock rotation"),
            ("cooling-freezing", "Cooling and freezing"),
            ("display-temperature", "Time / temperature controls for food on display"),
            ("calibration", "Calibration"),
            ("transporting-food", "Transporting food"),
            ("food-labelling-advertising", "Food labelling and advertising"),
            ("biological-hazards", "Process control for biological hazards"),
            ("chemical-hazards", "Process control for chemical hazards"),
            ("physical-hazards", "Process control for physical hazards"),
            ("importing-food", "Importing food"),
        ),
    ),
    (
        "Environmental control",
        (
            ("cleaning-and-hygiene", "Cleaning and sanitising"),
            ("pest-animal-control", "Pest and animal control"),
            ("waste-management", "Waste management"),
            ("premises-services", "Design and use of places, facilities and essential services"),
            ("water-supply", "Water supply"),
            ("maintenance", "Maintenance"),
        ),
    ),
    (
        "Compliance history",
        (
            ("trace-and-recall", "Complaints and recalls"),
            ("corrective-actions", "Non-compliance"),
            ("unsafe-unsuitable-food", "Managing unsafe / unsuitable food"),
        ),
    ),
)

PREPARATION_ITEMS = (
    "Current National Programme guidance and all relevant records and documentation.",
    "Suitable table or workspace, and access to relevant staff members.",
    "Retail label and advertising examples sent to the verifier before the visit, if used.",
    "Any site health-and-safety requirements or risks communicated before the visit.",
    "A translator arranged where needed.",
)


def build_np3_audit_rows(
    records: list[Any], derived_evidence: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Join NP3 topics to manual evidence and provenance-rich Core observations."""
    today = date.today()
    derived_evidence = derived_evidence or []
    controls = dict((framework_by_slug("np3-food-control") or {}).get("controls", ()))
    rows: list[dict[str, Any]] = []
    for category, topics in NP3_AUDIT_CATEGORIES:
        for control_id, topic in topics:
            playbook = evidence_playbook(control_id)
            matched = [record for record in records if record.control_id == control_id]
            current = [
                record
                for record in matched
                if record.status == "complete" and not (record.due_date and record.due_date < today)
            ]
            failed = [
                record
                for record in matched
                if record.status in {"open", "failed"} or (record.due_date and record.due_date < today)
            ]
            derived = [item for item in derived_evidence if item.get("control_id") == control_id]
            attestations = [
                record
                for record in matched
                if getattr(record, "record_type", None) == "attestation"
                and (getattr(record, "details", None) or {}).get("np3_guidance_version")
            ]
            latest_attestation = max(attestations, key=lambda record: record.created_at, default=None)
            guidance_update_required = bool(
                latest_attestation
                and (latest_attestation.details or {}).get("np3_guidance_version") != NP3_GUIDANCE_VERSION
            )
            state = "ready" if current or derived else "attention" if failed else "missing"
            # A recorded failure remains an attention item even when another Core fact is
            # available: a trace cannot silently close an overdue corrective action.
            if failed:
                state = "attention"
            if guidance_update_required:
                state = "attention"
            rows.append(
                {
                    "category": category,
                    "control_id": control_id,
                    "source_reference": control_reference("np3-food-control", control_id),
                    "guidance_url": playbook["guidance_url"],
                    "guidance_version": NP3_GUIDANCE_VERSION,
                    "requirement_summary": controls.get(control_id, topic),
                    "evidence_playbook": playbook,
                    "topic": topic,
                    "state": state,
                    "guidance_update_required": guidance_update_required,
                    "evidence_count": len(current) + len(derived),
                    "manual_evidence_count": len(current),
                    "derived_evidence_count": len(derived),
                    "evidence_titles": [record.title for record in current] + [item["title"] for item in derived],
                    "evidence_references": [
                        record.evidence_reference for record in current if record.evidence_reference
                    ],
                    "latest_recorded_at": max((record.created_at for record in current), default=None),
                    "derived_evidence": derived,
                    "history": [
                        {
                            "title": record.title,
                            "record_type": getattr(record, "record_type", None),
                            "status": record.status,
                            "created_at": record.created_at,
                            "created_by_user_id": getattr(record, "created_by_user_id", None),
                            "due_date": record.due_date,
                            "how_we_meet": (getattr(record, "details", None) or {}).get("how_we_meet"),
                            "evidence_fields": (getattr(record, "details", None) or {}).get("evidence_fields", {}),
                            "guidance_version": (getattr(record, "details", None) or {}).get("np3_guidance_version"),
                        }
                        for record in sorted(matched, key=lambda record: record.created_at, reverse=True)
                    ],
                }
            )
    return rows
