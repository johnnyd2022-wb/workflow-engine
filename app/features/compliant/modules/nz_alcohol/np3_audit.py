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
                    "guidance_url": NP3_GUIDANCE_URL,
                    "guidance_version": NP3_GUIDANCE_VERSION,
                    "requirement_summary": controls.get(control_id, topic),
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
                            "guidance_version": (getattr(record, "details", None) or {}).get("np3_guidance_version"),
                        }
                        for record in sorted(matched, key=lambda record: record.created_at, reverse=True)
                    ],
                }
            )
    return rows
