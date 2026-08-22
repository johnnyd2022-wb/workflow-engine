"""Application-owned, versioned industry process template catalogue.

Per SPEC process_templates: this is code, not a tenant-editable DB table. Each
template's applicability (`required_capability`/`industry_modules`) is declared
separately from its process/step definition, so the policy layer (`resolve_permitted_families`)
and the routes/service above it never branch on a specific industry module name — see AC4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.db.models.process import ProcessCategory


@dataclass(frozen=True)
class TemplateInput:
    name: str
    unit: str
    requires_inventory_selection: bool = True


@dataclass(frozen=True)
class TemplateOutput:
    name: str
    unit: str
    # See SPEC's `sample_only` architecture decision: forces WORK_IN_PROGRESS at
    # execution-completion time regardless of terminal-step position.
    sample_only: bool = False


@dataclass(frozen=True)
class TemplatePrompt:
    label: str
    type: str  # "text" | "number"
    unit: str | None = None
    required: bool = True


@dataclass(frozen=True)
class ProcessTemplate:
    id: str
    family: str
    name: str
    description: str
    traceability_shape: str
    category: ProcessCategory
    version: int
    step_name: str
    inputs: tuple[TemplateInput, ...] = field(default_factory=tuple)
    outputs: tuple[TemplateOutput, ...] = field(default_factory=tuple)
    prompts: tuple[TemplatePrompt, ...] = field(default_factory=tuple)


TEMPLATE_CUSTOMISE_ADVISORY = (
    "This template accelerates setup. It is not legal, food-safety, Customs, or Council "
    "advice — review and customise every label, unit and prompt against your own SOPs and "
    "regulatory obligations before use."
)

# Family metadata (display name/description shown on the catalogue's family groupings).
FAMILY_METADATA: dict[str, dict[str, str]] = {
    "distillery": {
        "name": "Distillery",
        "description": "Receiving, distillation, blending, bottling and R&D workflows for spirits producers.",
    },
    "brewery": {
        "name": "Brewery",
        "description": "Receiving, brewing, fermentation, conditioning and packaging workflows for breweries.",
    },
    "winery_vineyard": {
        "name": "Winery / Vineyard",
        "description": "Grape intake, crush, fermentation, cellar and bottling workflows for wineries and vineyards.",
    },
}

# Capability/industry-module policy, declared separately from the template definitions
# below. Core/the service layer reads this table generically; it never contains an
# `if nz_alcohol` branch of its own (AC4).
_FAMILY_CAPABILITY_MAP: dict[str, dict[str, object]] = {
    "distillery": {"required_capability": "compliant", "industry_modules": ("nz_alcohol",)},
    "brewery": {"required_capability": "compliant", "industry_modules": ("nz_alcohol",)},
    "winery_vineyard": {"required_capability": "compliant", "industry_modules": ("nz_alcohol",)},
}

_CATALOG: list[ProcessTemplate] = []


def register_template(template: ProcessTemplate) -> None:
    _CATALOG.append(template)


def register_family(
    family: str, *, required_capability: str, industry_modules: tuple[str, ...], name: str, description: str
) -> None:
    _FAMILY_CAPABILITY_MAP[family] = {"required_capability": required_capability, "industry_modules": industry_modules}
    FAMILY_METADATA[family] = {"name": name, "description": description}


def unregister_family(family: str) -> None:
    _FAMILY_CAPABILITY_MAP.pop(family, None)
    FAMILY_METADATA.pop(family, None)


def unregister_template(template_id: str) -> None:
    global _CATALOG
    _CATALOG = [t for t in _CATALOG if t.id != template_id]


def all_templates() -> list[ProcessTemplate]:
    return list(_CATALOG)


def get_template_by_id(template_id: str) -> ProcessTemplate | None:
    for t in _CATALOG:
        if t.id == template_id:
            return t
    return None


def resolve_permitted_families(*, compliant_enabled: bool, industry_module: str | None) -> list[str]:
    """Server-side policy: which template families a request may see.

    Never trusts a client-supplied tier/module — callers pass values already resolved
    from the org's own `ComplianceProfile`.
    """
    if not compliant_enabled or not industry_module:
        return []
    permitted = []
    for family, mapping in _FAMILY_CAPABILITY_MAP.items():
        if mapping["required_capability"] == "compliant" and industry_module in mapping["industry_modules"]:
            permitted.append(family)
    return permitted


def templates_for_families(families: list[str], family_filter: str | None = None) -> list[ProcessTemplate]:
    allowed = set(families)
    if family_filter is not None:
        allowed &= {family_filter}
    return [t for t in _CATALOG if t.family in allowed]


def get_permitted_template(template_id: str, families: list[str]) -> ProcessTemplate | None:
    t = get_template_by_id(template_id)
    if t is None or t.family not in set(families):
        return None
    return t


# ---------------------------------------------------------------------------------
# Distillery — full detail per docs/industry-process-templates-spec.md's Distillery table.
# ---------------------------------------------------------------------------------

register_template(
    ProcessTemplate(
        id="distillery_receive_ingredient_lot",
        family="distillery",
        name="Receive ingredient lot",
        description="Log a supplier delivery of a raw ingredient (botanicals, grain, sugar, etc.) as a traceable raw material lot.",
        traceability_shape="Supplier → raw material lot",
        category=ProcessCategory.OTHER,
        version=1,
        step_name="Receive ingredient lot",
        inputs=(),
        outputs=(TemplateOutput(name="Raw material lot", unit="kg"),),
        prompts=(
            TemplatePrompt(label="Supplier", type="text"),
            TemplatePrompt(label="Supplier batch", type="text"),
            TemplatePrompt(label="Expiry date", type="text", required=False),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="distillery_receive_neutral_spirit",
        family="distillery",
        name="Receive neutral spirit",
        description="Log a supplier delivery of neutral spirit as a traceable spirit lot.",
        traceability_shape="Supplier → spirit lot",
        category=ProcessCategory.OTHER,
        version=1,
        step_name="Receive neutral spirit",
        inputs=(),
        outputs=(TemplateOutput(name="Spirit lot", unit="L"),),
        prompts=(
            TemplatePrompt(label="Supplier batch", type="text"),
            TemplatePrompt(label="ABV", type="number", unit="%"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="distillery_flavour_botanical_preparation",
        family="distillery",
        name="Flavour or botanical preparation",
        description="Prepare a flavour or botanical intermediate from ingredient and/or spirit lots.",
        traceability_shape="ingredient/spirit lots → flavour intermediate",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Flavour or botanical preparation",
        inputs=(TemplateInput(name="Ingredient or spirit lot", unit="kg"),),
        outputs=(TemplateOutput(name="Flavour intermediate", unit="L"),),
        prompts=(
            TemplatePrompt(label="Trial / batch ID", type="text"),
            TemplatePrompt(label="Measured volume", type="number", unit="L"),
            TemplatePrompt(label="ABV", type="number", unit="%", required=False),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="distillery_distillation_run",
        family="distillery",
        name="Distillation run",
        description="Run a distillation batch from spirit and/or flavour inputs to a distillate.",
        traceability_shape="spirit/flavour inputs → distillate",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Distillation run",
        inputs=(TemplateInput(name="Spirit or flavour intermediate", unit="L"),),
        outputs=(TemplateOutput(name="Distillate", unit="L"),),
        prompts=(
            TemplatePrompt(label="Run ID", type="text"),
            TemplatePrompt(label="Input ABV", type="number", unit="%"),
            TemplatePrompt(label="Output ABV", type="number", unit="%"),
            TemplatePrompt(label="Yield", type="number", unit="L"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="distillery_blend_or_vat",
        family="distillery",
        name="Blend or vat",
        description="Blend distillate/spirit intermediates into a vat batch.",
        traceability_shape="intermediates → vat batch",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Blend or vat",
        inputs=(TemplateInput(name="Distillate or spirit intermediate", unit="L"),),
        outputs=(TemplateOutput(name="Vat batch", unit="L"),),
        prompts=(
            TemplatePrompt(label="Vat ID", type="text"),
            TemplatePrompt(label="ABV", type="number", unit="%"),
            TemplatePrompt(label="Volume", type="number", unit="L"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="distillery_bottling_run",
        family="distillery",
        name="Bottling run",
        description="Package a vat batch and packaging materials into a finished bottle batch.",
        traceability_shape="vat batch + packaging → finished bottle batch",
        category=ProcessCategory.PACKAGING,
        version=1,
        step_name="Bottling run",
        inputs=(
            TemplateInput(name="Vat batch", unit="L"),
            TemplateInput(name="Packaging materials", unit="units"),
        ),
        outputs=(TemplateOutput(name="Finished bottle batch", unit="units"),),
        prompts=(
            TemplatePrompt(label="Bottle batch", type="text"),
            TemplatePrompt(label="Bottle size", type="number", unit="mL"),
            TemplatePrompt(label="ABV", type="number", unit="%"),
            TemplatePrompt(label="Bottles produced", type="number", unit="units"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="distillery_rd_trial_and_sampling",
        family="distillery",
        name="R&D trial and sampling",
        description="Run an R&D trial or draw a QA sample from selected inputs. Output is always work-in-progress, never saleable stock, until run through a separate packaging template.",
        traceability_shape="selected inputs → trial intermediate / sample record",
        category=ProcessCategory.OTHER,
        version=1,
        step_name="R&D trial and sampling",
        inputs=(TemplateInput(name="Selected input lot", unit="L"),),
        outputs=(TemplateOutput(name="Trial intermediate / sample record", unit="mL", sample_only=True),),
        prompts=(
            TemplatePrompt(label="Experiment ID", type="text"),
            TemplatePrompt(label="Hypothesis", type="text", required=False),
            TemplatePrompt(label="Measured result", type="text"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="distillery_controlled_area_stock_transfer",
        family="distillery",
        name="Controlled-area stock transfer",
        description="Record a finished batch's transfer between storage locations or controlled areas.",
        traceability_shape="finished batch → storage/transfer record",
        category=ProcessCategory.OTHER,
        version=1,
        step_name="Controlled-area stock transfer",
        inputs=(TemplateInput(name="Finished batch", unit="units"),),
        outputs=(TemplateOutput(name="Storage/transfer record", unit="units"),),
        prompts=(
            TemplatePrompt(label="Source location", type="text"),
            TemplatePrompt(label="Destination location", type="text"),
            TemplatePrompt(label="Reference", type="text", required=False),
            TemplatePrompt(label="Quantity", type="number", unit="units"),
        ),
    )
)

# ---------------------------------------------------------------------------------
# Brewery — PRD names shape only; prompts/units authored by domain analogy to the
# Distillery family's fidelity (see SPEC's ASSUMPTION on this).
# ---------------------------------------------------------------------------------

register_template(
    ProcessTemplate(
        id="brewery_receive_raw_lot",
        family="brewery",
        name="Receive malt, hops, yeast or adjunct lot",
        description="Log a supplier delivery of malt, hops, yeast or an adjunct as a traceable raw material lot.",
        traceability_shape="supplier → raw material lot",
        category=ProcessCategory.OTHER,
        version=1,
        step_name="Receive raw material lot",
        inputs=(),
        outputs=(TemplateOutput(name="Raw material lot", unit="kg"),),
        prompts=(
            TemplatePrompt(label="Supplier", type="text"),
            TemplatePrompt(label="Supplier batch", type="text"),
            TemplatePrompt(label="Expiry date", type="text", required=False),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="brewery_brew_day",
        family="brewery",
        name="Brew day",
        description="Mash and boil raw lots into a wort batch.",
        traceability_shape="raw lots → wort batch",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Brew day",
        inputs=(TemplateInput(name="Raw material lot", unit="kg"),),
        outputs=(TemplateOutput(name="Wort batch", unit="L"),),
        prompts=(
            TemplatePrompt(label="Batch ID", type="text"),
            TemplatePrompt(label="Original gravity", type="number"),
            TemplatePrompt(label="Volume", type="number", unit="L"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="brewery_fermentation",
        family="brewery",
        name="Fermentation",
        description="Ferment wort and yeast into a beer batch.",
        traceability_shape="wort + yeast → beer batch",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Fermentation",
        inputs=(
            TemplateInput(name="Wort batch", unit="L"),
            TemplateInput(name="Yeast lot", unit="kg"),
        ),
        outputs=(TemplateOutput(name="Beer batch", unit="L"),),
        prompts=(
            TemplatePrompt(label="Fermentation vessel", type="text"),
            TemplatePrompt(label="Final gravity", type="number"),
            TemplatePrompt(label="ABV", type="number", unit="%"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="brewery_conditioning_blending",
        family="brewery",
        name="Conditioning / blending",
        description="Condition or blend beer batches into a conditioned batch.",
        traceability_shape="beer batches → conditioned batch",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Conditioning / blending",
        inputs=(TemplateInput(name="Beer batch", unit="L"),),
        outputs=(TemplateOutput(name="Conditioned batch", unit="L"),),
        prompts=(
            TemplatePrompt(label="Batch ID", type="text"),
            TemplatePrompt(label="Volume", type="number", unit="L"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="brewery_packaging_run",
        family="brewery",
        name="Packaging run",
        description="Package a conditioned batch and packaging materials into a finished pack batch.",
        traceability_shape="conditioned batch + packaging → finished pack batch",
        category=ProcessCategory.PACKAGING,
        version=1,
        step_name="Packaging run",
        inputs=(
            TemplateInput(name="Conditioned batch", unit="L"),
            TemplateInput(name="Packaging materials", unit="units"),
        ),
        outputs=(TemplateOutput(name="Finished pack batch", unit="units"),),
        prompts=(
            TemplatePrompt(label="Pack batch", type="text"),
            TemplatePrompt(label="Pack format", type="text"),
            TemplatePrompt(label="Units produced", type="number", unit="units"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="brewery_qa_sample_trial",
        family="brewery",
        name="QA sample / trial",
        description="Draw a QA sample or run a trial from a selected batch. Output is always work-in-progress, never saleable stock.",
        traceability_shape="selected batch → sample record",
        category=ProcessCategory.OTHER,
        version=1,
        step_name="QA sample / trial",
        inputs=(TemplateInput(name="Selected batch", unit="L"),),
        outputs=(TemplateOutput(name="Sample record", unit="mL", sample_only=True),),
        prompts=(
            TemplatePrompt(label="Sample ID", type="text"),
            TemplatePrompt(label="Measured result", type="text"),
        ),
    )
)

# ---------------------------------------------------------------------------------
# Winery / Vineyard — PRD names shape only; prompts/units authored by domain analogy.
# ---------------------------------------------------------------------------------

register_template(
    ProcessTemplate(
        id="winery_grape_intake",
        family="winery_vineyard",
        name="Grape intake",
        description="Log grapes received from a vineyard block or supplier as a traceable grape lot.",
        traceability_shape="vineyard/block or supplier → grape lot",
        category=ProcessCategory.OTHER,
        version=1,
        step_name="Grape intake",
        inputs=(),
        outputs=(TemplateOutput(name="Grape lot", unit="kg"),),
        prompts=(
            TemplatePrompt(label="Vineyard / block or supplier", type="text"),
            TemplatePrompt(label="Variety", type="text"),
            TemplatePrompt(label="Brix", type="number", required=False),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="winery_crush_and_press",
        family="winery_vineyard",
        name="Crush and press",
        description="Crush and press a grape lot into a juice/must batch.",
        traceability_shape="grape lot → juice/must batch",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Crush and press",
        inputs=(TemplateInput(name="Grape lot", unit="kg"),),
        outputs=(TemplateOutput(name="Juice/must batch", unit="L"),),
        prompts=(
            TemplatePrompt(label="Batch ID", type="text"),
            TemplatePrompt(label="Volume", type="number", unit="L"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="winery_fermentation",
        family="winery_vineyard",
        name="Fermentation",
        description="Ferment must and additions into a wine batch.",
        traceability_shape="must + additions → wine batch",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Fermentation",
        inputs=(
            TemplateInput(name="Juice/must batch", unit="L"),
            TemplateInput(name="Additions (yeast/nutrients)", unit="kg", requires_inventory_selection=False),
        ),
        outputs=(TemplateOutput(name="Wine batch", unit="L"),),
        prompts=(
            TemplatePrompt(label="Vessel", type="text"),
            TemplatePrompt(label="Final gravity", type="number", required=False),
            TemplatePrompt(label="ABV", type="number", unit="%"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="winery_racking_blending_stabilisation",
        family="winery_vineyard",
        name="Racking, blending or stabilisation",
        description="Rack, blend or stabilise wine batches into a cellar batch.",
        traceability_shape="wine batches → cellar batch",
        category=ProcessCategory.MANUFACTURING,
        version=1,
        step_name="Racking, blending or stabilisation",
        inputs=(TemplateInput(name="Wine batch", unit="L"),),
        outputs=(TemplateOutput(name="Cellar batch", unit="L"),),
        prompts=(
            TemplatePrompt(label="Batch ID", type="text"),
            TemplatePrompt(label="Volume", type="number", unit="L"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="winery_bottling_run",
        family="winery_vineyard",
        name="Bottling run",
        description="Package a cellar batch and packaging materials into a finished wine batch.",
        traceability_shape="cellar batch + packaging → finished wine batch",
        category=ProcessCategory.PACKAGING,
        version=1,
        step_name="Bottling run",
        inputs=(
            TemplateInput(name="Cellar batch", unit="L"),
            TemplateInput(name="Packaging materials", unit="units"),
        ),
        outputs=(TemplateOutput(name="Finished wine batch", unit="units"),),
        prompts=(
            TemplatePrompt(label="Bottle batch", type="text"),
            TemplatePrompt(label="Bottle size", type="number", unit="mL"),
            TemplatePrompt(label="Bottles produced", type="number", unit="units"),
        ),
    )
)

register_template(
    ProcessTemplate(
        id="winery_trial_or_qa_sample",
        family="winery_vineyard",
        name="Vineyard/block trial or QA sample",
        description="Draw a QA sample or run a trial from a selected lot. Output is always work-in-progress, never saleable stock.",
        traceability_shape="selected lot → sample record",
        category=ProcessCategory.OTHER,
        version=1,
        step_name="Vineyard/block trial or QA sample",
        inputs=(TemplateInput(name="Selected lot", unit="L"),),
        outputs=(TemplateOutput(name="Sample record", unit="mL", sample_only=True),),
        prompts=(
            TemplatePrompt(label="Sample ID", type="text"),
            TemplatePrompt(label="Measured result", type="text"),
        ),
    )
)
