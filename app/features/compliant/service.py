"""Compliance evaluation and audit-pack assembly.

The service reads core data; it never changes inventory, executions, or CRM records.
Manual compliance records are append-only operational evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db.models.execution import Execution
from app.core.db.models.execution_evidence import EVIDENCE_STATUS_ACTIVE, ExecutionEvidence
from app.core.db.models.execution_step import ExecutionStep, ExecutionStepStatus
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_movement import InventoryMovement, InventoryMovementType
from app.core.db.models.step import Step
from app.core.db.models.user import User
from app.features.compliant.models import AlcoholProductProfile, ComplianceProfile, ComplianceRecord, ComplianceReport
from app.features.compliant.modules.nz_alcohol.catalogue import (
    NZ_ALCOHOL_FRAMEWORKS,
    capture_requirements,
    control_reference,
    framework_applies,
    framework_by_slug,
    framework_for_profile,
)
from app.features.compliant.modules.nz_alcohol.councils import TRADE_WASTE_CATALOGUES, council_catalogue
from app.features.compliant.modules.nz_alcohol.live_evidence import derive_np3_core_evidence
from app.features.compliant.modules.nz_alcohol.np3_audit import (
    NP3_AUDIT_CATEGORIES,
    PREPARATION_ITEMS,
    build_np3_audit_rows,
)
from app.features.crm.models.product_mapping import ProductMapping


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return [_iso(item) for item in value]
    if isinstance(value, dict):
        return {key: _iso(item) for key, item in value.items()}
    return value


def np3_audit_coverage(health: dict[str, Any]) -> dict[str, Any]:
    """Translate the NP3 register health into the Overview coverage contract.

    The generic framework catalogue is useful for configuration, but it cannot see
    tailored logs or evidence derived from Core. Overview must therefore use the
    same NP3 register result an operator sees after opening the NP3 workspace.
    """
    current_controls = int(health.get("ok") or 0)
    needs_attention = int(health.get("needs_attention") or 0)
    total_controls = current_controls + needs_attention
    return {
        "current_controls": current_controls,
        "total_controls": total_controls,
        "percent": round((current_controls / total_controls) * 100) if total_controls else 0,
        "label": "NP3 audit evidence status",
    }


def module_summary_health(coverage: dict[str, Any], *, overdue: int = 0) -> dict[str, int]:
    """Provide one comparable, operational health summary for every module card."""
    evidence_ready = int(coverage.get("current_controls") or 0)
    total_controls = int(coverage.get("total_controls") or 0)
    return {
        "score": int(coverage.get("percent") or 0),
        "current_controls": evidence_ready,
        "total_controls": total_controls,
        "evidence_ready": evidence_ready,
        "needs_attention": max(0, total_controls - evidence_ready),
        "overdue": overdue,
    }


def serialise_record(record: ComplianceRecord) -> dict[str, Any]:
    return _iso(
        {
            "id": record.id,
            "framework_slug": record.framework_slug,
            "control_id": record.control_id,
            "record_type": record.record_type,
            "status": record.status,
            "title": record.title,
            "period_start": record.period_start,
            "period_end": record.period_end,
            "due_date": record.due_date,
            "measured_value": record.measured_value,
            "limit_value": record.limit_value,
            "owner_user_id": record.owner_user_id,
            "evidence_reference": record.evidence_reference,
            "source_refs": record.source_refs or [],
            "details": record.details or {},
            "created_at": record.created_at,
        }
    )


def calculate_customs_reconciliation(profiles: dict[str, Any], movements: list[tuple[Any, str]]) -> dict[str, Any]:
    """Pure LAL calculation used by the live service and contract tests."""
    production_lal = Decimal("0")
    wastage_lal = Decimal("0")
    unprofiled = 0
    unsupported_unit = 0
    unprofiled_items: set[str] = set()
    unsupported_items: set[str] = set()
    for movement, item_name in movements:
        if movement.movement_type not in {
            InventoryMovementType.PRODUCTION.value,
            InventoryMovementType.WASTAGE.value,
        }:
            continue
        product = profiles.get(item_name)
        if product is None:
            unprofiled += 1
            unprofiled_items.add(item_name)
            continue
        quantity = Decimal(str(movement.quantity))
        unit = (movement.unit or "").lower()
        if unit == "ml":
            litres = quantity / Decimal("1000")
        elif unit == "l":
            litres = quantity
        else:
            unsupported_unit += 1
            unsupported_items.add(f"{item_name} ({movement.unit})")
            continue
        litres_of_alcohol = abs(litres) * Decimal(str(product.abv_percent)) / Decimal("100")
        if movement.movement_type == InventoryMovementType.PRODUCTION.value:
            production_lal += litres_of_alcohol
        else:
            wastage_lal += litres_of_alcohol
    return {
        "production_litres_of_alcohol": str(production_lal.quantize(Decimal("0.0001"))),
        "wastage_litres_of_alcohol": str(wastage_lal.quantize(Decimal("0.0001"))),
        "profiled_product_count": len(profiles),
        "unprofiled_movement_count": unprofiled,
        "unsupported_unit_movement_count": unsupported_unit,
        "unprofiled_inventory_names": sorted(unprofiled_items),
        "unsupported_inventory_units": sorted(unsupported_items),
    }


def build_priority_actions(
    profile: ComplianceProfile | None,
    frameworks: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    records: list[ComplianceRecord] | None = None,
) -> list[dict[str, Any]]:
    """Return the fewest high-value actions needed to improve evidence readiness.

    This is deliberately a work queue, not a synthetic compliance score: each item tells the
    operator the exact value unlocked and points to one small action in the product.
    """
    if profile is None or not profile.enabled:
        return [
            {
                "kind": "profile",
                "title": "Tell Compliant what you make",
                "description": "Choose your alcohol products to see only the frameworks that apply.",
                "value": "Unlock your personalised compliance plan in under a minute.",
            }
        ]

    actions: list[dict[str, Any]] = []
    if not (profile.settings or {}).get("alcohol_product_types"):
        actions.append(
            {
                "kind": "profile",
                "title": "Choose the alcohol products you make",
                "description": "This removes irrelevant requirements and keeps your plan specific to your operation.",
                "value": "Personalise the plan.",
            }
        )
    unmapped = reconciliation.get("unprofiled_inventory_names", [])
    if unmapped:
        actions.append(
            {
                "kind": "product",
                "title": f"Map {len(unmapped)} product{'s' if len(unmapped) != 1 else ''} already found in Core",
                "description": "Add ABV once and Compliant turns future production and wastage movements into live LAL evidence.",
                "value": "Unlock live Customs production evidence.",
                "suggestions": unmapped[:5],
            }
        )
    elif not reconciliation.get("profiled_product_count"):
        actions.append(
            {
                "kind": "product",
                "title": "Map your first alcohol product",
                "description": "Set its ABV and Compliant will start deriving LAL from Core movements.",
                "value": "Start the live Customs view.",
            }
        )

    # A due date is an operator-visible reminder, rather than a passive field buried
    # in a historic record. This makes recurring self-reviews reliably return to the
    # live work queue before they become overdue.
    today = date.today()
    due_soon = sorted(
        (
            record
            for record in (records or [])
            if record.status == "complete"
            and record.due_date
            and today <= record.due_date <= today + timedelta(days=30)
        ),
        key=lambda record: record.due_date,
    )
    for record in due_soon:
        actions.append(
            {
                "kind": "record",
                "state": "review",
                "title": f"Review due {record.due_date.isoformat()}: {record.title}",
                "description": "A scheduled evidence review is coming up. Confirm the proof is still accurate or add a replacement record.",
                "value": "Open the exact control and review its current proof.",
                "framework_slug": record.framework_slug,
                "control_id": record.control_id,
            }
        )

    controls = [
        (framework, control)
        for framework in frameworks
        for control in framework["controls"]
        if control["state"] in {"attention", "setup"}
        and control["control_id"] not in {"product-mapping", "reconciliation"}
    ]
    controls.sort(
        key=lambda item: (0 if item[1]["state"] == "attention" else 1, item[0]["name"], item[1]["control_id"])
    )
    for framework, control in controls:
        actions.append(
            {
                "kind": "record",
                "title": f"{framework['name']}: {control['control_id'].replace('-', ' ').title()}",
                "description": control["reason"],
                "value": control["description"],
                "framework_slug": framework["slug"],
                "control_id": control["control_id"],
                "capture": control.get("capture", {}),
                "state": control["state"],
            }
        )
    return actions[:6]


class ComplianceService:
    def __init__(self, session: Session):
        self.session = session

    def get_profile(self, org_id: UUID) -> ComplianceProfile | None:
        return self.session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()

    def upsert_profile(self, org_id: UUID, data: dict[str, Any]) -> ComplianceProfile:
        profile = self.get_profile(org_id)
        if profile is None:
            profile = ComplianceProfile(org_id=org_id)
            self.session.add(profile)
        for field in ("enabled", "industry_module", "council_name", "trade_waste_consent_reference"):
            if field in data:
                setattr(profile, field, data[field])
        if "settings" in data:
            profile.settings = data["settings"] or {}
        self.session.commit()
        return profile

    def add_record(self, org_id: UUID, user_id: UUID, data: dict[str, Any]) -> ComplianceRecord:
        record = ComplianceRecord(org_id=org_id, created_by_user_id=user_id, **data)
        self.session.add(record)
        self.session.commit()
        return record

    def product_profiles(self, org_id: UUID) -> list[AlcoholProductProfile]:
        return (
            self.session.query(AlcoholProductProfile)
            .filter(AlcoholProductProfile.org_id == org_id)
            .order_by(AlcoholProductProfile.inventory_name)
            .all()
        )

    def add_product_profile(self, org_id: UUID, data: dict[str, Any]) -> AlcoholProductProfile:
        profile = AlcoholProductProfile(org_id=org_id, **data)
        self.session.add(profile)
        self.session.commit()
        return profile

    def records(self, org_id: UUID, framework_slug: str | None = None) -> list[ComplianceRecord]:
        query = self.session.query(ComplianceRecord).filter(ComplianceRecord.org_id == org_id)
        if framework_slug:
            query = query.filter(ComplianceRecord.framework_slug == framework_slug)
        return query.order_by(ComplianceRecord.created_at.desc()).all()

    def invalid_core_source_references(self, org_id: UUID, source_refs: list[str]) -> list[str]:
        """Ensure a claimed Core link actually belongs to this tenant.

        External documents stay in ``evidence_reference``.  ``source_refs`` is deliberately
        stricter: it is a trustable link to a known core execution, evidence file or inventory
        movement, rather than unverified text that merely looks connected.
        """
        invalid: list[str] = []
        parsed_source_ids: set[UUID] = set()
        for source_ref in source_refs:
            try:
                source_id = UUID(source_ref)
            except (TypeError, ValueError):
                invalid.append(source_ref)
                continue
            parsed_source_ids.add(source_id)

        if not parsed_source_ids:
            return invalid

        # A record may join any Core evidence type. Fetch each finite source table once
        # rather than querying once per reference (audit packs can carry many references).
        valid_source_ids = {
            source_id
            for rows in (
                self.session.query(Execution.id)
                .filter(Execution.org_id == org_id, Execution.id.in_(parsed_source_ids))
                .all(),
                self.session.query(ExecutionEvidence.id)
                .filter(ExecutionEvidence.org_id == org_id, ExecutionEvidence.id.in_(parsed_source_ids))
                .all(),
                self.session.query(ExecutionStep.id)
                .filter(ExecutionStep.org_id == org_id, ExecutionStep.id.in_(parsed_source_ids))
                .all(),
                self.session.query(InventoryMovement.id)
                .filter(InventoryMovement.org_id == org_id, InventoryMovement.id.in_(parsed_source_ids))
                .all(),
                self.session.query(InventoryItem.id)
                .filter(InventoryItem.org_id == org_id, InventoryItem.id.in_(parsed_source_ids))
                .all(),
            )
            for (source_id,) in rows
        }
        for source_ref in source_refs:
            try:
                source_id = UUID(source_ref)
            except (TypeError, ValueError):
                continue
            if source_id not in valid_source_ids:
                invalid.append(source_ref)
        return invalid

    def _core_movement_summary(self, org_id: UUID) -> dict[str, str]:
        rows = (
            self.session.query(InventoryMovement.movement_type, func.coalesce(func.sum(InventoryMovement.quantity), 0))
            .filter(InventoryMovement.org_id == org_id)
            .group_by(InventoryMovement.movement_type)
            .all()
        )
        return {str(kind): str(quantity) for kind, quantity in rows}

    def data_coverage(
        self,
        org_id: UUID,
        reconciliation: dict[str, Any] | None = None,
        records: list[ComplianceRecord] | None = None,
    ) -> dict[str, Any]:
        """Make the boundary of derived insight visible instead of implying omniscience.

        Accepts already-computed reconciliation/records so callers building a full overview
        or audit pack don't re-run the org-wide movement scan and records query a second time.
        """
        latest_movement = (
            self.session.query(func.max(InventoryMovement.created_at))
            .filter(InventoryMovement.org_id == org_id)
            .scalar()
        )
        profiles = self.product_profiles(org_id)
        live = reconciliation if reconciliation is not None else self.customs_reconciliation(org_id)
        if records is None:
            records = self.records(org_id)
        evidence_records = sum(1 for record in records if record.evidence_reference)
        linked_records = sum(1 for record in records if record.source_refs)
        gaps = live["unprofiled_movement_count"] + live["unsupported_unit_movement_count"]
        completed_prompt_steps = (
            self.session.query(ExecutionStep)
            .filter(
                ExecutionStep.org_id == org_id,
                ExecutionStep.status == ExecutionStepStatus.COMPLETED,
                ExecutionStep.execution_data.isnot(None),
            )
            .count()
        )
        active_evidence_files = (
            self.session.query(ExecutionEvidence)
            .filter(ExecutionEvidence.org_id == org_id, ExecutionEvidence.evidence_status == EVIDENCE_STATUS_ACTIVE)
            .count()
        )
        return _iso(
            {
                "inventory_movements_last_updated_at": latest_movement,
                "alcohol_product_profiles": len(profiles),
                "unresolved_live_data_gaps": gaps,
                "manual_evidence_records": len(records),
                "records_with_evidence_reference": evidence_records,
                "records_linked_to_core": linked_records,
                "completed_core_steps_with_captured_data": completed_prompt_steps,
                "active_core_evidence_files": active_evidence_files,
                "scope": "Customs production and wastage LAL is derived from Core inventory movements; other obligations are evidence-led until their data capture is connected.",
            }
        )

    def recent_core_proof(self, org_id: UUID) -> list[dict[str, Any]]:
        """Offer captured Core proof to reuse, avoiding a parallel compliance record system."""
        files = (
            self.session.query(ExecutionEvidence)
            .filter(ExecutionEvidence.org_id == org_id, ExecutionEvidence.evidence_status == EVIDENCE_STATUS_ACTIVE)
            .order_by(ExecutionEvidence.created_at.desc())
            .limit(8)
            .all()
        )
        file_candidates = [
            _iso(
                {
                    "id": record.id,
                    "execution_id": record.execution_id,
                    "kind": "file",
                    "title": record.file_name,
                    "created_at": record.created_at,
                }
            )
            for record in files
        ]
        steps = (
            self.session.query(ExecutionStep, Step.name)
            .join(Step, Step.id == ExecutionStep.step_id)
            .filter(
                ExecutionStep.org_id == org_id,
                ExecutionStep.status == ExecutionStepStatus.COMPLETED,
                ExecutionStep.execution_data.isnot(None),
            )
            .order_by(ExecutionStep.completed_at.desc())
            .limit(8)
            .all()
        )
        step_candidates = [
            _iso(
                {
                    "id": step.id,
                    "execution_id": step.execution_id,
                    "kind": "execution-step",
                    "title": f"Completed Core step: {step_name}",
                    "created_at": step.completed_at,
                }
            )
            for step, step_name in steps
        ]
        return (file_candidates + step_candidates)[:8]

    def customs_reconciliation(self, org_id: UUID) -> dict[str, Any]:
        """Calculate litres of alcohol from profiled production and wastage movements.

        Unprofiled or incompatible movements are stated explicitly. They are never
        treated as zero, because that would make an apparent reconciliation unreliable.
        """
        profiles = {profile.inventory_name: profile for profile in self.product_profiles(org_id) if profile.is_active}
        movements = (
            self.session.query(InventoryMovement, InventoryItem.name)
            .join(InventoryItem, InventoryItem.id == InventoryMovement.inventory_item_id)
            .filter(InventoryMovement.org_id == org_id)
            .all()
        )
        return calculate_customs_reconciliation(profiles, movements)

    def _control_state(
        self,
        profile: ComplianceProfile,
        framework: dict[str, Any],
        control_id: str,
        records: list[ComplianceRecord],
        reconciliation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        relevant = [record for record in records if record.control_id == control_id]
        today = date.today()
        failed = next((record for record in relevant if record.status in {"failed", "open"}), None)
        overdue = next((record for record in relevant if record.due_date and record.due_date < today), None)
        breached = next(
            (
                record
                for record in relevant
                if record.measured_value is not None
                and record.limit_value is not None
                and record.measured_value > record.limit_value
            ),
            None,
        )
        if failed or overdue or breached:
            reason = "Open or failed record"
            if overdue:
                reason = f"Overdue since {overdue.due_date.isoformat()}"
            elif breached:
                reason = "Recorded value exceeds configured limit"
            return {"control_id": control_id, "state": "attention", "reason": reason, "record_count": len(relevant)}

        # The two controls below can prove their setup from trusted core/CRM data.
        if control_id == "product-mapping":
            mapping_count = len(self.product_profiles(profile.org_id))
            crm_mapping_count = (
                self.session.query(ProductMapping).filter(ProductMapping.org_id == profile.org_id).count()
            )
            if mapping_count:
                return {
                    "control_id": control_id,
                    "state": "compliant",
                    "reason": "Alcohol product profiles configured",
                    "record_count": mapping_count,
                }
            if crm_mapping_count or (profile.settings or {}).get("customs_product_mappings"):
                return {
                    "control_id": control_id,
                    "state": "setup",
                    "reason": "Sales mapping exists; add ABV product profiles for reconciliation",
                    "record_count": crm_mapping_count,
                }
        if control_id == "reconciliation":
            live = reconciliation if reconciliation is not None else self.customs_reconciliation(profile.org_id)
            if not live["profiled_product_count"]:
                return {
                    "control_id": control_id,
                    "state": "setup",
                    "reason": "Add alcohol product profiles before calculating litres of alcohol",
                    "record_count": len(relevant),
                }
            if live["unprofiled_movement_count"] or live["unsupported_unit_movement_count"]:
                return {
                    "control_id": control_id,
                    "state": "attention",
                    "reason": "Live Customs calculation has unprofiled or unsupported movements",
                    "record_count": len(relevant),
                }
            declared_raw = next(
                (
                    record.details["declared_litres_of_alcohol"]
                    for record in relevant
                    if isinstance(record.details, dict) and record.details.get("declared_litres_of_alcohol") is not None
                ),
                None,
            )
            if declared_raw is not None:
                try:
                    declared = Decimal(str(declared_raw))
                except InvalidOperation:
                    return {
                        "control_id": control_id,
                        "state": "attention",
                        "reason": "Declared LAL must be numeric",
                        "record_count": len(relevant),
                    }
                calculated = Decimal(live["production_litres_of_alcohol"]) - Decimal(live["wastage_litres_of_alcohol"])
                try:
                    tolerance = Decimal(str((profile.settings or {}).get("customs_lal_tolerance", "0.01")))
                except InvalidOperation:
                    tolerance = Decimal("0.01")
                variance = abs(calculated - declared)
                if variance > tolerance:
                    return {
                        "control_id": control_id,
                        "state": "attention",
                        "reason": f"Declared LAL differs from calculated LAL by {variance}",
                        "record_count": len(relevant),
                    }
        if control_id == "consent-profile" and profile.council_name and profile.trade_waste_consent_reference:
            return {
                "control_id": control_id,
                "state": "compliant",
                "reason": "Council consent profile configured",
                "record_count": 0,
            }
        if relevant:
            return {
                "control_id": control_id,
                "state": "compliant",
                "reason": "Current evidence recorded",
                "record_count": len(relevant),
            }
        return {
            "control_id": control_id,
            "state": "setup",
            "reason": "Evidence or configuration required",
            "record_count": 0,
        }

    def evaluate(
        self,
        org_id: UUID,
        records: list[ComplianceRecord] | None = None,
        reconciliation: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        profile = self.get_profile(org_id)
        if profile is None or not profile.enabled:
            return []
        if records is None:
            records = self.records(org_id)
        frameworks: list[dict[str, Any]] = []
        for base_framework in NZ_ALCOHOL_FRAMEWORKS:
            framework = framework_for_profile(base_framework, profile.settings or {})
            applies_to = framework.get("applies_to", "all_alcohol")
            if not framework_applies(applies_to, profile.settings, profile.trade_waste_consent_reference):
                continue
            controls = []
            for control_id, description in framework["controls"]:
                control = self._control_state(profile, framework, control_id, records, reconciliation)
                control["description"] = description
                control["capture"] = capture_requirements(framework["slug"], control_id, profile.settings or {})
                control["source_reference"] = control_reference(framework["slug"], control_id)
                controls.append(control)
            states = {control["state"] for control in controls}
            state = "attention" if "attention" in states else "setup" if "setup" in states else "compliant"
            current_controls = sum(control["state"] == "compliant" for control in controls)
            frameworks.append(
                {
                    "slug": framework["slug"],
                    "name": framework["name"],
                    "version": framework["version"],
                    "source_title": framework["source_title"],
                    "source_url": framework["source_url"],
                    "applicable_product_types": list(applies_to) if isinstance(applies_to, tuple) else applies_to,
                    "state": state,
                    "controls": controls,
                    # This is evidence coverage, not a regulatory compliance score.
                    # It tells an operator how much of this selected module presently
                    # has a current proof record or a bounded Core observation.
                    "evidence_coverage": {
                        "current_controls": current_controls,
                        "total_controls": len(controls),
                        "percent": round((current_controls / len(controls)) * 100) if controls else 0,
                        "label": "Current operational evidence coverage",
                    },
                }
            )
        return frameworks

    def overview(self, org_id: UUID) -> dict[str, Any]:
        profile = self.get_profile(org_id)
        # Computed once and threaded through evaluate()/data_coverage() below: both would
        # otherwise re-run the org-wide movement scan and records query on every dashboard
        # load. profile.enabled is a precondition for evaluate() ever returning frameworks
        # (customs-alcohol always matches once enabled), so this mirrors the old `if frameworks`
        # gate without needing frameworks computed first.
        if profile is not None and profile.enabled:
            records = self.records(org_id)
            reconciliation = self.customs_reconciliation(org_id)
        else:
            records = []
            reconciliation = {}
        frameworks = self.evaluate(org_id, records=records, reconciliation=reconciliation)
        for framework in frameworks:
            overdue = sum(
                1
                for control in framework["controls"]
                if str(control.get("reason") or "").startswith("Overdue since")
            )
            framework["summary_health"] = module_summary_health(framework["evidence_coverage"], overdue=overdue)
        # The tailored NP3 register considers structured logs and evidence derived
        # from Core. Project that exact health into the module summary rather than
        # showing the generic catalogue count beside a different NP3 audit count.
        if profile is not None and profile.enabled and (profile.settings or {}).get("food_control_programme") == "np3":
            np3_health = self.np3_audit(org_id)["health"]
            for framework in frameworks:
                if framework["slug"] == "np3-food-control":
                    framework["np3_audit_health"] = np3_health
                    framework["evidence_coverage"] = np3_audit_coverage(np3_health)
                    framework["summary_health"] = module_summary_health(
                        framework["evidence_coverage"], overdue=int(np3_health.get("overdue") or 0)
                    )
        counts = {"compliant": 0, "attention": 0, "setup": 0}
        for framework in frameworks:
            counts[framework["state"]] += 1
        return {
            "profile": None
            if profile is None
            else _iso(
                {
                    "enabled": profile.enabled,
                    "industry_module": profile.industry_module,
                    "council_name": profile.council_name,
                    "trade_waste_consent_reference": profile.trade_waste_consent_reference,
                    "settings": profile.settings or {},
                }
            ),
            "frameworks": frameworks,
            "counts": counts,
            "core_movement_summary": self._core_movement_summary(org_id) if frameworks else {},
            "customs_reconciliation": reconciliation,
            "data_coverage": self.data_coverage(org_id, reconciliation=reconciliation, records=records)
            if frameworks
            else {},
            "priority_actions": build_priority_actions(profile, frameworks, reconciliation, records=records),
            "evidence_readiness": {
                "current_controls": sum(framework["summary_health"]["evidence_ready"] for framework in frameworks),
                "total_controls": sum(framework["summary_health"]["total_controls"] for framework in frameworks),
                "label": "Current operational evidence, not a legal compliance score.",
            },
            "core_proof_candidates": self.recent_core_proof(org_id) if profile else [],
            "trade_waste_catalogues": [
                {key: value for key, value in catalogue.items() if key != "controls"} | {"slug": slug}
                for slug, catalogue in TRADE_WASTE_CATALOGUES.items()
            ],
            "selected_trade_waste_catalogue": council_catalogue((profile.settings or {}).get("trade_waste_council"))
            if profile
            else None,
            "disclaimer": "Operational evidence status only. Review requirements with the relevant regulator or adviser.",
        }

    def np3_audit(self, org_id: UUID) -> dict[str, Any]:
        """Return the upcoming-verification checklist and only its linked evidence."""
        profile = self.get_profile(org_id)
        settings = profile.settings or {} if profile else {}
        if profile is not None and profile.enabled and settings.get("food_control_programme", "np3") != "np3":
            raise ValueError("Select National Programme 3 in Configuration to use the NP3 audit plan")
        records = self.records(org_id, "np3-food-control") if profile and profile.enabled else []
        derived_evidence, live_summary = (
            derive_np3_core_evidence(self.session, org_id) if profile and profile.enabled else ([], {})
        )
        staff = (
            [
                {
                    "id": str(user.id),
                    "name": " ".join(part for part in (user.first_name, user.last_name) if part) or user.email,
                    "created_at": user.created_at,
                }
                for user in self.session.query(User)
                .filter(User.org_id == org_id, User.is_active.is_(True))
                .order_by(User.first_name, User.last_name, User.email)
                .all()
            ]
            if profile and profile.enabled
            else []
        )
        rows = build_np3_audit_rows(records, derived_evidence, staff=staff)
        review_interval_months = settings.get("np3_review_interval_months", 6)
        check_review_intervals = settings.get("np3_check_review_intervals", {})
        for row in rows:
            row["default_review_interval_months"] = check_review_intervals.get(
                row["control_id"], review_interval_months
            )
        signer_ids = {
            event["created_by_user_id"] for row in rows for event in row["history"] if event["created_by_user_id"]
        }
        signers = (
            {
                user.id: " ".join(part for part in (user.first_name, user.last_name) if part) or user.email
                for user in self.session.query(User).filter(User.org_id == org_id, User.id.in_(signer_ids)).all()
            }
            if signer_ids
            else {}
        )
        for row in rows:
            for event in row["history"]:
                event["signed_off_by"] = signers.get(event.pop("created_by_user_id"), "Former team member")
        # Recap topics can appear in two navigation sections. They are one underlying
        # control, so health cards and notifications deliberately count them once.
        unique_rows = list({row["control_id"]: row for row in rows}.values())
        counts = {
            state: sum(1 for row in unique_rows if row["state"] == state) for state in ("ready", "attention", "missing")
        }
        today = date.today()
        overdue_rows = [row for row in unique_rows if row.get("review_due_date") and row["review_due_date"] < today]
        due_soon_rows = [
            row
            for row in unique_rows
            if row.get("review_due_date") and today <= row["review_due_date"] <= today + timedelta(days=30)
        ]
        staff_actions = [
            {"control_id": row["control_id"], "topic": row["topic"]} | action
            for row in unique_rows
            for action in row.get("staff_actions", [])
        ]
        guidance_actions = [row for row in unique_rows if row["guidance_update_required"]]
        remediation_rows = [
            row for row in unique_rows if any(event["status"] in {"open", "failed"} for event in row["history"])
        ]
        work_queue = (
            [
                {
                    "kind": "staff-training",
                    "severity": "attention",
                    "control_id": action["control_id"],
                    "title": f"Record training and competency for {action['name']}",
                    "description": action["reason"],
                    "person": action["name"],
                }
                for action in staff_actions
            ]
            + [
                {
                    "kind": "overdue-review",
                    "severity": "overdue",
                    "control_id": row["control_id"],
                    "title": f"Review overdue: {row['topic']}",
                    "description": "The scheduled NP3 sign-off is overdue. Review the evidence and create a fresh attestation.",
                    "due_date": row["review_due_date"],
                }
                for row in overdue_rows
            ]
            + [
                {
                    "kind": "guidance-update",
                    "severity": "attention",
                    "control_id": row["control_id"],
                    "title": f"Guidance changed: {row['topic']}",
                    "description": "The official NP3 guidance changed after the last sign-off. Reconfirm this check.",
                }
                for row in guidance_actions
            ]
            + [
                {
                    "kind": "open-remediation",
                    "severity": "attention",
                    "control_id": row["control_id"],
                    "title": f"Follow up an open record: {row['topic']}",
                    "description": "A logged deviation, incident or corrective action is still open.",
                }
                for row in remediation_rows
            ]
            + [
                {
                    "kind": "due-soon-review",
                    "severity": "due-soon",
                    "control_id": row["control_id"],
                    "title": f"Review due soon: {row['topic']}",
                    "description": "Review the current evidence before the scheduled sign-off date.",
                    "due_date": row["review_due_date"],
                }
                for row in due_soon_rows
            ]
        )
        return _iso(
            {
                "verification": {
                    "date": settings.get("np3_verification_date"),
                    "verifier": settings.get("np3_verifier_name"),
                    "location": settings.get("np3_verification_location"),
                },
                "default_review_interval_months": review_interval_months,
                "preparation_items": PREPARATION_ITEMS,
                "categories": [
                    {"key": f"section-{index}", "title": category}
                    for index, (category, _topics) in enumerate(NP3_AUDIT_CATEGORIES)
                ],
                "rows": rows,
                "counts": counts,
                "staff": staff,
                "health": {
                    "ok": counts["ready"],
                    "needs_attention": counts["attention"] + counts["missing"],
                    "needs_evidence": counts["missing"],
                    "overdue": len(overdue_rows),
                    "due_soon": len(due_soon_rows),
                    "staff_actions": len(staff_actions),
                    "open_remediation": len(remediation_rows),
                },
                "work_queue": work_queue,
                "configuration_required": not bool(profile and profile.enabled),
                "core_evidence": (
                    self.data_coverage(org_id, records=records) | {"live_np3_evidence": live_summary}
                    if profile and profile.enabled
                    else {}
                ),
            }
        )

    def build_audit_pack(
        self,
        org_id: UUID,
        framework_slug: str,
        generated_by_user_id: UUID,
        period_start: date | None,
        period_end: date | None,
    ) -> dict[str, Any]:
        framework = framework_by_slug(framework_slug)
        if framework is None:
            raise ValueError("Unknown framework")
        profile = self.get_profile(org_id)
        if profile is None or not profile.enabled:
            raise ValueError("Compliant is not enabled for this organisation")
        # Reject an inapplicable-but-real framework before any query: applicability is a
        # pure function of the profile's settings and the static catalogue, so it costs
        # nothing to check first and it saves every caller of a known-inapplicable slug
        # from paying for the org-wide movement scan below.
        applies_to = framework.get("applies_to", "all_alcohol")
        if not framework_applies(applies_to, profile.settings, profile.trade_waste_consent_reference):
            raise ValueError("Framework is not applicable to this organisation's current profile")
        records = self.records(org_id, framework_slug)
        if period_start or period_end:
            records = [
                record
                for record in records
                if (not period_start or not record.period_end or record.period_end >= period_start)
                and (not period_end or not record.period_start or record.period_start <= period_end)
            ]
        # Computed once and reused below: evaluate() and data_coverage() would otherwise
        # each re-run the same org-wide movement scan and records query.
        all_records = self.records(org_id)
        reconciliation = self.customs_reconciliation(org_id)
        state = next(
            (
                item
                for item in self.evaluate(org_id, records=all_records, reconciliation=reconciliation)
                if item["slug"] == framework_slug
            ),
            None,
        )
        if state is None:
            # Unreachable given the framework_applies() gate above, which uses the same
            # predicate evaluate() filters on — kept as a guard, not an assertion, so any
            # future drift between the two fails as a clean 400 instead of a 500.
            raise ValueError("Framework is not applicable to this organisation's current profile")
        payload = _iso(
            {
                "title": f"{framework['name']} audit pack",
                "generated_at": datetime.now(UTC),
                "framework": state,
                "period_start": period_start,
                "period_end": period_end,
                "profile": {"council_name": profile.council_name, "consent": profile.trade_waste_consent_reference},
                "source_data": {
                    "inventory_movements": self._core_movement_summary(org_id),
                    "customs_reconciliation": reconciliation,
                    "data_coverage": self.data_coverage(org_id, reconciliation=reconciliation, records=all_records),
                },
                "records": [serialise_record(record) for record in records],
                "disclaimer": "This pack presents recorded evidence and derived operational checks; it is not a certification of legal compliance.",
            }
        )
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        report = ComplianceReport(
            org_id=org_id,
            framework_slug=framework_slug,
            period_start=period_start,
            period_end=period_end,
            generated_by_user_id=generated_by_user_id,
            checksum_sha256=checksum,
            payload=payload,
        )
        self.session.add(report)
        self.session.commit()
        return {"report_id": str(report.id), "checksum_sha256": checksum, "payload": payload}
