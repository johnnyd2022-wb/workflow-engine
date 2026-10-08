resource "cloudflare_zero_trust_tunnel_cloudflared" "this" {
  account_id = var.account_id
  name       = var.name
  config_src = "cloudflare"
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "this" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.this.id
  config = {
    ingress = concat([
      for hostname in sort(keys(var.routes)) : {
        hostname = hostname
        service  = var.routes[hostname].service
        origin_request = {
          no_tls_verify = var.routes[hostname].no_tls_verify
        }
      }
    ], [{ service = "http_status:404" }])
  }
}

resource "cloudflare_dns_record" "routes" {
  for_each = var.routes

  zone_id = var.zone_id
  name    = each.key
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.this.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
}
