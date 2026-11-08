"""What a compliance module wants people to know about each site and stock area (GL-P07 A2).

Core's Sites page asks for notes about the organisation's sites; the installed module answers in
plain words with a link to where it is managed. Core never names a module: with no compliance
profile, or a module without notes, every site simply has none.

A note is ``{"text": str, "short": str, "tone": "ok" | "warn" | "neutral", "href": str | None}``;
``short`` fits a table cell. The module also names its column (``label``) and may add a setup
step (``step``: title, done, detail, href, href_label), so core's wording never names a regime.
"""

from datetime import date
from typing import Protocol

from app.features.compliant.models.compliance_profile import ComplianceProfile


class SiteNotesProvider(Protocol):
    module_id: str

    def notes(self, session, org_id, sites, areas, today: date) -> dict: ...


def _providers():
    from app.features.compliant.modules.nz_alcohol.site_notes import NZAlcoholSiteNotes

    return (NZAlcoholSiteNotes(),)


def site_notes(session, org_id, sites, areas, today: date | None = None) -> dict:
    """``{"sites": {site_id: [note]}, "areas": {location_id: note}, "label": str | None,
    "step": dict | None}`` for the given rows."""
    empty = {"sites": {}, "areas": {}, "label": None, "step": None}
    profile = session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
    if profile is None or not profile.enabled:
        return empty
    provider = next((p for p in _providers() if p.module_id == profile.industry_module), None)
    if provider is None:
        return empty
    return provider.notes(session, org_id, sites, areas, today or date.today())
