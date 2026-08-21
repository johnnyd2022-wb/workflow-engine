"""Business logic for the industry process template catalogue: capability/module
policy resolution, catalogue read shaping, and copy-into-tenant orchestration.

No Flask imports here (repo-conventions §1) — routes pass org_id/session in explicitly.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend.event_writer import EventWriter
from app.core.db.models.process import Process
from app.core.db.repositories.process_repo import ProcessRepository
from app.features.compliant.service import ComplianceService
from app.features.process_templates.catalog import registry
from app.features.process_templates.catalog.registry import ProcessTemplate

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
