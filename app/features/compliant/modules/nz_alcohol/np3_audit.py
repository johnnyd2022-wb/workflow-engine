"""The verifier-confirmed NP3 audit view.

The topic list comes from the organisation's verification-confirmation email.  It is a
planning aid, not a substitute for the National Programme guidance or verifier judgement.
"""

from __future__ import annotations

from datetime import date
from typing import Any

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
            ("premises-services", "Premises, facilities, essential services and water supply"),
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


def build_np3_audit_rows(records: list[Any]) -> list[dict[str, Any]]:
    """Join the email's audit topics to the organisation's evidence ledger."""
    today = date.today()
    rows: list[dict[str, Any]] = []
    for category, topics in NP3_AUDIT_CATEGORIES:
        for control_id, topic in topics:
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
            state = "ready" if current else "attention" if failed else "missing"
            rows.append(
                {
                    "category": category,
                    "control_id": control_id,
                    "topic": topic,
                    "state": state,
                    "evidence_count": len(current),
                    "evidence_titles": [record.title for record in current],
                    "evidence_references": [
                        record.evidence_reference for record in current if record.evidence_reference
                    ],
                    "latest_recorded_at": max((record.created_at for record in current), default=None),
                }
            )
    return rows
