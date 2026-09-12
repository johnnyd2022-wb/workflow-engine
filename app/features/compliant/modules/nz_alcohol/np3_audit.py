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


def _field_guidance(key: str, label: str) -> tuple[str, str]:
    """Give each review field usable, visible instructions rather than a vague placeholder."""
    specific = {
        "training_register_reference": (
            "Identify the live register that lists every staff member, their required training and completed dates.",
            "Training / Staff competency matrix / 2026",
        ),
        "last_training_review": (
            "Record when the register was checked for every current worker, including new starters and changed roles.",
            "12 September 2026",
        ),
        "competency_observation": (
            "State how a supervisor confirmed people can follow the procedure in practice, not just that they attended training.",
            "Packaging lead observed the allergen changeover on 8 Sep",
        ),
        "mock_recall_date": (
            "Use the date of the latest trace or mock-recall exercise.",
            "4 August 2026",
        ),
        "trace_result": (
            "Record the batch traced, the result and how quickly the product could be located.",
            "Batch B2408 traced to supplier lots and three customers in 38 min",
        ),
    }
    if key in specific:
        return specific[key]
    if key.endswith("_date") or key.startswith("last_") or key.startswith("next_"):
        return ("Record the actual date for this review, check or activity.", "12 September 2026")
    if any(word in key for word in ("reference", "register", "log", "schedule", "report", "matrix")):
        return (
            "Name the exact record and where the verifier can open it; avoid a general description.",
            "Food safety / Current records / " + label,
        )
    if any(word in key for word in ("person", "supplier", "carrier", "source", "area", "equipment", "asset", "device")):
        return (
            "Identify the specific person, item or area reviewed for this sign-off.",
            "Name or ID used at this site",
        )
    return (
        "Record the specific result, method or decision that shows this check is operating.",
        "Brief factual result for this review",
    )


def _playbook(
    section: str,
    page: int,
    proof: tuple[str, ...],
    fields: tuple[tuple[str, str], ...],
    *,
    reference_notes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """A compact, check-specific evidence plan derived from the named MPI card.

    The product deliberately paraphrases the action to take; the official card remains
    one click away and is the source of truth for a verifier.
    """
    return {
        "section": section,
        "page": page,
        "guidance_url": f"{NP3_GUIDANCE_URL}#page={page}",
        "proof": list(proof),
        "reference_notes": list(reference_notes),
        "fields": [
            {
                "key": key,
                "label": label,
                "help": _field_guidance(key, label)[0],
                "example": _field_guidance(key, label)[1],
            }
            for key, label in fields
        ],
    }


def _log_template(
    key: str,
    title: str,
    description: str,
    record_type: str,
    fields: tuple[dict[str, Any], ...],
    *,
    roster_driven: bool = False,
) -> dict[str, Any]:
    """Describe an audit-ready operational register the product can maintain itself.

    These are deliberately control-specific.  A temperature check is not a staff-training
    record and an illness/exclusion decision should not ask for medical detail.
    """
    return {
        "key": key,
        "title": title,
        "description": description,
        "record_type": record_type,
        "roster_driven": roster_driven,
        "fields": list(fields),
    }


NP3_LOG_TEMPLATES: dict[str, dict[str, Any]] = {
    "staff-competency": _log_template(
        "staff_training",
        "Staff training and competency register",
        "One entry per person and competency review. The system shows active team members who still need an entry.",
        "competency",
        (
            {"key": "event_date", "label": "Training or review date", "type": "date", "required": True},
            {"key": "employee_user_id", "label": "Employee", "type": "user", "required": True},
            {"key": "training_topic", "label": "Training, procedure or task", "type": "text", "required": True},
            {
                "key": "competency_result",
                "label": "Competency confirmation",
                "type": "select",
                "required": True,
                "options": (
                    ("observed-competent", "Observed competent"),
                    ("refresher-needed", "Refresher or follow-up needed"),
                ),
            },
            {"key": "review_notes", "label": "Supervisor notes", "type": "textarea", "required": False},
        ),
        roster_driven=True,
    ),
    "health-and-sickness": _log_template(
        "health_exclusion",
        "Illness and exclusion register",
        "Record the food-safety decision and return-to-work review. Do not enter diagnosis or other unnecessary medical detail.",
        "incident",
        (
            {"key": "event_date", "label": "Report or review date", "type": "date", "required": True},
            {"key": "employee_user_id", "label": "Employee", "type": "user", "required": True},
            {
                "key": "food_safety_decision",
                "label": "Food-safety decision",
                "type": "select",
                "required": True,
                "options": (
                    ("cleared", "Cleared for food handling"),
                    ("restricted", "Restricted from affected work"),
                    ("excluded", "Excluded from food handling"),
                ),
            },
            {"key": "return_review_date", "label": "Return-to-work review date", "type": "date", "required": False},
            {"key": "manager_notes", "label": "Decision notes", "type": "textarea", "required": False},
        ),
    ),
    "cleaning-and-hygiene": _log_template(
        "cleaning_verification",
        "Cleaning and sanitising verification log",
        "Capture what was checked, whether it was effective, and the correction when it was not.",
        "reading",
        (
            {"key": "event_date", "label": "Check date", "type": "date", "required": True},
            {"key": "area_or_equipment", "label": "Area or equipment", "type": "text", "required": True},
            {"key": "method", "label": "Cleaning or verification method", "type": "text", "required": True},
            {
                "key": "result",
                "label": "Result",
                "type": "select",
                "required": True,
                "options": (("ok", "Effective"), ("action-required", "Action required")),
            },
            {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
        ),
    ),
    "receiving-food": _log_template(
        "receiving_check",
        "Food receiving log",
        "Capture identification, condition and the accept/hold/reject decision for the delivery checked.",
        "reading",
        (
            {"key": "event_date", "label": "Receiving date", "type": "date", "required": True},
            {
                "key": "supplier_or_delivery",
                "label": "Supplier and delivery reference",
                "type": "text",
                "required": True,
            },
            {"key": "food_or_batch", "label": "Food, batch or lot", "type": "text", "required": True},
            {
                "key": "condition_or_temperature",
                "label": "Condition or temperature checked",
                "type": "text",
                "required": True,
            },
            {
                "key": "decision",
                "label": "Decision",
                "type": "select",
                "required": True,
                "options": (("accepted", "Accepted"), ("held", "Held"), ("rejected", "Rejected")),
            },
        ),
    ),
    "time-temperature-processing": _log_template(
        "process_temperature",
        "Process time and temperature log",
        "Record the batch, the observed critical limit and the action when a limit is not met.",
        "reading",
        (
            {"key": "event_date", "label": "Process date", "type": "date", "required": True},
            {"key": "batch_or_product", "label": "Batch or product", "type": "text", "required": True},
            {"key": "observed_limit", "label": "Observed time / temperature", "type": "text", "required": True},
            {
                "key": "result",
                "label": "Limit met",
                "type": "select",
                "required": True,
                "options": (("ok", "Yes"), ("action-required", "No — action required")),
            },
            {"key": "corrective_action", "label": "Action for any deviation", "type": "textarea", "required": False},
        ),
    ),
    "cooling-freezing": _log_template(
        "cooling_freezing",
        "Cooling and freezing log",
        "Record applicable batch cooling/freezing checks and any action taken for a deviation.",
        "reading",
        (
            {"key": "event_date", "label": "Check date", "type": "date", "required": True},
            {"key": "batch_or_product", "label": "Batch or product", "type": "text", "required": True},
            {"key": "observed_limit", "label": "Observed time / temperature", "type": "text", "required": True},
            {
                "key": "result",
                "label": "Limit met",
                "type": "select",
                "required": True,
                "options": (("ok", "Yes"), ("action-required", "No — action required")),
            },
            {"key": "corrective_action", "label": "Action for any deviation", "type": "textarea", "required": False},
        ),
    ),
    "display-temperature": _log_template(
        "display_temperature",
        "Display temperature log",
        "Record each display area checked and what happened if it was outside its limit.",
        "reading",
        (
            {"key": "event_date", "label": "Check date", "type": "date", "required": True},
            {"key": "display_area", "label": "Display area", "type": "text", "required": True},
            {"key": "observed_temperature", "label": "Observed temperature", "type": "text", "required": True},
            {
                "key": "result",
                "label": "Within limit",
                "type": "select",
                "required": True,
                "options": (("ok", "Yes"), ("action-required", "No — action required")),
            },
            {"key": "corrective_action", "label": "Action for any deviation", "type": "textarea", "required": False},
        ),
    ),
    "calibration": _log_template(
        "calibration_check",
        "Measuring equipment calibration register",
        "Record the device, comparison/check result and follow-up for an out-of-tolerance result.",
        "reading",
        (
            {"key": "event_date", "label": "Calibration or check date", "type": "date", "required": True},
            {"key": "device", "label": "Device ID or description", "type": "text", "required": True},
            {"key": "check_result", "label": "Calibration/check result", "type": "text", "required": True},
            {
                "key": "result",
                "label": "Within tolerance",
                "type": "select",
                "required": True,
                "options": (("ok", "Yes"), ("action-required", "No — action required")),
            },
            {"key": "corrective_action", "label": "Action for any deviation", "type": "textarea", "required": False},
        ),
    ),
    "pest-animal-control": _log_template(
        "pest_inspection",
        "Pest inspection and treatment log",
        "Record inspections, findings, treatment and close-out rather than relying on an unstructured contractor note.",
        "incident",
        (
            {"key": "event_date", "label": "Inspection date", "type": "date", "required": True},
            {"key": "area", "label": "Area checked", "type": "text", "required": True},
            {"key": "finding", "label": "Finding or service completed", "type": "textarea", "required": True},
            {
                "key": "result",
                "label": "Follow-up needed",
                "type": "select",
                "required": True,
                "options": (("ok", "No"), ("action-required", "Yes — action required")),
            },
            {"key": "corrective_action", "label": "Treatment or follow-up", "type": "textarea", "required": False},
        ),
    ),
    "corrective-actions": _log_template(
        "corrective_action",
        "Corrective action register",
        "Record containment, cause, corrective action and verification rather than only the incident title.",
        "incident",
        (
            {"key": "event_date", "label": "Incident date", "type": "date", "required": True},
            {"key": "issue", "label": "What happened", "type": "textarea", "required": True},
            {"key": "containment", "label": "Immediate containment", "type": "textarea", "required": True},
            {"key": "cause_and_action", "label": "Cause and corrective action", "type": "textarea", "required": True},
            {
                "key": "result",
                "label": "Action status",
                "type": "select",
                "required": True,
                "options": (("ok", "Verified closed"), ("action-required", "Still open")),
            },
        ),
    ),
    "trace-and-recall": _log_template(
        "mock_recall",
        "Mock recall and trace exercise log",
        "Capture the batch, trace result, elapsed time and improvement action from each exercise.",
        "incident",
        (
            {"key": "event_date", "label": "Exercise date", "type": "date", "required": True},
            {"key": "batch_or_product", "label": "Batch or product traced", "type": "text", "required": True},
            {"key": "trace_result", "label": "Trace and recall result", "type": "textarea", "required": True},
            {"key": "elapsed_time", "label": "Elapsed time", "type": "text", "required": True},
            {"key": "improvement_action", "label": "Improvement action", "type": "textarea", "required": False},
        ),
    ),
    "water-supply": _log_template(
        "water_check",
        "Water suitability register",
        "For self-supply, record the accredited-lab test before first use and after a severe-weather/adverse-event restart. For a registered supply, record the current supplier check.",
        "reading",
        (
            {"key": "event_date", "label": "Test or check date", "type": "date", "required": True},
            {
                "key": "source_type",
                "label": "Source type",
                "type": "select",
                "required": True,
                "options": (
                    ("self-supply", "Self-supply: bore, roof or aquifer"),
                    ("registered-supplier", "Registered drinking-water supplier"),
                ),
            },
            {
                "key": "test_or_check",
                "label": "Accredited-lab test or supplier check",
                "type": "text",
                "required": True,
            },
            {
                "key": "result",
                "label": "Result",
                "type": "select",
                "required": True,
                "options": (("ok", "Meets criteria"), ("action-required", "Action required")),
            },
            {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
        ),
    ),
    "maintenance": _log_template(
        "maintenance_check",
        "Maintenance register",
        "One entry per service or check. If maintenance chemicals are used, confirm they are labelled, sealed and cannot be mistaken for food containers.",
        "reading",
        (
            {"key": "event_date", "label": "Date", "type": "date", "required": True},
            {"key": "asset_or_area", "label": "Asset, equipment or area", "type": "text", "required": True},
            {"key": "task_performed", "label": "Task performed or check made", "type": "text", "required": True},
            {
                "key": "maintenance_chemicals_checked",
                "label": "Maintenance chemicals handled safely (if used)",
                "type": "select",
                "required": False,
                "options": (
                    ("ok", "Confirmed"),
                    ("not-applicable", "No chemicals used"),
                    ("action-required", "Action required"),
                ),
            },
            {
                "key": "result",
                "label": "Result",
                "type": "select",
                "required": True,
                "options": (("ok", "Suitable / working properly"), ("action-required", "Action required")),
            },
            {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
        ),
    ),
    "food-labelling-advertising": _log_template(
        "packaging_handling",
        "Packaging handling verification",
        "Spot-check that empty packaging and filled containers are handled to prevent contamination. The listed practices are site-specific applications of NP3's packaging-care requirement.",
        "reading",
        (
            {"key": "event_date", "label": "Check date", "type": "date", "required": True},
            {
                "key": "checked_practice",
                "label": "Practice checked",
                "type": "select",
                "required": True,
                "options": (
                    ("bottles-boxed-until-filling", "Bottles kept boxed/sealed until filling"),
                    ("corked-immediately", "Corked/capped immediately after filling"),
                    ("packaging-storage", "Packaging stored away from contamination risk"),
                ),
            },
            {
                "key": "result",
                "label": "Result",
                "type": "select",
                "required": True,
                "options": (("ok", "Confirmed"), ("action-required", "Action required")),
            },
            {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
        ),
    ),
    "water-activity-control": _log_template(
        "water_activity",
        "Water-activity control register",
        "For dried or concentrated food, capture the per-batch method and water-activity result. This is only applicable where this preservation method is used.",
        "reading",
        (
            {"key": "event_date", "label": "Batch or test date", "type": "date", "required": True},
            {"key": "batch_or_product", "label": "Batch or product", "type": "text", "required": True},
            {"key": "method", "label": "Drying/concentrating method or test method", "type": "text", "required": True},
            {"key": "test_result", "label": "Water-activity result", "type": "text", "required": True},
            {
                "key": "result",
                "label": "Result",
                "type": "select",
                "required": True,
                "options": (("ok", "Within the validated limit"), ("action-required", "Action required")),
            },
            {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
        ),
    ),
    "acidification-fermentation-control": _log_template(
        "acidification_fermentation",
        "Acidification and fermentation control register",
        "Use for pickled, fermented or acidified food. If the method is not used in this product line, use the tailored review sign-off to record that decision instead.",
        "reading",
        (
            {"key": "event_date", "label": "Batch or test date", "type": "date", "required": True},
            {"key": "batch_or_product", "label": "Batch or product", "type": "text", "required": True},
            {"key": "method", "label": "Acidification or fermentation method", "type": "text", "required": True},
            {"key": "test_result", "label": "pH result and test method", "type": "text", "required": True},
            {
                "key": "result",
                "label": "Result",
                "type": "select",
                "required": True,
                "options": (("ok", "Within the validated limit"), ("action-required", "Action required")),
            },
            {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
        ),
    ),
    "unsafe-unsuitable-food": _log_template(
        "unsafe_food_incident",
        "Unsafe or unsuitable food and recall register",
        "Record the hold/disposition decision. If a self-initiated recall is needed, use the guidance drawer for the NZFS reporting and communication sequence.",
        "incident",
        (
            {"key": "event_date", "label": "Incident date", "type": "date", "required": True},
            {"key": "affected_product", "label": "Affected product or batch", "type": "text", "required": True},
            {"key": "containment", "label": "Immediate hold or containment", "type": "textarea", "required": True},
            {
                "key": "disposition",
                "label": "Disposition decision",
                "type": "select",
                "required": True,
                "options": (
                    ("isolated", "Isolated / held"),
                    ("disposed", "Disposed"),
                    ("reworked", "Reworked"),
                    ("recall", "Recall initiated"),
                ),
            },
            {
                "key": "recall_level",
                "label": "Recall level (if a recall was initiated)",
                "type": "select",
                "required": False,
                "options": (("not-applicable", "No recall"), ("trade", "Trade level"), ("consumer", "Consumer level")),
            },
            {
                "key": "result",
                "label": "Follow-up status",
                "type": "select",
                "required": True,
                "options": (("ok", "Verified closed"), ("action-required", "Follow-up still open")),
            },
            {
                "key": "corrective_action",
                "label": "Investigation, notification or prevention action",
                "type": "textarea",
                "required": False,
            },
        ),
    ),
}


# A Core connection says where an operator should work once, not where they should copy
# the same fact into another register.  These are intentionally only surfaced where Core
# already owns a useful operational concept; the tailored NP3 log captures the small
# food-safety judgement that Core cannot truthfully infer.
NP3_CORE_CONNECTIONS: dict[str, tuple[dict[str, str], ...]] = {
    "trace-and-recall": (
        {
            "title": "Source Map traceability",
            "detail": "Use the product-to-input trace in Core for live lineage. The mock-recall register records the exercise result and elapsed time once.",
            "workspace_url": "/core/sourcemap?show=check-needed",
            "workspace_label": "Open Source Map trace",
        },
    ),
    "documentation-record-keeping": (
        {
            "title": "Core execution records",
            "detail": "Completed step data and active evidence files remain in Core; the NP3 review only confirms that the record set is accessible and retained.",
            "workspace_url": "/core/executions/live",
            "workspace_label": "Open execution evidence",
        },
    ),
    "suppliers-and-purchasing": (
        {
            "title": "Core inventory supplier data",
            "detail": "Supplier identity belongs on the raw-material record in Core. Review supplier approval here rather than creating a second stock register.",
            "workspace_url": "/core/inventory/view",
            "workspace_label": "Open inventory records",
        },
    ),
    "receiving-food": (
        {
            "title": "Core inventory receiving details",
            "detail": "Supplier, supplier batch and purchase date are reused from inventory. The receiving log adds only the condition/temperature and accept, hold or reject decision.",
            "workspace_url": "/core/inventory/add/manual",
            "workspace_label": "Add or review inventory",
        },
    ),
    "staff-competency": (
        {
            "title": "Organisation people roster",
            "detail": "Every active Core user appears in the competency work queue until a per-person record is added. New starters are detected automatically.",
            "workspace_url": "/org/users",
            "workspace_label": "Open organisation users",
        },
    ),
    "health-and-sickness": (
        {
            "title": "Organisation people roster",
            "detail": "Select the active team member once when recording a food-safety decision; keep unnecessary medical information out of the food-safety register.",
            "workspace_url": "/org/users",
            "workspace_label": "Open organisation users",
        },
    ),
    "time-temperature-processing": (
        {
            "title": "Core workflow evidence",
            "detail": "When NP3 workflow evidence is enabled, Core execution steps prompt for the operational evidence. The log records the critical result and deviation decision.",
            "workspace_url": "/core/executions/live",
            "workspace_label": "Open live executions",
        },
    ),
    "cooling-freezing": (
        {
            "title": "Core workflow evidence",
            "detail": "Use the execution record for the batch workflow; retain the cooling/freezing observation and any deviation only once in this check register.",
            "workspace_url": "/core/executions/live",
            "workspace_label": "Open live executions",
        },
    ),
    "display-temperature": (
        {
            "title": "Core tasks",
            "detail": "Use a recurring Core task to prompt the display check. This register retains the actual measured result and corrective action.",
            "workspace_url": "/core?tab=tasks",
            "workspace_label": "Open Core tasks",
        },
    ),
    "cleaning-and-hygiene": (
        {
            "title": "Core tasks",
            "detail": "Schedule cleaning verification in Core Tasks; record the inspection result and correction here, not in a duplicate task note.",
            "workspace_url": "/core?tab=tasks",
            "workspace_label": "Open Core tasks",
        },
    ),
    "calibration": (
        {
            "title": "Core tasks",
            "detail": "Use a recurring Core task for each calibration due date. This register holds the device result and any out-of-tolerance action.",
            "workspace_url": "/core?tab=tasks",
            "workspace_label": "Open Core tasks",
        },
    ),
    "pest-animal-control": (
        {
            "title": "Core tasks",
            "detail": "Schedule inspections or contractor visits in Core Tasks; record findings, treatment and close-out in this audit-ready log.",
            "workspace_url": "/core?tab=tasks",
            "workspace_label": "Open Core tasks",
        },
    ),
    "maintenance": (
        {
            "title": "Core tasks",
            "detail": "Plan maintenance in Core Tasks and retain the food-safety release decision with the check evidence.",
            "workspace_url": "/core?tab=tasks",
            "workspace_label": "Open Core tasks",
        },
    ),
    "water-supply": (
        {
            "title": "Core tasks",
            "detail": "Use Core Tasks to schedule the next supplier or self-supply review. The water register retains the test/check result and any corrective action.",
            "workspace_url": "/core?tab=tasks",
            "workspace_label": "Open Core tasks",
        },
    ),
    "food-labelling-advertising": (
        {
            "title": "Core workflow evidence",
            "detail": "Use the production workflow to retain the operational evidence; the packaging register records the contamination-prevention spot check once.",
            "workspace_url": "/core/executions/live",
            "workspace_label": "Open live executions",
        },
    ),
    "water-activity-control": (
        {
            "title": "Core workflow evidence",
            "detail": "Use the batch execution for the product context; this register retains the measured water-activity result once per applicable batch.",
            "workspace_url": "/core/executions/live",
            "workspace_label": "Open live executions",
        },
    ),
    "acidification-fermentation-control": (
        {
            "title": "Core workflow evidence",
            "detail": "Use the batch execution for the product context; this register retains the applicable pH result once per batch.",
            "workspace_url": "/core/executions/live",
            "workspace_label": "Open live executions",
        },
    ),
    "unsafe-unsuitable-food": (
        {
            "title": "Source Map traceability",
            "detail": "Use Source Map to identify the connected product, inputs and downstream movement. Keep the containment, disposition and recall decision in this register.",
            "workspace_url": "/core/sourcemap?show=check-needed",
            "workspace_label": "Open Source Map trace",
        },
    ),
    "corrective-actions": (
        {
            "title": "Core tasks",
            "detail": "Assign corrective work in Core Tasks, then keep the containment, cause and verification record here as the single audit trail.",
            "workspace_url": "/core?tab=tasks",
            "workspace_label": "Open Core tasks",
        },
    ),
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
        66,
        ("Incident or complaint log", "Containment, cause, corrective action and close-out evidence"),
        (
            ("incident_reference", "Incident or corrective-action reference"),
            ("close_out_date", "Date the action was verified closed"),
        ),
    ),
    "trace-and-recall": _playbook(
        "Sourcing, receiving and tracing food",
        37,
        (
            "Trace from a finished batch to inputs and customers",
            "Mock recall result, including time taken and improvement actions",
        ),
        (
            ("mock_recall_date", "Date of the latest mock recall"),
            ("trace_result", "Batch/lot traced and recall outcome"),
        ),
        reference_notes=(
            "For a self-initiated recall: investigate and hold affected food, inform your verifier or NZFS, assess, report the recall decision to NZFS within 24 hours, communicate, then audit the outcome.",
            "A mock recall is required at least every 12 months unless a real recall was carried out effectively in that period. Keep the risk assessment, recall notice and actions taken.",
        ),
    ),
    "documentation-record-keeping": _playbook(
        "Checking the programme is working well",
        15,
        ("Current NP3 guidance accessible to staff", "Record index showing where required logs are held and retained"),
        (
            ("record_register_location", "Location of the record register"),
            ("retention_check_date", "Date retention and accessibility were checked"),
        ),
    ),
    "staff-competency": _playbook(
        "Ensuring staff are trained and competent",
        25,
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
        15,
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
        43,
        ("Current ingredient specifications and recipe/formula version", "Product-composition or standards review"),
        (
            ("product_or_recipe", "Product, recipe or formula reviewed"),
            ("standards_review_reference", "Composition/standards review reference"),
        ),
    ),
    "food-standards-microbiological": _playbook(
        "Preventing contamination of your food",
        46,
        ("Hazard assessment for the process", "Relevant sampling, test result or control verification"),
        (
            ("hazard_assessment", "Microbiological hazard assessment reference"),
            ("verification_result", "Latest test or verification result"),
        ),
    ),
    "time-temperature-processing": _playbook(
        "Thoroughly cooking or pasteurising food",
        48,
        ("Critical time/temperature limits for the process", "Batch logs and action taken for any deviation"),
        (
            ("process_step", "Process or product covered"),
            ("critical_limit", "Critical time/temperature limit"),
            ("log_reference", "Batch or temperature-log reference"),
        ),
    ),
    "cross-contamination": _playbook(
        "Preventing contamination of your food",
        46,
        ("Separation, scheduling or zoning controls", "Cleaning/changeover verification"),
        (
            ("control_method", "Separation or changeover control used"),
            ("verification_reference", "Verification or observation reference"),
        ),
    ),
    "equipment-design": _playbook(
        "Managing places and equipment",
        19,
        ("Food-contact equipment suitability and condition", "Cleaning, maintenance or replacement evidence"),
        (
            ("equipment_or_area", "Equipment or area reviewed"),
            ("suitability_check", "Suitability/condition check reference"),
        ),
    ),
    "suppliers-and-purchasing": _playbook(
        "Sourcing, receiving and tracing food",
        37,
        ("Approved supplier list and specifications", "Supplier approval or review evidence"),
        (("supplier_name", "Supplier reviewed"), ("approval_reference", "Supplier approval/specification reference")),
    ),
    "receiving-food": _playbook(
        "Sourcing, receiving and tracing food",
        37,
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
        43,
        ("Allergen/ingredient matrix and current label review", "Segregation, changeover or verification records"),
        (
            ("allergen_matrix", "Allergen matrix or ingredient review reference"),
            ("label_check", "Label/changeover verification reference"),
        ),
    ),
    "cooking-poultry": _playbook(
        "Thoroughly cooking or pasteurising food",
        48,
        ("Validated cooking limit for poultry", "Per-batch temperature/time record"),
        (("critical_limit", "Validated poultry cooking limit"), ("batch_log", "Latest poultry batch-log reference")),
    ),
    "defrosting-reheating": _playbook(
        "Defrosting and reheating food safely",
        53,
        ("Approved defrost/reheat method and limits", "Batch or temperature record"),
        (("method", "Defrosting/reheating method"), ("log_reference", "Latest process-log reference")),
    ),
    "storage-stock-rotation": _playbook(
        "Safe storage and display",
        40,
        ("Storage limits and stock-rotation method", "Storage check or stock-rotation record"),
        (("storage_area", "Storage area reviewed"), ("check_reference", "Storage/rotation check reference")),
    ),
    "cooling-freezing": _playbook(
        "Safe storage and display",
        40,
        ("Cooling/freezing limits for applicable food", "Batch cooling/freezing log and deviation action"),
        (("critical_limit", "Cooling/freezing limit"), ("log_reference", "Latest cooling/freezing log reference")),
    ),
    "display-temperature": _playbook(
        "Safe storage and display",
        40,
        ("Display temperature limits and checking frequency", "Display log and action when out of limit"),
        (("display_area", "Display area reviewed"), ("log_reference", "Latest display-temperature log reference")),
    ),
    "calibration": _playbook(
        "Managing places and equipment",
        19,
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
        64,
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
        46,
        ("Process hazard assessment", "Control monitoring or verification result"),
        (("hazard", "Biological hazard considered"), ("control_verification", "Control or verification reference")),
    ),
    "water-activity-control": _playbook(
        "Using water activity to control bugs",
        55,
        (
            "Per-batch drying or concentrating method",
            "Per-batch water-activity result from a calibrated meter, accredited laboratory or proven consistent method",
        ),
        (
            ("applicability", "Product or process to which water-activity control applies"),
            ("method", "Drying, concentrating or verification method"),
            ("result_reference", "Latest per-batch water-activity result reference"),
        ),
        reference_notes=(
            "The guidance uses water activity below 0.85 to prevent bug growth. A proven consistent method is only an option where its target water activity is below 0.80.",
        ),
    ),
    "acidification-fermentation-control": _playbook(
        "Pickling, fermenting, or acidifying food to keep them safe",
        57,
        (
            "Applicable acidification or fermentation method",
            "Per-batch pH test result using a calibrated meter or accredited laboratory, where this preservation method is used",
        ),
        (
            ("applicability", "Product line or explicit not-applicable decision"),
            ("method", "Acidification or fermentation method"),
            ("result_reference", "Latest pH test-result reference"),
        ),
        reference_notes=(
            "The guidance distinguishes pH below 3.6 from pH 3.6–4.6, where an additional pasteurising or cooking control is needed. Use the official card for the applicable method and limit.",
        ),
    ),
    "chemical-hazards": _playbook(
        "Preventing contamination of your food",
        46,
        ("Chemical/cleaner/allergen hazard assessment", "Storage, use or residue control verification"),
        (("hazard", "Chemical hazard considered"), ("control_verification", "Control or verification reference")),
    ),
    "physical-hazards": _playbook(
        "Keeping foreign matter out of food",
        59,
        ("Foreign-matter risk assessment", "Inspection, maintenance or detection-control evidence"),
        (("hazard", "Physical hazard considered"), ("control_verification", "Control or inspection reference")),
    ),
    "importing-food": _playbook(
        "Sourcing, receiving and tracing food",
        37,
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
        19,
        ("Waste handling and disposal controls", "Cleaning or contractor record that shows the controls operate"),
        (
            ("waste_control", "Waste handling/disposal method"),
            ("check_reference", "Waste-area inspection or service reference"),
        ),
    ),
    "premises-services": _playbook(
        "Managing places and equipment",
        19,
        ("Premises, facilities and essential-service suitability check", "Repair or maintenance action for a defect"),
        (
            ("area_or_service", "Premises area or essential service reviewed"),
            ("condition_check", "Condition/suitability check reference"),
        ),
    ),
    "water-supply": _playbook(
        "Ensuring your water is suitable",
        21,
        (
            "Water source and, for self-supply, accredited-lab test results",
            "Food-grade tank, container, pipe and treatment-system evidence",
        ),
        (
            ("water_source_type", "Registered supplier or self-supply source"),
            ("water_source", "Water source reviewed"),
            ("water_assurance", "Supplier registration or accredited-lab test reference"),
            ("storage_container_provenance", "Repurposed container and food-grade confirmation, if relevant"),
        ),
        reference_notes=(
            "Self-supply requires accredited-lab testing before a new source is used and within one week of restarting after severe weather or another adverse event that could affect the supply.",
            "For chlorinated self-supply, the guidance gives pH and chlorine criteria; use the official card and your verifier for the applicable testing plan. Keep self-supply test records.",
        ),
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
        66,
        (
            "Product isolation/disposition decision",
            "Investigation, verifier notification where needed, and prevention action",
        ),
        (
            ("affected_product", "Affected product or batch"),
            ("disposition", "Isolation, disposal, rework or recall decision"),
            ("incident_reference", "Incident/close-out reference"),
        ),
        reference_notes=(
            "For a self-initiated recall, report the recall decision to NZFS within 24 hours. Use the official recall card (page 68) for the current contact and communication process.",
            "Keep actions taken, the risk assessment and recall notice for the required retention period. A consumer-level recall includes consumer communication; a trade-level recall removes food from the supply chain.",
        ),
    ),
}


def evidence_playbook(control_id: str) -> dict[str, Any]:
    """Return an explicit fallback only for a new/unmapped future NP3 control."""
    playbook = NP3_EVIDENCE_PLAYBOOKS.get(
        control_id,
        _playbook(
            "National Programme 3 Guidance",
            6,
            ("Explain the operating control and retain a reviewable supporting record.",),
            (("supporting_record", "Supporting record reference"),),
        ),
    )
    # Copy the outer mapping so attaching the presentational log contract never mutates
    # the module catalogue shared by another tenant/request.
    return playbook | {
        "log_template": NP3_LOG_TEMPLATES.get(control_id),
        "core_connections": list(NP3_CORE_CONNECTIONS.get(control_id, ())),
    }


def np3_log_template(control_id: str) -> dict[str, Any] | None:
    """Return the built-in record schema for controls that genuinely need a register."""
    return NP3_LOG_TEMPLATES.get(control_id)


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
            ("water-activity-control", "Water activity for dried or concentrated food"),
            ("acidification-fermentation-control", "Pickling, fermenting or acidifying food"),
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


def _log_entry(record: Any) -> dict[str, Any]:
    details = getattr(record, "details", None) or {}
    return {
        "id": getattr(record, "id", None),
        "created_at": getattr(record, "created_at", None),
        "event_date": details.get("log_fields", {}).get("event_date"),
        "status": getattr(record, "status", None),
        "fields": details.get("log_fields", {}),
        "signed_off_by_user_id": getattr(record, "created_by_user_id", None),
    }


def build_np3_audit_rows(
    records: list[Any],
    derived_evidence: list[dict[str, Any]] | None = None,
    staff: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Join NP3 topics to manual evidence and provenance-rich Core observations."""
    today = date.today()
    derived_evidence = derived_evidence or []
    controls = dict((framework_by_slug("np3-food-control") or {}).get("controls", ()))
    rows: list[dict[str, Any]] = []
    for category_index, (category, topics) in enumerate(NP3_AUDIT_CATEGORIES):
        category_key = f"section-{category_index}"
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
            review_due_date = getattr(latest_attestation, "due_date", None)
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
            log_template = np3_log_template(control_id)
            log_entries = [
                _log_entry(record)
                for record in sorted(matched, key=lambda record: record.created_at, reverse=True)
                if (getattr(record, "details", None) or {}).get("np3_log_type") == (log_template or {}).get("key")
            ]
            staff_actions: list[dict[str, Any]] = []
            if log_template and log_template.get("roster_driven"):
                trained_user_ids = {
                    str(entry["fields"].get("employee_user_id"))
                    for entry in log_entries
                    if entry["fields"].get("employee_user_id") and entry["status"] == "complete"
                }
                staff_actions = [
                    {
                        "user_id": member["id"],
                        "name": member["name"],
                        "created_at": member.get("created_at"),
                        "reason": "No training and competency entry has been recorded for this active user.",
                    }
                    for member in (staff or [])
                    if str(member["id"]) not in trained_user_ids
                ]
            rows.append(
                {
                    "category": category,
                    "category_key": category_key,
                    "control_id": control_id,
                    "source_reference": control_reference("np3-food-control", control_id),
                    "guidance_url": playbook["guidance_url"],
                    "guidance_version": NP3_GUIDANCE_VERSION,
                    "requirement_summary": controls.get(control_id, topic),
                    "evidence_playbook": playbook,
                    "topic": topic,
                    "state": state,
                    "open_remediation": any(
                        getattr(record, "status", None) in {"open", "failed"} for record in matched
                    ),
                    "guidance_update_required": guidance_update_required,
                    "review_due_date": review_due_date,
                    "evidence_count": len(current) + len(derived),
                    "manual_evidence_count": len(current),
                    "derived_evidence_count": len(derived),
                    "evidence_titles": [record.title for record in current] + [item["title"] for item in derived],
                    "evidence_references": [
                        record.evidence_reference for record in current if record.evidence_reference
                    ],
                    "latest_recorded_at": max((record.created_at for record in current), default=None),
                    "derived_evidence": derived,
                    "log_template": log_template,
                    "log_entries": log_entries,
                    "staff_actions": staff_actions,
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
                            "log_entry": bool((getattr(record, "details", None) or {}).get("np3_log_type")),
                        }
                        for record in sorted(matched, key=lambda record: record.created_at, reverse=True)
                    ],
                }
            )
    return rows
