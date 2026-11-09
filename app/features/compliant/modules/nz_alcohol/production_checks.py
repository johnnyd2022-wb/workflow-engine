"""NZ alcohol: making alcohol at a site needs a food registration that covers manufacturing there
on that day (Food Act 2014; the record kept under Compliance, Food registrations)."""

from datetime import date

from app.features.compliant.modules.nz_alcohol.food_registrations import covers_activity


class NZAlcoholProductionChecks:
    module_id = "nz_alcohol"

    def start_blockers(self, session, org_id, site, on: date) -> list[str]:
        if site is None:
            return ["Add your site under Settings, Sites, so its food registration can be checked"]
        if covers_activity(session, org_id, site.id, "manufacturing", on):
            return []
        return [
            f"No food registration covers manufacturing at {site.name} on {on.day} {on:%b}; "
            "record it under Compliance, Food registrations"
        ]
