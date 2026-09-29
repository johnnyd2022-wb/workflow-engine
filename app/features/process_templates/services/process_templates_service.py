"""Business logic for the industry process template catalogue: capability/module
policy resolution, catalogue read shaping, and copy-into-tenant orchestration.

No Flask imports here (repo-conventions §1) — routes pass org_id/session in explicitly.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.db.models.process import Process, ProcessCategory
from app.core.db.repositories.process_repo import ProcessRepository
from app.features.compliant.service import ComplianceService
from app.features.process_templates.catalog import registry
from app.features.process_templates.catalog.registry import ProcessTemplate
from app.observability import get_logger

logger = get_logger(__name__)

_DESCRIPTION_MAX_LEN = 1000


def _resolve_permitted_families(session: Session, org_id: UUID) -> list[str]:
    profile = ComplianceService(session).get_profile(org_id)
    compliant_enabled = bool(profile and profile.enabled)
    industry_module = profile.industry_module if profile else None
    return registry.resolve_permitted_families(compliant_enabled=compliant_enabled, industry_module=industry_module)


def _template_summary(template: ProcessTemplate) -> dict:
    return {
        "id": template.id,
        "family": template.family,
        "name": template.name,
        "description": template.description,
        "traceability_shape": template.traceability_shape,
        "step_count": 1,
        "default_units": sorted({i.unit for i in template.inputs} | {o.unit for o in template.outputs}),
        "version": template.version,
        "advisory": registry.TEMPLATE_CUSTOMISE_ADVISORY,
    }


def _template_detail(template: ProcessTemplate) -> dict:
    summary = _template_summary(template)
    summary["step"] = {
        "name": template.step_name,
        "inputs": [
            {
                "name": i.name,
                "quantity": 1,
                "unit": i.unit,
                "requires_inventory_selection": i.requires_inventory_selection,
            }
            for i in template.inputs
        ],
        "outputs": [
            {
                "name": o.name,
                "quantity": 1,
                "unit": o.unit,
                "extra_data": ({"sample_only": True} if o.sample_only else {}),
            }
            for o in template.outputs
        ],
        "execution_prompts": [
            {"label": p.label, "type": p.type, "unit": p.unit, "required": p.required} for p in template.prompts
        ],
    }
    return summary


def list_catalog(session: Session, org_id: UUID, family_filter: str | None = None) -> dict:
    families = _resolve_permitted_families(session, org_id)
    templates = registry.templates_for_families(families, family_filter)
    return {
        "families": [{"key": f, **registry.FAMILY_METADATA.get(f, {"name": f, "description": ""})} for f in families],
        "templates": [_template_summary(t) for t in templates],
    }


def get_template_detail(session: Session, org_id: UUID, template_id: str) -> dict | None:
    families = _resolve_permitted_families(session, org_id)
    template = registry.get_permitted_template(template_id, families)
    if template is None:
        if registry.get_template_by_id(template_id) is not None:
            # A real catalogue id, wrong family for this org — the tenant-boundary
            # probe this feature's whole capability-gating design exists to catch.
            # Same generic event name every other cross-tenant 404 in the app uses
            # (backend.py's _log_process_access_denied/_log_trace_access_denied),
            # so one query covers all of them.
            logger.warning(
                "access_denied", reason="template_family_not_permitted", org_id=str(org_id), template_id=template_id
            )
        return None
    return _template_detail(template)


def _build_description(template: ProcessTemplate) -> str:
    suffix = f"Created from: {template.name} v{template.version}"
    if not template.description:
        return suffix[:_DESCRIPTION_MAX_LEN]
    combined = f"{template.description}\n\n{suffix}"
    if len(combined) <= _DESCRIPTION_MAX_LEN:
        return combined
    # Truncate the template's own description first so the provenance suffix survives.
    room_for_description = _DESCRIPTION_MAX_LEN - len(suffix) - 2  # 2 for "\n\n"
    if room_for_description <= 0:
        return suffix[:_DESCRIPTION_MAX_LEN]
    return f"{template.description[:room_for_description]}\n\n{suffix}"


def copy_template(session: Session, org_id: UUID, template_id: str) -> Process | None:
    families = _resolve_permitted_families(session, org_id)
    template = registry.get_permitted_template(template_id, families)
    if template is None:
        if registry.get_template_by_id(template_id) is not None:
            logger.warning(
                "access_denied", reason="template_family_not_permitted", org_id=str(org_id), template_id=template_id
            )
        return None

    repo = ProcessRepository(session)
    process = repo.create_process(
        org_id=org_id,
        name=template.name,
        description=_build_description(template),
        category=template.category,
        is_draft=True,
    )
    repo.add_step(
        process_id=process.id,
        org_id=org_id,
        step_number=1,
        position=1000,
        name=template.step_name,
        inputs=[
            {
                "name": i.name,
                "quantity": 1,
                "unit": i.unit,
                "requires_inventory_selection": i.requires_inventory_selection,
            }
            for i in template.inputs
        ],
        outputs=[
            {
                "name": o.name,
                "quantity": 1,
                "unit": o.unit,
                "extra_data": ({"sample_only": True} if o.sample_only else {}),
            }
            for o in template.outputs
        ],
        execution_prompts=[
            {"label": p.label, "type": p.type, "unit": p.unit, "required": p.required} for p in template.prompts
        ],
    )

    EventWriter(session, org_id).emit(
        event_type="process_templates.template_copied",
        entity_type="process",
        entity_id=process.id,
        payload={"template_id": template.id, "family": template.family, "process_id": str(process.id)},
    )
    session.commit()
    logger.info(
        "process_templates_template_copied",
        org_id=str(org_id),
        template_id=template.id,
        family=template.family,
        process_id=str(process.id),
    )
    return process


def emit_catalog_viewed(session: Session, org_id: UUID) -> None:
    EventWriter(session, org_id).emit(
        event_type="process_templates.catalog_viewed",
        entity_type="process_template_catalog",
        entity_id=org_id,
        payload={},
    )
    session.commit()


def emit_template_selected(session: Session, org_id: UUID, template_id: str) -> None:
    EventWriter(session, org_id).emit(
        event_type="process_templates.template_selected",
        entity_type="process_template_catalog",
        entity_id=org_id,
        payload={"template_id": template_id},
    )
    session.commit()


# --- starter packs (plan 2.4c) ---------------------------------------------------------------


def _pack_summary(pack) -> dict:
    from app.features.compliant.platform.presets import describe_checks

    titles = describe_checks([cid for cid, _why in pack.key_checks])
    return {
        "id": pack.id,
        "product_type": pack.product_type,
        "name": pack.name,
        "description": pack.description,
        "steps": [s.name for s in pack.steps],
        "final_output": pack.final_output,
        "key_checks": [
            {"control_id": cid, "title": titles.get(cid) or cid, "why": why} for cid, why in pack.key_checks
        ],
        "advisory": registry.TEMPLATE_CUSTOMISE_ADVISORY,
    }


def list_starter_packs(session: Session, org_id: UUID) -> list[dict]:
    from app.features.process_templates.catalog.starter_packs import STARTER_PACKS

    families = set(_resolve_permitted_families(session, org_id))
    return [_pack_summary(p) for p in STARTER_PACKS if p.family in families]


def apply_starter_pack(session: Session, org_id: UUID, pack_id: str, configure_compliance: bool) -> dict | None:
    """Create the pack's workflow (once) and, if allowed, preconfigure its compliance fields."""
    from uuid import uuid4

    from app.features.compliant.platform.presets import apply_product_preset
    from app.features.process_templates.catalog.starter_packs import get_pack

    pack = get_pack(pack_id)
    if pack is None or pack.family not in set(_resolve_permitted_families(session, org_id)):
        return None
    existing = session.query(Process).filter(Process.org_id == org_id, Process.name == pack.name).first()
    created = existing is None
    process = existing
    if created:
        repo = ProcessRepository(session)
        process = repo.create_process(
            org_id=org_id,
            name=pack.name,
            description=f"{pack.description}\n\nCreated from the {pack.product_type} starter pack.",
            category=ProcessCategory.MANUFACTURING,
            is_draft=True,
        )
        previous = None
        for index, step in enumerate(pack.steps, start=1):
            inputs = []
            if step.takes_previous and previous is not None:
                inputs.append(
                    {
                        "name": previous["name"],
                        "source_output_id": previous["id"],
                        "quantity": 1,
                        "unit": previous["unit"],
                        "requires_inventory_selection": True,
                        "is_variable": False,
                    }
                )
            inputs += [
                {
                    "name": i.name,
                    "quantity": 1,
                    "unit": i.unit,
                    "requires_inventory_selection": i.requires_inventory_selection,
                }
                for i in step.inputs
            ]
            output = {"id": str(uuid4()), "name": step.output.name, "quantity": 1, "unit": step.output.unit}
            repo.add_step(
                process_id=process.id,
                org_id=org_id,
                step_number=index,
                position=index * 1000,
                name=step.name,
                description=step.description,
                inputs=inputs,
                outputs=[output],
                execution_prompts=[
                    {"label": p.label, "type": p.type, "unit": p.unit, "required": p.required} for p in step.prompts
                ],
            )
            previous = output
    changes = (
        apply_product_preset(session, org_id, pack.product_type, [pack.final_output]) if configure_compliance else []
    )
    EventWriter(session, org_id).emit(
        event_type="process_templates.starter_pack_applied",
        entity_type="process",
        entity_id=process.id,
        payload={"pack_id": pack.id, "created": created, "compliance_changes": len(changes)},
    )
    session.commit()
    return {
        "process_id": str(process.id),
        "created": created,
        "compliance_changes": changes,
        "compliance_skipped": not configure_compliance,
        **_pack_summary(pack),
    }
