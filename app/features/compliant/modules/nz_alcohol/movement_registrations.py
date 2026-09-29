"""Recorded destination coverage checks; no legal authority is inferred from site kind."""

from sqlalchemy import or_

from app.core.db.models.site import Site
from app.core.db.models.site_transfer import SiteStockReceipt, SiteStockTransfer
from app.features.compliant.models.licensing import LiquorLicence
from app.features.compliant.modules.nz_alcohol.food_registrations import ACTIVITIES, covers_activity


def coverage_findings(session, org_id, site_id, activity, on, transfer_id):
    site = session.query(Site).filter(Site.org_id == org_id, Site.id == site_id).one_or_none()
    if site is None:
        return []  # Core rejects foreign/missing sites; never reveal another tenant's site.
    prefix = f"nz-movement-{transfer_id}"
    base = {"due_date": on.isoformat(), "action_label": "Review registration"}
    if not isinstance(activity, str) or activity not in ACTIVITIES:
        return [
            {
                **base,
                "id": f"{prefix}-activity",
                "title": f"Record the intended activity at {site.name}",
                "description": "Destination activity was not recorded. Site kind does not establish food or selling coverage.",
                "href": "/core/site-transfers",
            }
        ]
    alerts = []
    if not covers_activity(session, org_id, site.id, activity, on):
        alerts.append(
            {
                **base,
                "id": f"{prefix}-food",
                "title": f"Review food registration at {site.name}",
                "description": f"No recorded food registration covers {activity} at this site on {on.isoformat()}. Check the registration and record its explicit premises scope.",
                "href": "/compliant/nz-alcohol/food-registrations",
            }
        )
    if activity == "selling":
        query = session.query(LiquorLicence.id).filter(
            LiquorLicence.org_id == org_id,
            LiquorLicence.site_id == site.id,
            LiquorLicence.status == "current",
            LiquorLicence.licence_number.isnot(None),
            LiquorLicence.licence_number != "",
            LiquorLicence.issued_on <= on,
            LiquorLicence.expires_on >= on,
            or_(
                LiquorLicence.kind.in_(("on", "off", "club")),
                (LiquorLicence.kind == "special")
                & (LiquorLicence.event_starts_on <= on)
                & (LiquorLicence.event_ends_on >= on),
            ),
        )
        if query.first() is None:
            alerts.append(
                {
                    **base,
                    "id": f"{prefix}-liquor",
                    "title": f"Review liquor licence at {site.name}",
                    "description": f"No current, dated liquor licence is recorded for this selling site on {on.isoformat()}. Review the applicable licence, conditions and selling hours; stock receipt is not permission to sell.",
                    "href": "/compliant/nz-alcohol/licensing",
                }
            )
    return alerts


def transfer_findings(session, org_id):
    alerts = []
    for transfer in session.query(SiteStockTransfer).filter(SiteStockTransfer.org_id == org_id):
        evidence = transfer.decision_snapshot or {}
        if evidence.get("policy") != "nz_alcohol_cca_1":
            continue
        alerts.extend(
            coverage_findings(
                session,
                org_id,
                transfer.destination_site_id,
                evidence.get("destination_activity"),
                transfer.occurred_on,
                transfer.id,
            )
        )
    for receipt, transfer in (
        session.query(SiteStockReceipt, SiteStockTransfer)
        .join(
            SiteStockTransfer,
            (SiteStockTransfer.org_id == SiteStockReceipt.org_id)
            & (SiteStockTransfer.id == SiteStockReceipt.transfer_id),
        )
        .filter(SiteStockReceipt.org_id == org_id, SiteStockReceipt.quantity > 0)
    ):
        evidence = (receipt.decision_snapshot or {}).get("receipt") or {}
        if evidence.get("policy") != "nz_alcohol_cca_1":
            continue
        alerts.extend(
            coverage_findings(
                session,
                org_id,
                transfer.destination_site_id,
                evidence.get("destination_activity"),
                receipt.occurred_on,
                f"{transfer.id}-receipt-{receipt.id}",
            )
        )
    return alerts
