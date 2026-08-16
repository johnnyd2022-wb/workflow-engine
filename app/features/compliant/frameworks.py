"""Versioned, source-linked NZ Alcohol framework catalogue.

This is intentionally a small, reviewed catalogue. It communicates operational evidence
status and must not be represented as legal advice or regulatory certification.
"""

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
        "applies_to": ("beer", "spirits", "cider", "mead", "rtd", "other"),
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
        "version": "2026.1",
        "source_title": "Council trade-waste consent and bylaw",
        "source_url": "",
        "applies_to": "consent_required",
        "controls": (
            ("consent-profile", "Record the applicable council, consent reference and conditions."),
            ("monitoring", "Record required discharge monitoring and sample results."),
            ("incidents", "Record and resolve trade-waste incidents and corrective actions."),
        ),
    },
)


def framework_by_slug(slug: str) -> dict | None:
    return next((framework for framework in NZ_ALCOHOL_FRAMEWORKS if framework["slug"] == slug), None)
