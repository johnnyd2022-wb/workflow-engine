"""Customs owns licences; Core owns the sites and stock locations they cover."""

from datetime import date
from uuid import UUID

from sqlalchemy import or_

from app.core.db.models.site import Site
from app.core.db.models.stock_location import StockLocation
from app.features.compliant.models.customs_premises import CustomsCoverage, CustomsLicence

KINDS = {
    "lma": "Manufacturing area",
    "oss": "Off-site storage",
    "duty_free": "Duty-free shop",
    "export": "Export warehouse",
}


def _text(data, key, limit):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{key} must be text, from 1 to {limit} characters")
    return value.strip()


def _dates(data):
    try:
        start = date.fromisoformat(data["valid_from"])
        end_value = data.get("valid_until")
        end = None if end_value is None else date.fromisoformat(end_value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Enter valid ISO licence dates") from exc
    if end is not None and end < start:
        raise ValueError("End date cannot precede start date")
    return start, end


def _id(value):
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError("Invalid premises reference") from exc


def _body(data, allowed):
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("Unexpected premises fields")


def add_licence(db, org_id, data):
    _body(data, {"number", "name", "kind", "legal_entity_reference", "valid_from", "valid_until", "evidence_reference"})
    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("Choose a valid Customs licence type")
    start, end = _dates(data)
    number = _text(data, "number", 100).upper()
    if db.query(CustomsLicence.id).filter(CustomsLicence.org_id == org_id, CustomsLicence.number == number).first():
        raise ValueError("That licence is already registered")
    licence = CustomsLicence(
        org_id=org_id,
        number=number,
        name=_text(data, "name", 150),
        kind=kind,
        legal_entity_reference=_text(data, "legal_entity_reference", 100),
        valid_from=start,
        valid_until=end,
        evidence_reference=_text(data, "evidence_reference", 500),
    )
    db.add(licence)
    db.flush()
    return licence


def add_coverage(db, org_id, data):
    _body(data, {"licence_id", "site_id", "location_id", "valid_from", "valid_until", "evidence_reference"})
    site_id, licence_id = _id(data.get("site_id")), _id(data.get("licence_id"))
    # Serialize all area assignments at this site, including its unnamed main area.
    site = db.query(Site).filter(Site.org_id == org_id, Site.id == site_id).with_for_update().one_or_none()
    if site is None or not site.is_active:
        raise ValueError("Choose an active site belonging to this business")
    licence = (
        db.query(CustomsLicence).filter(CustomsLicence.org_id == org_id, CustomsLicence.id == licence_id).one_or_none()
    )
    if licence is None:
        raise ValueError("Choose a licence belonging to this business")
    location_id = _id(data["location_id"]) if data.get("location_id") is not None else None
    if location_id is not None:
        location = (
            db.query(StockLocation)
            .filter(
                StockLocation.org_id == org_id,
                StockLocation.site_id == site_id,
                StockLocation.id == location_id,
                StockLocation.is_active.is_(True),
            )
            .one_or_none()
        )
        if location is None:
            raise ValueError("Choose a location at the selected site")
    start, end = _dates(data)
    if start < licence.valid_from or (licence.valid_until is not None and (end is None or end > licence.valid_until)):
        raise ValueError("Area coverage must fall within the licence's valid dates")
    overlap = (
        db.query(CustomsCoverage.id)
        .filter(
            CustomsCoverage.org_id == org_id,
            CustomsCoverage.site_id == site_id,
            CustomsCoverage.location_id == location_id,
            CustomsCoverage.valid_from <= (end or date.max),
            or_(CustomsCoverage.valid_until.is_(None), CustomsCoverage.valid_until >= start),
        )
        .first()
    )
    if overlap:
        raise ValueError("This area already has Customs coverage during those dates")
    row = CustomsCoverage(
        org_id=org_id,
        site_id=site_id,
        licence_id=licence_id,
        location_id=location_id,
        valid_from=start,
        valid_until=end,
        evidence_reference=_text(data, "evidence_reference", 500),
    )
    db.add(row)
    db.flush()
    return row


def licence_for_area(db, org_id, site_id, location_id, on):
    """Exact dated area lookup. A main-area record never licenses an outside shop."""
    return (
        db.query(CustomsLicence)
        .join(
            CustomsCoverage,
            (CustomsCoverage.licence_id == CustomsLicence.id) & (CustomsCoverage.org_id == CustomsLicence.org_id),
        )
        .filter(
            CustomsLicence.org_id == org_id,
            CustomsCoverage.org_id == org_id,
            CustomsCoverage.site_id == site_id,
            CustomsCoverage.location_id == location_id,
            CustomsCoverage.valid_from <= on,
            or_(CustomsCoverage.valid_until.is_(None), CustomsCoverage.valid_until >= on),
            CustomsLicence.valid_from <= on,
            or_(CustomsLicence.valid_until.is_(None), CustomsLicence.valid_until >= on),
        )
        .one_or_none()
    )


def record_dict(row):
    fields = (
        ("number", "name", "kind", "legal_entity_reference")
        if isinstance(row, CustomsLicence)
        else ("licence_id", "site_id", "location_id")
    )
    result = {
        "id": str(row.id),
        "valid_from": row.valid_from.isoformat(),
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "evidence_reference": row.evidence_reference,
    }
    for field in fields:
        value = getattr(row, field)
        result[field] = str(value) if isinstance(value, UUID) else value
    return result


def overview(db, org_id):
    return {
        "licences": [
            record_dict(row)
            for row in db.query(CustomsLicence)
            .filter(CustomsLicence.org_id == org_id)
            .order_by(CustomsLicence.number)
            .all()
        ],
        "coverage": [
            record_dict(row)
            for row in db.query(CustomsCoverage)
            .filter(CustomsCoverage.org_id == org_id)
            .order_by(CustomsCoverage.valid_from)
            .all()
        ],
        "sites": [
            {"id": str(row.id), "name": row.name}
            for row in db.query(Site).filter(Site.org_id == org_id, Site.is_active.is_(True)).order_by(Site.name).all()
        ],
        "locations": [
            {"id": str(row.id), "site_id": str(row.site_id), "name": row.name}
            for row in db.query(StockLocation)
            .filter(StockLocation.org_id == org_id, StockLocation.is_active.is_(True))
            .order_by(StockLocation.name)
            .all()
        ],
        "kinds": KINDS,
    }
