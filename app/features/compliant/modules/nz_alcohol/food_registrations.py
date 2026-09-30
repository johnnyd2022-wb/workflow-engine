"""Registration scope is recorded explicitly; site kind is not a food permission."""

from datetime import date
from types import SimpleNamespace

from app.core.db.models.site import Site
from app.features.compliant.models.food_registration import FoodRegistration, FoodRegistrationSite
from app.features.compliant.modules.nz_alcohol.premises import _body, _id, _text

PROGRAMMES = {"np1": "NP1", "np2": "NP2", "np3": "NP3", "fcp": "Food control plan"}
ACTIVITIES = {"manufacturing": "Manufacturing", "storage": "Storage", "selling": "Selling"}


def add_registration(db, org_id, data, today):
    _body(
        data, {"reference", "name", "programme", "registered_on", "registered_as", "valid_until", "evidence_reference"}
    )
    programme, registered_as = data.get("programme"), data.get("registered_as")
    if not isinstance(programme, str) or programme not in PROGRAMMES:
        raise ValueError("Choose NP1, NP2, NP3 or a food control plan")
    if not isinstance(registered_as, str) or registered_as not in {"new", "existing"}:
        raise ValueError("Choose whether registered as a new or existing business")
    try:
        registered_on = date.fromisoformat(data.get("registered_on"))
        until = None if data.get("valid_until") is None else date.fromisoformat(data["valid_until"])
    except (ValueError, TypeError):
        raise ValueError("Enter valid registration dates") from None
    if registered_on > today or (until is not None and until < registered_on):
        raise ValueError("Registration dates must be valid and registration must have happened")
    reference = _text(data, "reference", 100).upper()
    if (
        db.query(FoodRegistration.id)
        .filter(FoodRegistration.org_id == org_id, FoodRegistration.reference == reference)
        .first()
    ):
        raise ValueError("That food registration is already recorded")
    row = FoodRegistration(
        org_id=org_id,
        reference=reference,
        name=_text(data, "name", 150),
        programme=programme,
        registered_on=registered_on,
        registered_as=registered_as,
        valid_until=until,
        evidence_reference=_text(data, "evidence_reference", 500),
    )
    db.add(row)
    db.flush()
    return row


def get_registration(db, org_id, registration_id, lock=False):
    query = db.query(FoodRegistration).filter(
        FoodRegistration.org_id == org_id, FoodRegistration.id == _id(registration_id)
    )
    if lock:
        query = query.with_for_update().populate_existing()
    row = query.one_or_none()
    if row is None:
        raise ValueError("Food registration not found in this business")
    return row


def add_scope(db, org_id, data):
    _body(data, {"registration_id", "site_id", "activity", "evidence_reference"})
    activity = data.get("activity")
    if not isinstance(activity, str) or activity not in ACTIVITIES:
        raise ValueError("Choose the activity covered by the registration")
    row = get_registration(db, org_id, data.get("registration_id"), lock=True)
    site = (
        db.query(Site)
        .filter(Site.org_id == org_id, Site.id == _id(data.get("site_id")))
        .with_for_update(read=True)
        .populate_existing()
        .one_or_none()
    )
    if site is None or not site.is_active:
        raise ValueError("Choose an active site belonging to this business")
    if (
        db.query(FoodRegistrationSite.id)
        .filter(
            FoodRegistrationSite.org_id == org_id,
            FoodRegistrationSite.registration_id == row.id,
            FoodRegistrationSite.site_id == site.id,
            FoodRegistrationSite.activity == activity,
        )
        .first()
    ):
        raise ValueError("This activity is already covered at that site")
    scope = FoodRegistrationSite(
        org_id=org_id,
        registration_id=row.id,
        site_id=site.id,
        activity=activity,
        evidence_reference=_text(data, "evidence_reference", 500),
    )
    db.add(scope)
    db.flush()
    return scope


def registration_profile(registration):
    # Reuse national-programme date rules without changing the org's singleton settings.
    return SimpleNamespace(
        settings={
            "food_control_programme": registration.programme,
            "np_registered_on": registration.registered_on.isoformat(),
            "np_registered_as": registration.registered_as,
        }
    )


def record_dict(row):
    base = {"id": str(row.id), "evidence_reference": row.evidence_reference}
    if isinstance(row, FoodRegistration):
        return {
            **base,
            "reference": row.reference,
            "name": row.name,
            "programme": row.programme,
            "registered_on": row.registered_on.isoformat(),
            "registered_as": row.registered_as,
            "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        }
    return {**base, "registration_id": str(row.registration_id), "site_id": str(row.site_id), "activity": row.activity}


def overview(db, org_id):
    return {
        "registrations": [
            record_dict(r)
            for r in db.query(FoodRegistration)
            .filter(FoodRegistration.org_id == org_id)
            .order_by(FoodRegistration.name)
            .all()
        ],
        "coverage": [
            record_dict(r) for r in db.query(FoodRegistrationSite).filter(FoodRegistrationSite.org_id == org_id).all()
        ],
        "sites": [
            {"id": str(r.id), "name": r.name}
            for r in db.query(Site).filter(Site.org_id == org_id, Site.is_active.is_(True)).order_by(Site.name).all()
        ],
        "programmes": PROGRAMMES,
        "activities": ACTIVITIES,
    }


def covers_activity(db, org_id, site_id, activity, on):
    return (
        db.query(FoodRegistrationSite.id)
        .join(
            FoodRegistration,
            (FoodRegistration.id == FoodRegistrationSite.registration_id)
            & (FoodRegistration.org_id == FoodRegistrationSite.org_id),
        )
        .filter(
            FoodRegistrationSite.org_id == org_id,
            FoodRegistrationSite.site_id == site_id,
            FoodRegistrationSite.activity == activity,
            FoodRegistration.registered_on <= on,
            (FoodRegistration.valid_until.is_(None) | (FoodRegistration.valid_until >= on)),
        )
        .first()
        is not None
    )
