"""NZ Alcohol framework catalogue and control-level capture contracts."""

from app.features.compliant.modules.nz_alcohol.councils import council_catalogue

NZ_ALCOHOL_FRAMEWORKS = (
    {
        "slug": "customs-alcohol",
        "name": "Customs alcohol reconciliation",
        "version": "2026.1",
        "source_title": "New Zealand Customs Service — alcohol LMA and off-site storage record keeping",
        "source_url": "https://www.customs.govt.nz/business/excise/alcohol-and-excise/record-keeping-obligations-for-alcohol-licenced-manufacturing-areas-and-off-site-storage",
        "applies_to": "all_alcohol",
        "controls": (
            ("product-mapping", "Map every alcohol product to its Customs classification and litres of alcohol basis."),
            ("period-lodgement", "Record each lodgement period and attach the filed lodgement reference."),
            ("reconciliation", "Review production, stock, wastage and sales movements for the filing period."),
            (
                "movement-evidence",
                "Retain dispatch, delivery and inter-CCA movement evidence for alcohol leaving or entering controlled areas.",
            ),
            (
                "record-retention",
                "Confirm seven-year record retention and New Zealand storage or Customs approval for offshore storage.",
            ),
        ),
    },
    {
        "slug": "np3-food-control",
        "name": "National Programme 3 food control",
        "version": "2025-v2",
        "source_title": "Ministry for Primary Industries — National Programme 3 Guidance (December 2025, version 2)",
        "source_url": "https://www.mpi.govt.nz/dmsdocument/21853/direct",
        "applies_to": ("national-programme-3", "beer", "spirits", "cider", "mead", "rtd", "other"),
        "controls": (
            ("registration-scope", "Keep the registered business scope, verifier and material changes current."),
            ("operational-verification", "Record the required operational and verification checks."),
            ("staff-competency", "Keep current staff training and competency evidence."),
            (
                "cleaning-and-hygiene",
                "Record cleaning, sanitising, maintenance and hygiene verification relevant to the operation.",
            ),
            ("trace-and-recall", "Prove traceability and retain mock-recall or recall evidence."),
            ("corrective-actions", "Close food-safety incidents and corrective actions with evidence."),
            (
                "documentation-record-keeping",
                "Make the current National Programme guidance and the last 12 months of relevant records available.",
            ),
            (
                "delegation",
                "Record who is delegated to carry out food-safety responsibilities and how they are supported.",
            ),
            (
                "operator-verification",
                "Retain previous verification outcomes and evidence that required follow-up has been completed.",
            ),
            ("personal-hygiene", "Show the team follows the hygiene and behaviour controls relevant to the operation."),
            ("health-and-sickness", "Keep staff illness and exclusion decisions where they affect food safety."),
            ("food-standards-composition", "Keep ingredient, composition and applicable Food Standards Code evidence."),
            ("food-standards-microbiological", "Keep microbiological controls or test results where they apply."),
            (
                "time-temperature-processing",
                "Keep time and temperature records for cooking or processing where they apply.",
            ),
            ("cross-contamination", "Show controls that prevent cross contamination."),
            ("equipment-design", "Show food-contact equipment is suitable, maintained and used appropriately."),
            ("suppliers-and-purchasing", "Keep approved supplier and purchasing evidence."),
            ("receiving-food", "Keep receiving checks for ingredients and other food inputs."),
            ("allergen-management", "Keep allergen identification, segregation and labelling controls."),
            ("cooking-poultry", "Keep cooking-poultry control records where they apply."),
            ("defrosting-reheating", "Keep defrosting and reheating control records where they apply."),
            ("storage-stock-rotation", "Keep storage conditions and stock-rotation evidence."),
            ("cooling-freezing", "Keep cooling and freezing controls where they apply."),
            ("display-temperature", "Keep time and temperature controls for food on display where they apply."),
            ("calibration", "Keep calibration records for measuring equipment used for food safety."),
            ("transporting-food", "Keep controls for safe transport where it applies."),
            ("food-labelling-advertising", "Keep current retail label and advertising examples for verification."),
            ("biological-hazards", "Show process controls for biological hazards where they apply."),
            ("chemical-hazards", "Show process controls for chemical hazards where they apply."),
            ("physical-hazards", "Show process controls for physical hazards where they apply."),
            ("importing-food", "Keep food-importing records where it applies."),
            ("pest-animal-control", "Keep pest and animal-control checks and contractor records."),
            ("waste-management", "Keep waste-management controls relevant to the premises."),
            (
                "premises-services",
                "Show the premises, facilities and essential services support safe food production.",
            ),
            ("water-supply", "Keep water-supply controls and any relevant records."),
            ("maintenance", "Keep maintenance evidence for food-safety-critical areas and equipment."),
            ("unsafe-unsuitable-food", "Show how unsafe or unsuitable food is identified, isolated and managed."),
        ),
    },
    {
        "slug": "np2-food-control",
        "name": "National Programme 2 food control",
        "version": "2025 guidance",
        "source_title": "Ministry for Primary Industries — National Programme 2 guidance",
        "source_url": "https://www.mpi.govt.nz/food-business/running-a-food-business/national-programmes",
        "applies_to": ("national-programme-2", "beer", "spirits", "cider", "mead", "rtd", "other"),
        "controls": (
            ("registration-scope", "Keep the registered business scope, verifier and material changes current."),
            (
                "operational-verification",
                "Record the operating checks and verification evidence required for your selected programme.",
            ),
            ("staff-competency", "Keep current staff training and competency evidence."),
            ("cleaning-and-hygiene", "Record cleaning, maintenance and hygiene checks relevant to the operation."),
            ("trace-and-recall", "Prove traceability and retain mock-recall or recall evidence."),
            ("corrective-actions", "Close food-safety incidents and corrective actions with evidence."),
        ),
    },
    {
        "slug": "np1-food-control",
        "name": "National Programme 1 food control",
        "version": "2025 guidance",
        "source_title": "Ministry for Primary Industries — National Programme 1 guidance",
        "source_url": "https://www.mpi.govt.nz/food-business/running-a-food-business/national-programmes",
        "applies_to": ("national-programme-1", "beer", "spirits", "cider", "mead", "rtd", "other"),
        "controls": (
            ("registration-scope", "Keep the registered business scope, verifier and material changes current."),
            (
                "operational-verification",
                "Record the operating checks and verification evidence required for your selected programme.",
            ),
            ("staff-competency", "Keep current staff training and competency evidence."),
            ("trace-and-recall", "Prove traceability and retain mock-recall or recall evidence."),
            ("corrective-actions", "Close food-safety incidents and corrective actions with evidence."),
        ),
    },
    {
        "slug": "liquor-licence",
        "name": "Alcohol licence obligations",
        "version": "Sale and Supply of Alcohol Act 2012 — local conditions apply",
        "source_title": "Alcohol.org.nz — alcohol licensing guidance",
        "source_url": "https://resources.alcohol.org.nz/alcohol-management-laws/licensing-local-policies/alcohol-licensing",
        "applies_to": "liquor-licence-required",
        "controls": (
            (
                "licence-scope",
                "Record the licence type, premises or event scope, District Licensing Committee and licence reference.",
            ),
            (
                "licence-conditions",
                "Keep the current licence conditions and the operating arrangements that meet them.",
            ),
            ("certified-manager", "Keep evidence that the required certified manager arrangements are in place."),
            ("licence-renewal", "Track the licence renewal date or, for a special licence, the event date and scope."),
            (
                "service-practices",
                "Keep training and incident evidence for age, intoxication and responsible-service controls.",
            ),
        ),
    },
    {
        "slug": "wine-standards",
        "name": "Wine Standards Management Plan",
        "version": "wine-act-current",
        "source_title": "Ministry for Primary Industries — Wine Standards Management Plans",
        "source_url": "https://www.mpi.govt.nz/food-business/winemaking-standards-requirements-and-testing/wine-standards-management-plans",
        "applies_to": ("wine",),
        "controls": (
            ("wsmp-registration", "Record the registered Wine Standards Management Plan, scope and verifier."),
            ("wine-risk-controls", "Record the plan's risk controls and verification evidence for winemaking."),
            ("wine-trace-and-recall", "Maintain traceability, recall and corrective-action evidence for wine."),
            ("wine-returns", "Record required Wine Act records, returns and export evidence where applicable."),
        ),
    },
    {
        "slug": "trade-waste",
        "name": "Council trade waste",
        "version": "council-specific",
        "source_title": "Council trade-waste consent and bylaw",
        "source_url": "",
        "applies_to": "consent_required",
        "controls": (
            ("consent-profile", "Record the applicable council, consent reference and conditions."),
            ("management-plan", "Maintain the site trade-waste management plan where required."),
            ("pre-treatment", "Record required pre-treatment, servicing and inspection evidence."),
            ("monitoring", "Record required discharge monitoring and sample results."),
            ("renewal", "Track consent or agreement expiry and renewal."),
            ("incidents", "Record and resolve trade-waste incidents and corrective actions."),
        ),
    },
)

CONTROL_REQUIREMENTS = {
    ("customs-alcohol", "period-lodgement"): {"record_types": ("lodgement",), "period": True, "evidence": True},
    ("customs-alcohol", "reconciliation"): {
        "record_types": ("reading", "attestation"),
        "period": True,
        "evidence": True,
        "fields": ("declared_litres_of_alcohol",),
    },
    ("customs-alcohol", "movement-evidence"): {"evidence": True, "source_refs": True},
    ("customs-alcohol", "record-retention"): {"evidence": True},
    ("np3-food-control", "staff-competency"): {"record_types": ("competency",), "evidence": True, "due_date": True},
    ("np3-food-control", "operational-verification"): {"evidence": True},
    ("np3-food-control", "cleaning-and-hygiene"): {"evidence": True},
    ("np3-food-control", "trace-and-recall"): {"evidence": True, "source_refs": True},
    ("wine-standards", "wsmp-registration"): {"evidence": True},
    ("wine-standards", "wine-trace-and-recall"): {"evidence": True, "source_refs": True},
    ("trade-waste", "consent-profile"): {"evidence": True},
    ("trade-waste", "monitoring"): {
        "record_types": ("reading",),
        "evidence": True,
        "fields": ("measured_value", "limit_value"),
    },
    ("trade-waste", "pre-treatment"): {"evidence": True},
    ("np2-food-control", "staff-competency"): {"record_types": ("competency",), "evidence": True, "due_date": True},
    ("np1-food-control", "staff-competency"): {"record_types": ("competency",), "evidence": True, "due_date": True},
    ("liquor-licence", "licence-scope"): {"evidence": True},
    ("liquor-licence", "licence-conditions"): {"evidence": True},
    ("liquor-licence", "certified-manager"): {"record_types": ("competency",), "evidence": True, "due_date": True},
    ("liquor-licence", "licence-renewal"): {"evidence": True, "due_date": True},
    ("liquor-licence", "service-practices"): {"evidence": True},
}


def framework_by_slug(slug: str) -> dict | None:
    return next((framework for framework in NZ_ALCOHOL_FRAMEWORKS if framework["slug"] == slug), None)


def capture_requirements(framework_slug: str, control_id: str, profile_settings: dict | None = None) -> dict:
    requirements = dict(CONTROL_REQUIREMENTS.get((framework_slug, control_id), {}))
    if (profile_settings or {}).get("require_core_source_refs"):
        requirements["source_refs"] = True
    return requirements


def framework_applies(
    applies_to: str | tuple[str, ...], profile_settings: dict | None, trade_waste_consent_reference: str | None
) -> bool:
    """Single source of truth for whether a framework applies to a profile.

    Mirrors the filter ComplianceService.evaluate() runs per framework, so a caller that
    only needs a yes/no answer (e.g. rejecting an inapplicable audit-pack request) can get
    one without evaluating every control or touching the database.
    """
    if applies_to == "consent_required":
        return bool(trade_waste_consent_reference or (profile_settings or {}).get("trade_waste_required"))
    if isinstance(applies_to, tuple) and applies_to[0].startswith("national-programme-"):
        # Existing organisations predate this setting and were built around NP3, so the
        # absent value deliberately preserves that plan until an administrator chooses.
        selected = (profile_settings or {}).get("food_control_programme", "np3")
        product_types = set((profile_settings or {}).get("alcohol_product_types") or [])
        return selected == f"np{applies_to[0].removeprefix('national-programme-')}" and (
            not product_types or bool(product_types.intersection(applies_to[1:]))
        )
    if applies_to == "liquor-licence-required":
        return bool((profile_settings or {}).get("liquor_licence_types"))
    if isinstance(applies_to, tuple):
        product_types = set((profile_settings or {}).get("alcohol_product_types") or [])
        return not product_types or bool(product_types.intersection(applies_to))
    return True


def framework_for_profile(framework: dict, profile_settings: dict | None) -> dict:
    """Bind the trade-waste pack to the selected authority's current catalogue."""
    if framework["slug"] != "trade-waste":
        return framework
    catalogue = council_catalogue((profile_settings or {}).get("trade_waste_council"))
    if catalogue is None:
        return framework
    bound = dict(framework)
    bound.update({key: catalogue[key] for key in ("version", "source_title", "source_url", "controls")})
    return bound
