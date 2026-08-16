"""Current, source-linked council trade-waste catalogues.

The catalogue deliberately captures operational controls, not universal discharge limits.
Limits and sampling frequency are consent-specific and must be configured from the
customer's consent; presenting a generic limit as law would make the product less safe.
"""

TRADE_WASTE_CATALOGUES = {
    "auckland-watercare": {
        "name": "Auckland / Watercare",
        "version": "Trade Waste Control 2019; agreement guidance checked 2026-08-16",
        "source_title": "Watercare — Trade waste agreements and management-plan resources",
        "source_url": "https://www.watercare.co.nz/business/help-and-support/trade-waste/trade-waste-agreements",
        "controls": (
            ("consent-profile", "Classify the discharge and retain the trade-waste agreement or low-risk basis."),
            ("management-plan", "Maintain the management plan identifying site risks and mitigations."),
            ("pre-treatment", "Record required pre-treatment, inspection and servicing evidence."),
            ("monitoring", "Record agreement-specified monitoring, sampling and discharge results."),
            ("renewal", "Renew the fixed-term agreement and management plan before expiry."),
            ("incidents", "Record spills, abnormal discharges and corrective actions."),
        ),
    },
    "wellington-city": {
        "name": "Wellington City",
        "version": "Trade Waste Bylaw 2016; source checked 2026-08-16",
        "source_title": "Wellington City Council — Trade Waste Bylaw 2016",
        "source_url": "https://wellington.govt.nz/-/media/your-council/plans-policies-and-bylaws/bylaws/files/trade-waste-bylaw-2016.pdf",
        "controls": (
            ("consent-profile", "Retain the trade-waste discharge consent and its operating conditions."),
            ("pre-treatment", "Maintain consented screens, traps or other pre-treatment works."),
            ("monitoring", "Record required sampling, analysis, flow measurement and meter certification."),
            ("renewal", "Track the consent term, renewal and changes to discharge characteristics."),
            ("incidents", "Record and rectify any discharge incident or consent non-conformance."),
        ),
    },
    "christchurch": {
        "name": "Christchurch City",
        "version": "Trade Waste Bylaw 2025 (effective 1 July 2025)",
        "source_title": "Christchurch City Council — Trade Waste Bylaw 2025",
        "source_url": "https://ccc.govt.nz/assets/Documents/The-Council/Plans-Strategies-Policies-Bylaws/Bylaws/Trade-Waste-Bylaw-2025.pdf",
        "controls": (
            (
                "consent-profile",
                "Confirm permitted, conditional, tankered or prohibited classification and consent conditions.",
            ),
            ("management-plan", "Maintain the required site management plan where the consent requires it."),
            ("pre-treatment", "Record maintenance of pretreatment, flow meters, samplers or measuring devices."),
            ("monitoring", "Record monitoring evidence against the consent's discharge criteria."),
            ("incidents", "Keep spill prevention and corrective-action evidence."),
        ),
    },
    "hamilton": {
        "name": "Hamilton City",
        "version": "Trade Waste and Wastewater Bylaw 2016 (amended 2023)",
        "source_title": "Hamilton City Council — trade-waste consent requirements",
        "source_url": "https://hamilton.govt.nz/property-rates-and-building/water-services/trade-waste-applications/",
        "controls": (
            ("consent-profile", "Retain the consent, discharge characteristics and applicable conditions."),
            (
                "management-plan",
                "Retain any management plan or independently qualified report required for the application.",
            ),
            ("pre-treatment", "Record installed pre-treatment and required servicing."),
            ("monitoring", "Record consent-specified substance, volume and monitoring evidence."),
            ("incidents", "Record discharge changes, incidents and corrective actions."),
        ),
    },
    "dunedin": {
        "name": "Dunedin City",
        "version": "Trade Waste Bylaw 2020; guidance checked 2026-08-16",
        "source_title": "Dunedin City Council — Trade waste consent and category guidance",
        "source_url": "https://www.dunedin.govt.nz/services/wastewater/tradewaste",
        "controls": (
            ("consent-profile", "Record the consent or permitted-discharge registration and approval."),
            ("pre-treatment", "Maintain any required pre-treatment and retain servicing evidence."),
            ("monitoring", "Record inspections, sampling and consent-specific monitoring results."),
            ("renewal", "Track consent expiry, re-issue and discharge changes."),
            ("incidents", "Record organic-waste, spill or other discharge incidents and corrections."),
        ),
    },
}


def council_catalogue(slug: str | None) -> dict | None:
    return TRADE_WASTE_CATALOGUES.get(slug or "")
