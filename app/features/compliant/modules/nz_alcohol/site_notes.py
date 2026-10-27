"""NZ Alcohol's notes for the Sites page: which sites and areas sit inside a Customs-licensed area.

Coverage is the Customs licences register (premises.py): a licence covers a site's main area
(no location) or one named stock area, for dated periods. A named area needs its own record;
anything outside a current licence holds duty-paid stock only.
"""

from sqlalchemy import or_

from app.features.compliant.models.customs_premises import CustomsCoverage, CustomsLicence
from app.features.compliant.modules.nz_alcohol.premises import KINDS

PREMISES = "/compliant/nz-alcohol/premises"


class NZAlcoholSiteNotes:
    module_id = "nz_alcohol"

    def notes(self, session, org_id, sites, areas, today):
        current = (
            session.query(CustomsCoverage, CustomsLicence)
            .join(
                CustomsLicence,
                (CustomsLicence.id == CustomsCoverage.licence_id) & (CustomsLicence.org_id == CustomsCoverage.org_id),
            )
            .filter(
                CustomsCoverage.org_id == org_id,
                CustomsCoverage.valid_from <= today,
                or_(CustomsCoverage.valid_until.is_(None), CustomsCoverage.valid_until >= today),
                CustomsLicence.valid_from <= today,
                or_(CustomsLicence.valid_until.is_(None), CustomsLicence.valid_until >= today),
            )
            .all()
        )
        by_site, by_area = {}, {}
        for coverage, licence in current:
            label = f"{KINDS.get(licence.kind, 'Licensed area')} {licence.number}"
            if coverage.location_id is None:
                by_site.setdefault(coverage.site_id, []).append(label)
            else:
                by_area[coverage.location_id] = label
        # A site-level record licenses the site's main area (stock not placed in a named area);
        # a named area is licensed only by a record of its own (premises.licence_for_area).
        site_notes, licensed = {}, []
        for site in sites:
            whole = by_site.get(site.id, [])
            own = [a for a in areas if a.site_id == site.id]
            parts = [a for a in own if a.id in by_area]
            numbers = sorted(set(whole) | {by_area[a.id] for a in parts})
            if numbers and len(parts) == len(own):
                note = {"text": "Customs-licensed: " + ", ".join(numbers), "short": "Licensed", "tone": "ok"}
            elif whole:
                note = {
                    "text": f"Customs-licensed main area ({', '.join(whole)}); {len(parts)} of its {len(own)} areas",
                    "short": f"Main area, {len(parts)} of {len(own)} areas",
                    "tone": "ok",
                }
            elif parts:
                note = {
                    "text": f"Customs-licensed: {len(parts)} of its {len(own)} areas",
                    "short": f"{len(parts)} of {len(own)} areas licensed",
                    "tone": "ok",
                }
            else:
                note = {
                    "text": "Not in a Customs-licensed area: duty-paid stock only",
                    "short": "Duty-paid",
                    "tone": "neutral",
                }
            if note["tone"] == "ok" and site.is_active:
                licensed.append(site.name)
            site_notes[str(site.id)] = [{**note, "href": PREMISES}]
        area_notes = {}
        for area in areas:
            licence = by_area.get(area.id)
            area_notes[str(area.id)] = (
                {"text": licence, "tone": "ok", "href": PREMISES}
                if licence
                else {"text": "Duty-paid", "tone": "neutral", "href": PREMISES}
            )
        if licensed:
            detail = (
                f"{', '.join(licensed)} {'is' if len(licensed) == 1 else 'are'} in a Customs-licensed area. "
                "Everywhere else holds duty-paid stock."
            )
        else:
            detail = "No site is in a Customs-licensed area yet. Register your licences so duty is worked out per area."
        return {
            "sites": site_notes,
            "areas": area_notes,
            "label": "Customs",
            "step": {
                "title": "Check which sites hold stock under bond",
                "done": bool(licensed),
                "detail": detail,
                "href": PREMISES,
                "href_label": "Customs licences and areas",
            },
        }
