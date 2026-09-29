"""Starter packs: a complete workflow per producer type, with its compliance fields (plan 2.4c).

A pack is a whole workflow (receive → make → package) whose steps pass their output to the
next step, unlike the single-step templates in ``registry``. Applying a pack also asks the
installed compliance module to preconfigure what that product type needs (e.g. ABV on the
final product, the product type's frameworks), through ``compliant.platform.presets``.

Like the templates, packs accelerate setup; they aren't legal or food-safety advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.features.process_templates.catalog.registry import TemplateInput, TemplateOutput, TemplatePrompt


@dataclass(frozen=True)
class PackStep:
    name: str
    description: str
    output: TemplateOutput
    inputs: tuple[TemplateInput, ...] = ()  # raw inputs picked from stock
    takes_previous: bool = True  # consumes the previous step's output
    prompts: tuple[TemplatePrompt, ...] = ()


@dataclass(frozen=True)
class StarterPack:
    id: str
    product_type: str  # matches the compliance profile's alcohol_product_types
    family: str  # template family that gates who can see it
    name: str
    description: str
    steps: tuple[PackStep, ...]
    key_checks: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (check id, why)

    @property
    def final_output(self) -> str:
        return self.steps[-1].output.name


_SUPPLIER = (TemplatePrompt(label="Supplier", type="text"), TemplatePrompt(label="Supplier batch", type="text"))
_PACKAGING = TemplateInput(name="Packaging materials", unit="units")
_LABEL = "the label shows ABV, standard drinks and, above 1.15% ABV, the pregnancy warning"


STARTER_PACKS: tuple[StarterPack, ...] = (
    StarterPack(
        id="spirits",
        product_type="spirits",
        family="distillery",
        name="Spirit: receive to bottle",
        description="Botanicals and neutral spirit in, distillation or maceration, blend and proof, bottle.",
        steps=(
            PackStep(
                "Receive ingredients",
                "Log botanicals, grain or neutral spirit as supplier lots.",
                TemplateOutput("Ingredient lot", "kg"),
                takes_previous=False,
                prompts=_SUPPLIER,
            ),
            PackStep(
                "Distil or macerate",
                "Run the still or macerate; record the cuts you kept.",
                TemplateOutput("Distillate", "L"),
                inputs=(TemplateInput("Neutral spirit", "L"),),
                prompts=(TemplatePrompt("Still run or maceration reference", "text"),),
            ),
            PackStep(
                "Blend and proof",
                "Blend and dilute to bottling strength.",
                TemplateOutput("Proofed spirit", "L"),
                inputs=(TemplateInput("Water", "L", requires_inventory_selection=False),),
                prompts=(TemplatePrompt("Volume after proofing", "number", unit="L"),),
            ),
            PackStep(
                "Bottle",
                "Fill, cap and label. ABV is asked for here.",
                TemplateOutput("Bottled spirit", "units"),
                inputs=(_PACKAGING,),
            ),
        ),
        key_checks=(
            ("chemical-hazards", "methanol and heads cuts; cleaning chemicals near product"),
            ("suppliers-and-purchasing", "botanicals and neutral spirit from known suppliers"),
            ("food-labelling-advertising", _LABEL),
            ("trace-and-recall", "every bottle traces back to its still run and supplier lots"),
        ),
    ),
    StarterPack(
        id="beer",
        product_type="beer",
        family="brewery",
        name="Beer: brew to package",
        description="Malt, hops and yeast in, brew day, ferment, condition, package.",
        steps=(
            PackStep(
                "Receive malt, hops and yeast",
                "Log raw materials as supplier lots.",
                TemplateOutput("Raw material lot", "kg"),
                takes_previous=False,
                prompts=_SUPPLIER,
            ),
            PackStep(
                "Brew day",
                "Mash, boil and knock out to the fermenter.",
                TemplateOutput("Wort", "L"),
                prompts=(TemplatePrompt("Original gravity", "number"),),
            ),
            PackStep(
                "Ferment",
                "Ferment to terminal gravity.",
                TemplateOutput("Green beer", "L"),
                inputs=(TemplateInput("Yeast", "kg"),),
                prompts=(TemplatePrompt("Final gravity", "number"),),
            ),
            PackStep(
                "Condition",
                "Condition, carbonate and clarify.",
                TemplateOutput("Bright beer", "L"),
            ),
            PackStep(
                "Package",
                "Can, bottle or keg. ABV is asked for here.",
                TemplateOutput("Packaged beer", "units"),
                inputs=(_PACKAGING,),
            ),
        ),
        key_checks=(
            ("allergen-management", "gluten (barley, wheat) declared on the label"),
            ("acidification-fermentation-control", "fermentation records show the brew stayed on track"),
            ("food-contact-equipment-cleaning", "fermenter, line and keg cleaning"),
            ("food-labelling-advertising", _LABEL),
        ),
    ),
    StarterPack(
        id="wine",
        product_type="wine",
        family="winery_vineyard",
        name="Wine: intake to bottle",
        description="Grape intake, crush and press, ferment, cellar, bottle.",
        steps=(
            PackStep(
                "Grape intake",
                "Log each grape delivery by block or grower.",
                TemplateOutput("Grape lot", "kg"),
                takes_previous=False,
                prompts=(TemplatePrompt("Vineyard or grower", "text"), TemplatePrompt("Brix at intake", "number")),
            ),
            PackStep("Crush and press", "Crush and press to juice or must.", TemplateOutput("Juice or must", "L")),
            PackStep(
                "Ferment",
                "Primary (and malolactic) fermentation.",
                TemplateOutput("Young wine", "L"),
                inputs=(TemplateInput("Additions (yeast, nutrients)", "kg", requires_inventory_selection=False),),
            ),
            PackStep(
                "Cellar",
                "Rack, blend, stabilise; record sulphite additions.",
                TemplateOutput("Finished wine", "L"),
                prompts=(TemplatePrompt("Free SO2", "number", unit="mg/L", required=False),),
            ),
            PackStep(
                "Bottle",
                "Fill, close and label. ABV is asked for here.",
                TemplateOutput("Bottled wine", "units"),
                inputs=(_PACKAGING,),
            ),
        ),
        key_checks=(
            ("allergen-management", "sulphites above 10 mg/kg declared on the label"),
            ("acidification-fermentation-control", "fermentation and stabilisation records"),
            ("food-labelling-advertising", _LABEL),
            ("trace-and-recall", "every bottle traces back to its grape lots"),
        ),
    ),
    StarterPack(
        id="cider",
        product_type="cider",
        family="winery_vineyard",
        name="Cider: fruit to package",
        description="Fruit or juice in, press, ferment, blend, package.",
        steps=(
            PackStep(
                "Receive fruit or juice",
                "Log each fruit or juice delivery as a supplier lot.",
                TemplateOutput("Fruit or juice lot", "kg"),
                takes_previous=False,
                prompts=_SUPPLIER,
            ),
            PackStep("Mill and press", "Mill and press to juice.", TemplateOutput("Juice", "L")),
            PackStep(
                "Ferment",
                "Ferment to dryness or the target gravity.",
                TemplateOutput("Cider base", "L"),
                inputs=(TemplateInput("Yeast", "kg"),),
                prompts=(TemplatePrompt("Final gravity", "number"),),
            ),
            PackStep(
                "Blend and back-sweeten",
                "Blend, sweeten and stabilise; record any pasteurisation.",
                TemplateOutput("Finished cider", "L"),
                prompts=(TemplatePrompt("Pasteurised or stabilised how", "text", required=False),),
            ),
            PackStep(
                "Package",
                "Can, bottle or keg. ABV is asked for here.",
                TemplateOutput("Packaged cider", "units"),
                inputs=(_PACKAGING,),
            ),
        ),
        key_checks=(
            ("acidification-fermentation-control", "fermentation records; refermentation risk if sweetened"),
            ("time-temperature-processing", "pasteurisation of sweetened cider, where used"),
            ("allergen-management", "sulphites declared where added"),
            ("food-labelling-advertising", _LABEL),
        ),
    ),
    StarterPack(
        id="mead",
        product_type="mead",
        family="winery_vineyard",
        name="Mead: honey to bottle",
        description="Honey in, must, ferment, age, bottle.",
        steps=(
            PackStep(
                "Receive honey",
                "Log each honey delivery as a supplier lot.",
                TemplateOutput("Honey lot", "kg"),
                takes_previous=False,
                prompts=_SUPPLIER,
            ),
            PackStep(
                "Make the must",
                "Dilute honey and add nutrients.",
                TemplateOutput("Must", "L"),
                inputs=(TemplateInput("Water", "L", requires_inventory_selection=False),),
                prompts=(TemplatePrompt("Original gravity", "number"),),
            ),
            PackStep(
                "Ferment",
                "Ferment with staggered nutrient additions.",
                TemplateOutput("Young mead", "L"),
                inputs=(TemplateInput("Yeast", "kg"),),
            ),
            PackStep("Age and clarify", "Age, rack and clarify.", TemplateOutput("Finished mead", "L")),
            PackStep(
                "Bottle",
                "Fill, close and label. ABV is asked for here.",
                TemplateOutput("Bottled mead", "units"),
                inputs=(_PACKAGING,),
            ),
        ),
        key_checks=(
            ("suppliers-and-purchasing", "honey from registered suppliers (tutin rules apply to honey)"),
            ("acidification-fermentation-control", "fermentation records"),
            ("food-labelling-advertising", _LABEL),
        ),
    ),
    StarterPack(
        id="rtd",
        product_type="rtd",
        family="distillery",
        name="RTD: spirit to can",
        description="Spirit base and mixers in, batch, carbonate, can.",
        steps=(
            PackStep(
                "Receive spirit base and ingredients",
                "Log spirit, flavours and sweeteners as supplier lots.",
                TemplateOutput("Ingredient lot", "kg"),
                takes_previous=False,
                prompts=_SUPPLIER,
            ),
            PackStep(
                "Batch",
                "Mix spirit, water and flavours to the recipe.",
                TemplateOutput("RTD batch", "L"),
                inputs=(TemplateInput("Water", "L", requires_inventory_selection=False),),
                prompts=(TemplatePrompt("Batch volume", "number", unit="L"),),
            ),
            PackStep(
                "Carbonate and fill",
                "Carbonate and can. ABV is asked for here.",
                TemplateOutput("Canned RTD", "units"),
                inputs=(_PACKAGING,),
                prompts=(TemplatePrompt("Pasteurised", "text", required=False),),
            ),
        ),
        key_checks=(
            ("allergen-management", "flavours and sweeteners checked for allergens"),
            ("time-temperature-processing", "tunnel pasteurisation, where used"),
            ("water-supply", "water used in the product is potable"),
            ("food-labelling-advertising", _LABEL),
        ),
    ),
)


def get_pack(pack_id: str) -> StarterPack | None:
    return next((p for p in STARTER_PACKS if p.id == pack_id), None)
