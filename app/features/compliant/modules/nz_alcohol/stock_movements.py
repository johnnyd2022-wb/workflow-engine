"""Evidence-backed CCA transfer policy; accounting gaps remain closed.

Authority: Customs 'Moving products excise-unpaid'. Destination OSS movements
require prior approval even where both premises belong to the same legal entity.
Further-manufacture, product-owner and export authorities need trusted contracts
before this implementation can accept them; they are not inferred from site kind.
"""

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from app.features.compliant.models.alcohol_product_profile import AlcoholProductProfile
from app.features.compliant.modules.nz_alcohol.excise import _base_name
from app.features.compliant.modules.nz_alcohol.movement_registrations import coverage_findings
from app.features.compliant.modules.nz_alcohol.premises import licence_for_area
from app.features.compliant.platform.stock_movements import MovementDecision

POLICY_VERSION = "nz_alcohol_cca_1"


def _deny(reason):
    return MovementDecision(False, reason)


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 500


def _binding(context):
    return {
        "transfer_id": str(context.transfer_id),
        "source_item_id": str(context.source_item_id),
        "source_site_id": str(context.source_site_id),
        "source_location_id": str(context.source_location_id) if context.source_location_id else None,
        "destination_site_id": str(context.destination_site_id),
        "destination_location_id": str(context.destination_location_id) if context.destination_location_id else None,
        "product_name": context.product_name,
        "unit": context.unit,
    }


def _licence(row):
    return {
        "id": str(row.id),
        "number": row.number,
        "kind": row.kind,
        "legal_entity_reference": row.legal_entity_reference,
        "evidence_reference": row.evidence_reference,
        "valid_from": row.valid_from.isoformat(),
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
    }


class NZAlcoholMovementPolicy:
    module_id = "nz_alcohol"

    def prepare(self, session, org_id, source_item_id):
        from app.features.compliant.modules.nz_alcohol.movement_excise import prepare_dispatch_duty

        return prepare_dispatch_duty(session, org_id, source_item_id)

    def requirements(self):
        return {
            "authority_permission": "compliance.manage",
            "fields": [
                {
                    "name": "destination_activity",
                    "type": "select",
                    "label": "Intended activity at destination",
                    "required": True,
                    "options": [
                        {"value": "storage", "label": "Storage"},
                        {"value": "manufacturing", "label": "Manufacturing"},
                        {"value": "selling", "label": "Selling"},
                    ],
                },
                {
                    "name": "authority",
                    "type": "select",
                    "label": "Movement authority",
                    "required": True,
                    "options": [
                        {"value": "same_legal_entity", "label": "CCA licences held by the same legal entity"},
                        {"value": "prior_customs_approval", "label": "Prior Customs approval"},
                        {"value": "home_consumption", "label": "Removal for home consumption (producer pays duty)"},
                    ],
                },
                {
                    "name": "reference",
                    "type": "text",
                    "label": "Customs approval reference (when required)",
                    "required": False,
                },
                {
                    "name": "approved_on",
                    "type": "date",
                    "label": "Customs approval date (when required)",
                    "required": False,
                },
                {
                    "name": "evidence_reference",
                    "type": "text",
                    "label": "Authority evidence reference",
                    "required": True,
                },
                {
                    "name": "measured_abv_percent",
                    "type": "text",
                    "label": "Tested spirits strength (% ABV; home consumption)",
                    "required": False,
                },
                {
                    "name": "measurement_method",
                    "type": "select",
                    "label": "Strength testing method (home consumption)",
                    "required": False,
                    "options": [
                        {"value": "analysis", "label": "Analysis"},
                        {"value": "hydrometric", "label": "Hydrometric"},
                    ],
                },
                {
                    "name": "measured_on",
                    "type": "date",
                    "label": "Strength tested on (home consumption)",
                    "required": False,
                },
                {
                    "name": "measurement_reference",
                    "type": "text",
                    "label": "Strength report reference (home consumption)",
                    "required": False,
                },
                {
                    "name": "volume_reference",
                    "type": "text",
                    "label": "Pack or volume evidence reference (home consumption)",
                    "required": False,
                },
            ],
        }

    def evaluate(self, session, org_id, context):
        if context.operation not in {"dispatch", "receipt", "loss"}:
            return _deny("Unknown stock movement operation")
        if type(context.occurred_on) is not date:
            return _deny("A valid movement date is required")
        try:
            quantity = Decimal(str(context.quantity))
        except (InvalidOperation, ValueError):
            return _deny("A finite positive movement quantity is required")
        if not quantity.is_finite() or quantity <= 0 or not _text(context.unit):
            return _deny("A finite positive quantity and unit are required")
        if not _text(context.product_name):
            return _deny("A valid product name is required")
        products = (
            session.query(AlcoholProductProfile)
            .filter(
                AlcoholProductProfile.org_id == org_id,
                AlcoholProductProfile.is_active.is_(True),
            )
            .all()
        )
        matching = [p for p in products if p.inventory_name.casefold() == _base_name(context.product_name).casefold()]
        if len(matching) != 1:
            return _deny("Classify this product's Customs treatment before transferring it")
        product = matching[0]
        if context.operation == "loss":
            return _deny("Transit loss needs Customs accounting before it can be confirmed")
        destination = licence_for_area(
            session, org_id, context.destination_site_id, context.destination_location_id, context.occurred_on
        )
        if context.operation == "receipt":
            return self._receipt(session, org_id, context, destination, quantity)
        source = licence_for_area(
            session, org_id, context.source_site_id, context.source_location_id, context.occurred_on
        )
        if source is None:
            return _deny("The dispatch area needs valid dated Customs coverage")
        if not _text(context.carrier) or not _text(context.consignment_reference):
            return _deny("Record the carrier and consignment reference before dispatch")
        approval = context.approval
        if not isinstance(approval, Mapping):
            return _deny("Record the authority for this movement")
        if set(approval) - {
            "authority",
            "reference",
            "approved_on",
            "evidence_reference",
            "destination_activity",
            "measured_abv_percent",
            "measurement_method",
            "measured_on",
            "measurement_reference",
            "volume_reference",
        }:
            return _deny("Unexpected movement approval fields")
        if any(value is not None and not isinstance(value, str) for value in approval.values()):
            return _deny("Movement approval fields must be text")
        if approval.get("destination_activity") not in (None, "storage", "manufacturing", "selling"):
            return _deny("Choose a supported destination activity")
        authority = approval.get("authority")
        if not _text(approval.get("evidence_reference")):
            return _deny("Record evidence for the movement authority")
        if destination is None:
            if authority != "home_consumption":
                return _deny("An unlicensed destination needs a documented excise removal")
            return self._home_consumption(session, org_id, context, source, product, quantity)
        if authority == "home_consumption":
            return _deny("Home-consumption removal requires a destination outside every recorded CCA")
        if authority == "prior_customs_approval":
            try:
                approved_on = date.fromisoformat(approval.get("approved_on"))
            except (ValueError, TypeError):
                return _deny("Record the Customs approval date")
            if approved_on > context.occurred_on or not _text(approval.get("reference")):
                return _deny("Customs approval must be obtained before the movement with a reference")
        elif authority == "same_legal_entity":
            if destination.kind == "oss":
                return _deny("Movement to off-site storage requires prior Customs approval")
            if source.kind not in {"lma", "oss"} or source.legal_entity_reference != destination.legal_entity_reference:
                return _deny("The registered licences do not establish this same-entity authority")
        else:
            return _deny("This movement authority is not yet supported; record prior Customs approval")
        evidence = {
            "policy": POLICY_VERSION,
            "destination_activity": approval.get("destination_activity"),
            "system_alerts": coverage_findings(
                session,
                org_id,
                context.destination_site_id,
                approval.get("destination_activity"),
                context.occurred_on,
                context.transfer_id,
            ),
            "binding": _binding(context),
            "dispatched_quantity": str(quantity),
            "dispatched_on": context.occurred_on.isoformat(),
            "carrier": context.carrier,
            "consignment_reference": context.consignment_reference,
            "product_profile_id": str(product.id),
            "source_licence": _licence(source),
            "destination_licence": _licence(destination),
            "authority": {
                key: approval.get(key) for key in ("authority", "reference", "approved_on", "evidence_reference")
            },
        }
        return MovementDecision(True, "Recorded CCA movement authority", json.dumps(evidence, sort_keys=True))

    def _home_consumption(self, session, org_id, context, source, product, quantity):
        from app.features.compliant.modules.nz_alcohol.movement_excise import capture_spirits_removal_basis

        prepared = context.prepared_context
        snapshot = context.source_snapshot
        if not isinstance(prepared, Mapping) or prepared.get("found") is not True:
            return _deny("Source duty responsibility was not prepared before stock locking")
        if prepared.get("source_item_id") != str(context.source_item_id) or any(
            prepared.get(key) != snapshot.get(key) for key in ("source_execution_step_id", "source_execution_id")
        ):
            return _deny("Source production provenance changed before the removal")
        if prepared.get("duty_responsibility") != "producer_licensee":
            return _deny("Customer contract duty needs verified CCA authority and cannot use producer home consumption")
        captured = capture_spirits_removal_basis(session, org_id, context, product, source)
        if not captured.valid:
            return _deny(captured.reason)
        evidence = {
            "policy": POLICY_VERSION,
            "binding": _binding(context),
            "destination_activity": context.approval.get("destination_activity"),
            "system_alerts": coverage_findings(
                session,
                org_id,
                context.destination_site_id,
                context.approval.get("destination_activity"),
                context.occurred_on,
                context.transfer_id,
            ),
            "dispatched_quantity": str(quantity),
            "dispatched_on": context.occurred_on.isoformat(),
            "carrier": context.carrier,
            "consignment_reference": context.consignment_reference,
            "product_profile_id": str(product.id),
            "source_licence": _licence(source),
            "destination_licence": None,
            "authority": {
                "authority": "home_consumption",
                "evidence_reference": context.approval.get("evidence_reference"),
            },
            "tax_status": "home_consumption_excise_due",
            "duty_responsibility": "producer_licensee",
            "contract_order_id": prepared.get("contract_order_id"),
            "removal_basis": json.loads(captured.evidence),
        }
        return MovementDecision(
            True, "Recorded producer-liable home-consumption removal", json.dumps(evidence, sort_keys=True)
        )

    def _receipt(self, session, org_id, context, destination, quantity):
        evidence = context.dispatch_evidence
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except (ValueError, TypeError):
                return _deny("The immutable dispatch decision is missing or invalid")
        if not isinstance(evidence, Mapping) or evidence.get("policy") != POLICY_VERSION:
            return _deny("The immutable dispatch decision is missing or invalid")
        if evidence.get("binding") != _binding(context):
            return _deny("Receipt does not match its immutable dispatch")
        authority = evidence.get("authority")
        if not isinstance(authority, Mapping):
            return _deny("The immutable dispatch authority is missing or invalid")
        treatment = authority.get("authority")
        if treatment == "home_consumption":
            basis = evidence.get("removal_basis")
            source_cca = basis.get("source_cca") if isinstance(basis, Mapping) else None
            source_licence = evidence.get("source_licence")
            if (
                destination is not None
                or evidence.get("tax_status") != "home_consumption_excise_due"
                or evidence.get("duty_responsibility") != "producer_licensee"
                or not isinstance(basis, Mapping)
                or basis.get("transfer_id") != str(context.transfer_id)
                or basis.get("source_item_id") != str(context.source_item_id)
                or not isinstance(source_cca, Mapping)
                or not isinstance(source_licence, Mapping)
                or source_cca.get("id") != source_licence.get("id")
            ):
                return _deny("Home-consumption destination changed; review the receipt without granting a duty credit")
            destination_id = None
        elif destination is None:
            return _deny("The destination needs dated Customs coverage matching its dispatch")
        try:
            dispatched = Decimal(evidence["dispatched_quantity"])
            dispatched_on = date.fromisoformat(evidence["dispatched_on"])
            if treatment != "home_consumption":
                destination_id = evidence["destination_licence"]["id"]
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return _deny("The immutable dispatch decision is invalid")
        if not dispatched.is_finite() or quantity > dispatched or context.occurred_on < dispatched_on:
            return _deny("Receipt quantity or date conflicts with the dispatch")
        if destination is not None and destination_id != str(destination.id):
            return _deny("Destination Customs coverage changed; review the transfer before receipt")
        result = {
            "policy": POLICY_VERSION,
            "binding": _binding(context),
            "destination_activity": evidence.get("destination_activity"),
            "system_alerts": coverage_findings(
                session,
                org_id,
                context.destination_site_id,
                evidence.get("destination_activity"),
                context.occurred_on,
                f"{context.transfer_id}-receipt-{context.receipt_id}",
            ),
            "received_quantity": str(quantity),
            "received_on": context.occurred_on.isoformat(),
            "receipt_id": str(context.receipt_id),
            "dispatch": dict(evidence),
            "destination_licence": _licence(destination) if destination else None,
            "tax_status": "home_consumption_excise_due" if treatment == "home_consumption" else "excise_unpaid",
        }
        return MovementDecision(True, "Receipt matches its recorded CCA authority", json.dumps(result, sort_keys=True))
