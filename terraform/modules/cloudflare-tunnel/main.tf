locals {
  ingress_order = concat(var.ingress_order, sort(tolist(setsubtract(keys(var.routes), var.ingress_order))))
  dns_hostnames = toset([for hostname, route in var.routes : hostname if route.dns])
  access        = { for hostname, route in var.routes : hostname => route.access if route.access != null }
  # A hostname this root publishes must sit behind Access unless it says, in so many words,
  # that it is meant to be open to the internet.
  unprotected = [
    for hostname, route in var.routes : hostname if route.dns && route.access == null && !route.public
  ]
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "this" {
  account_id = var.account_id
  name       = var.name
  config_src = "cloudflare"

  lifecycle {
    precondition {
      condition     = length(setsubtract(var.ingress_order, keys(var.routes))) == 0 && length(var.ingress_order) == length(toset(var.ingress_order))
      error_message = "ingress_order may only list route hostnames, each at most once."
    }
    precondition {
      condition     = length(local.unprotected) == 0
      error_message = "These hostnames would be published without Cloudflare Access: ${join(", ", local.unprotected)}. Give each an access block, or public = true if that is intended."
    }
    precondition {
      condition = alltrue(flatten([
        for access in values(local.access) : [for key in access.policies : contains(keys(var.access_policy_ids), key)]
      ]))
      error_message = "A route names an Access policy that is not in access_policy_ids."
    }
  }
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "this" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.this.id
  config = {
    ingress = concat([
      for hostname in local.ingress_order : {
        hostname       = hostname
        service        = var.routes[hostname].service
        origin_request = var.routes[hostname].origin_request
      }
    ], [{ service = "http_status:404" }])
  }

  # A hostname is reachable once it has both a route and a DNS record. Neither exists
  # until its Access application does.
  depends_on = [cloudflare_zero_trust_access_application.this]
}

resource "cloudflare_zero_trust_access_application" "this" {
  for_each = local.access

  account_id                 = var.account_id
  name                       = coalesce(each.value.name, each.key)
  type                       = "self_hosted"
  domain                     = each.key
  destinations               = [{ type = "public", uri = each.key }]
  session_duration           = each.value.session_duration
  allowed_idps               = each.value.allowed_idps
  auto_redirect_to_identity  = each.value.auto_redirect_to_identity
  http_only_cookie_attribute = each.value.http_only_cookie_attribute
  enable_binding_cookie      = false
  options_preflight_bypass   = false
  policies = [
    for index, key in each.value.policies : {
      id         = var.access_policy_ids[key]
      precedence = index + 1
    }
  ]
}

resource "cloudflare_dns_record" "routes" {
  for_each = local.dns_hostnames

  zone_id = var.zone_id
  name    = each.value
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.this.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1

  depends_on = [cloudflare_zero_trust_access_application.this]
}
