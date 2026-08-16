"""Compliance evaluation and audit-pack assembly.

The service reads core data; it never changes inventory, executions, or CRM records.
Manual compliance records are append-only operational evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
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
from app.features.compliant.models import AlcoholProductProfile, ComplianceProfile, ComplianceRecord, ComplianceReport
from app.features.compliant.modules.nz_alcohol.catalogue import (
    NZ_ALCOHOL_FRAMEWORKS,
    capture_requirements,
    framework_by_slug,
    framework_for_profile,
)
from app.features.compliant.modules.nz_alcohol.councils import TRADE_WASTE_CATALOGUES, council_catalogue
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
    profile: ComplianceProfile | None, frameworks: list[dict[str, Any]], reconciliation: dict[str, Any]
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
        for source_ref in source_refs:
            try:
                source_id = UUID(source_ref)
            except (TypeError, ValueError):
                invalid.append(source_ref)
                continue
            exists = any(
                self.session.query(model.id).filter(model.id == source_id, model.org_id == org_id).first()
                for model in (Execution, ExecutionEvidence, ExecutionStep, InventoryMovement)
            )
            if not exists:
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

    def data_coverage(self, org_id: UUID) -> dict[str, Any]:
        """Make the boundary of derived insight visible instead of implying omniscience."""
        latest_movement = (
            self.session.query(func.max(InventoryMovement.created_at))
            .filter(InventoryMovement.org_id == org_id)
            .scalar()
        )
        profiles = self.product_profiles(org_id)
        live = self.customs_reconciliation(org_id)
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
        self, profile: ComplianceProfile, framework: dict[str, Any], control_id: str, records: list[ComplianceRecord]
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
            live = self.customs_reconciliation(profile.org_id)
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

    def evaluate(self, org_id: UUID) -> list[dict[str, Any]]:
        profile = self.get_profile(org_id)
        if profile is None or not profile.enabled:
            return []
        records = self.records(org_id)
        product_types = set((profile.settings or {}).get("alcohol_product_types") or [])
        frameworks: list[dict[str, Any]] = []
        for base_framework in NZ_ALCOHOL_FRAMEWORKS:
            framework = framework_for_profile(base_framework, profile.settings or {})
            applies_to = framework.get("applies_to", "all_alcohol")
            if applies_to == "consent_required" and not (
                profile.trade_waste_consent_reference or (profile.settings or {}).get("trade_waste_required")
            ):
                continue
            if isinstance(applies_to, tuple) and product_types and not product_types.intersection(applies_to):
                continue
            controls = []
            for control_id, description in framework["controls"]:
                control = self._control_state(profile, framework, control_id, records)
                control["description"] = description
                control["capture"] = capture_requirements(framework["slug"], control_id, profile.settings or {})
                controls.append(control)
            states = {control["state"] for control in controls}
            state = "attention" if "attention" in states else "setup" if "setup" in states else "compliant"
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
                }
            )
        return frameworks

    def overview(self, org_id: UUID) -> dict[str, Any]:
        profile = self.get_profile(org_id)
        frameworks = self.evaluate(org_id)
        reconciliation = self.customs_reconciliation(org_id) if frameworks else {}
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
            "data_coverage": self.data_coverage(org_id) if frameworks else {},
            "priority_actions": build_priority_actions(profile, frameworks, reconciliation),
            "evidence_readiness": {
                "current_controls": sum(
                    1
                    for framework in frameworks
                    for control in framework["controls"]
                    if control["state"] == "compliant"
                ),
                "total_controls": sum(len(framework["controls"]) for framework in frameworks),
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
        records = self.records(org_id, framework_slug)
        if period_start or period_end:
            records = [
                record
                for record in records
                if (not period_start or not record.period_end or record.period_end >= period_start)
                and (not period_end or not record.period_start or record.period_start <= period_end)
            ]
        state = next(item for item in self.evaluate(org_id) if item["slug"] == framework_slug)
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
                    "customs_reconciliation": self.customs_reconciliation(org_id),
                    "data_coverage": self.data_coverage(org_id),
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
