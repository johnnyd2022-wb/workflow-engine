"""Whether a place is inside a licensed area, as the installed compliance module decides it
(GL-P07 A5).

Core asks here when it needs to know if moving stock crosses the licensed-area boundary. With
several sites switched on, NZ Alcohol answers from its Customs register: a site's main area,
or a named area with its own record, on that day. Otherwise there is no answer (None) and core
keeps using each area's own flag. Core never names a module.
"""

from datetime import date


def _provider(session, org_id):
    from app.core.db.models.organisation import Organisation
    from app.features.compliant.models.compliance_profile import ComplianceProfile

    multiple = session.query(Organisation.multiple_sites_enabled).filter(Organisation.id == org_id).scalar()
    if not multiple:
        return None
    profile = session.query(ComplianceProfile).filter(ComplianceProfile.org_id == org_id).one_or_none()
    if profile is None or not profile.enabled or profile.industry_module != "nz_alcohol":
        return None
    from app.features.compliant.modules.nz_alcohol.premises import licence_for_area

    return lambda site_id, location_id, on: licence_for_area(session, org_id, site_id, location_id, on) is not None


def licensed_place(session, org_id, site_id, location_id, on: date | None = None) -> bool | None:
    """True or False from the module, or None when no module decides it."""
    decide = _provider(session, org_id)
    return decide(site_id, location_id, on or date.today()) if decide else None


def licensed_map(session, org_id, sites, areas, on: date | None = None) -> dict | None:
    """``{"sites": {site_id: main_area_licensed}, "areas": {location_id: licensed}}`` or None."""
    decide = _provider(session, org_id)
    if decide is None:
        return None
    on = on or date.today()
    return {
        "sites": {str(s.id): decide(s.id, None, on) for s in sites},
        "areas": {str(a.id): decide(a.site_id, a.id, on) for a in areas},
    }
