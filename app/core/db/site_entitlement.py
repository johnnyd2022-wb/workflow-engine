"""Whether an organisation may work at sites other than its default (GL-P07).

Three gates, all off by default:

1. the deployment: ``[features] multi_site_enabled`` in the environment's ini;
2. the organisation's subscription: the ``multi_site`` feature;
3. the organisation's own switch: ``Organisation.multiple_sites_enabled`` (Settings, Sites).

The first two are the *entitlement*: they decide whether the Sites settings appear at all.
The third is the business turning it on. Records made without a site always land on the
default site, whatever the gates say.
"""

from app.core.db.models.feature_subscription import FeatureSubscription
from app.utils.config_loader import config

FEATURE_KEY = "multi_site"


def entitled(session, org_id) -> bool:
    """The deployment and the organisation's subscription both allow multiple sites."""
    if not config.multi_site_enabled:
        return False
    return (
        session.query(FeatureSubscription.id)
        .filter(
            FeatureSubscription.org_id == org_id,
            FeatureSubscription.feature_key == FEATURE_KEY,
            FeatureSubscription.active.is_(True),
        )
        .first()
        is not None
    )


def sites_on(session, org_id, multiple_sites_enabled: bool) -> bool:
    """All three gates: work may happen at any active site, not just the default."""
    return bool(multiple_sites_enabled) and entitled(session, org_id)
