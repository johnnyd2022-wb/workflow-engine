"""Costing's contribution to Home and Notifications (spec 8.1d): purchases waiting in To record.

Shown to people who can record them (``costs.manage``), in orgs with the costing feature and a
connected Xero; nothing at zero.
"""

from __future__ import annotations

from datetime import date


def purchases_to_record(db, org_id, user) -> list[dict]:
    from app.core.security.access_policy import has_permission
    from app.core.security.entitlements import org_has_feature
    from app.features.costing import FEATURE_KEY
    from app.features.costing.actions import to_record_summary
    from app.features.crm.repositories.xero_tenant_repo import XeroTenantRepository

    if not has_permission(user, "costs.manage") or not org_has_feature(db, org_id, FEATURE_KEY):
        return []
    if XeroTenantRepository(db).get_connected(org_id) is None:
        return []
    summary = to_record_summary(db, org_id)
    if not summary["count"]:
        return []
    detail = None
    if summary["newest"]:
        newest = date.fromisoformat(summary["newest"])
        detail = "Newest " + newest.strftime("%-d %b %Y")
    return [
        {
            "key": "costing_purchases_to_record",
            "label": "Purchases to record into stock",
            "count": summary["count"],
            "severity": "medium",
            "href": "/core/costing/purchases",
            "workspace": "Production",
            "detail": detail,
        }
    ]
