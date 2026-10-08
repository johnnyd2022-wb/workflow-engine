locals {
  ingress_order = length(var.ingress_order) > 0 ? var.ingress_order : sort(keys(var.routes))
  dns_hostnames = var.dns_hostnames == null ? toset(keys(var.routes)) : var.dns_hostnames
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "this" {
  account_id = var.account_id
  name       = var.name
  config_src = "cloudflare"

  lifecycle {
    precondition {
      condition     = toset(local.ingress_order) == toset(keys(var.routes)) && length(local.ingress_order) == length(var.routes)
      error_message = "ingress_order must contain every route hostname exactly once."
    }
    precondition {
      condition     = length(setsubtract(local.dns_hostnames, toset(keys(var.routes)))) == 0
      error_message = "dns_hostnames must be a subset of the route hostnames."
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
}

resource "cloudflare_dns_record" "routes" {
  for_each = local.dns_hostnames

  zone_id = var.zone_id
  name    = each.value
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.this.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
}
