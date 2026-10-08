locals {
  # The same settings for every site, so a route is only ever a hostname and an origin.
  # Each timeout is the longest any route had before they were made the same.
  http_origin = {
    no_tls_verify          = true # origins serve a self-signed certificate
    http2_origin           = true
    connect_timeout        = 1800
    tls_timeout            = 600
    tcp_keep_alive         = 600
    keep_alive_timeout     = 1800
    keep_alive_connections = 600
  }

  # Who gets in, and how they sign in: the same for every published site.
  access_session    = "730h"
  founders_group    = "1ddc91a4-287b-488c-8d7e-529479a9ea64" # Access group, managed in the dashboard
  identity_provider = "d64aecc5-00f5-439f-a87a-ce249fe4c347" # the one sign-in method offered

  hostnames = sort(keys(var.routes))
  # Hostnames in this root's zone: the apex and anything under it.
  published = toset([
    for hostname in local.hostnames : hostname
    if hostname == var.zone_name || endswith(hostname, ".${var.zone_name}")
  ])
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "this" {
  account_id = var.account_id
  name       = var.name
  config_src = "cloudflare"
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "this" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.this.id
  config = {
    ingress = concat(
      [
        for hostname in local.hostnames : {
          hostname       = hostname
          service        = var.routes[hostname]
          origin_request = local.http_origin
        } if startswith(var.routes[hostname], "http")
      ],
      # Other protocols (rdp://) take none of the HTTP origin settings.
      [
        for hostname in local.hostnames : {
          hostname       = hostname
          service        = var.routes[hostname]
          origin_request = {}
        } if !startswith(var.routes[hostname], "http")
      ],
      [{ service = "http_status:404" }],
    )
  }

  # A hostname is reachable once it has both a route and a DNS record. Neither exists
  # until its Access application does.
  depends_on = [cloudflare_zero_trust_access_application.this]
}

resource "cloudflare_zero_trust_access_application" "this" {
  for_each = local.published

  account_id                 = var.account_id
  name                       = each.value
  type                       = "self_hosted"
  domain                     = each.value
  destinations               = [{ type = "public", uri = each.value }]
  session_duration           = local.access_session
  allowed_idps               = [local.identity_provider]
  auto_redirect_to_identity  = true # one sign-in method, so skip the chooser
  http_only_cookie_attribute = true
  enable_binding_cookie      = false
  options_preflight_bypass   = false
  policies                   = [{ id = cloudflare_zero_trust_access_policy.founders.id, precedence = 1 }]
}

resource "cloudflare_zero_trust_access_policy" "founders" {
  account_id       = var.account_id
  name             = "Founder access"
  decision         = "allow"
  session_duration = "168h"
  include          = [{ group = { id = local.founders_group } }]
}

resource "cloudflare_dns_record" "this" {
  for_each = local.published

  zone_id = var.zone_id
  name    = each.value
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.this.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1

  depends_on = [cloudflare_zero_trust_access_application.this]
}
