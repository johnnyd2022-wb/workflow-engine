# Cloudflare Access in front of production. Created only when production is published
# (local.publish_production in main.tf), and before its route and DNS record exist.
#
# Access here is a second gate, not the app's own sign-in: only these addresses get as far
# as the biz-e sign-in page. Widen the list (or switch the rule to an email domain) as
# customers are brought on.

resource "cloudflare_zero_trust_access_policy" "production" {
  count = local.publish_production ? 1 : 0

  account_id = var.account_id
  name       = "biz-e production: allowed people"
  decision   = "allow"
  include    = [for email in var.production_access_emails : { email = { email = email } }]
}

resource "cloudflare_zero_trust_access_application" "production" {
  count = local.publish_production ? 1 : 0

  account_id       = var.account_id
  name             = "biz-e production"
  type             = "self_hosted"
  domain           = local.production_hostname
  session_duration = "24h"
  policies = [{
    id         = cloudflare_zero_trust_access_policy.production[0].id
    precedence = 1
  }]
}
