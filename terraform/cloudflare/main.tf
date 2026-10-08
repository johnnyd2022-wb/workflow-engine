locals {
  # Production (https://biz-e.app -> scripts/run_prod.sh on loopback port 8010) is published
  # only together with the Cloudflare Access application in access.tf, never without it.
  # Turn this on once the API token can manage Access (see README, "Publishing production").
  publish_production = false

  production_hostname  = "biz-e.app"
  production_hostnames = local.publish_production ? [local.production_hostname] : []
  production_routes = {
    for hostname in local.production_hostnames : hostname => {
      service = "https://host.docker.internal:8010"
      origin_request = {
        http2_origin       = true
        no_tls_verify      = true
        keep_alive_timeout = 1800
      }
    }
  }

  # The existing local connector serves this one shared, remotely managed tunnel.
  # Its complete ingress map includes Whistlebird routes that must be retained.
  tunnels = {
    maungaraki = {
      name = "wb_inventory_maungaraki"
      routes = merge(local.production_routes, {
        "inventory.whistlebird.co.nz" = {
          service = "https://host.docker.internal:5000"
          origin_request = {
            tls_timeout            = 600
            no_tls_verify          = true
            tcp_keep_alive         = 600
            connect_timeout        = 1800
            keep_alive_timeout     = 1800
            keep_alive_connections = 600
          }
        }
        "test-inventory.whistlebird.co.nz" = {
          service = "https://host.docker.internal:5001"
          origin_request = {
            tls_timeout              = 600
            http2_origin             = true
            no_tls_verify            = true
            tcp_keep_alive           = 600
            connect_timeout          = 1800
            keep_alive_timeout       = 600
            keep_alive_connections   = 100
            disable_chunked_encoding = false
          }
        }
        "access.whistlebird.co.nz" = {
          service        = "rdp://host.docker.internal:3389"
          origin_request = {}
        }
        "test.biz-e.app" = {
          service = "https://host.docker.internal:8001"
          origin_request = {
            http2_origin       = true
            no_tls_verify      = true
            keep_alive_timeout = 1800
          }
        }
        "dev.biz-e.app" = {
          service = "https://172.26.121.16:8005"
          origin_request = {
            http2_origin       = true
            no_tls_verify      = true
            keep_alive_timeout = 1800
          }
        }
        "admin-test.biz-e.app" = {
          service = "https://host.docker.internal:8020"
          origin_request = {
            http2_origin       = true
            no_tls_verify      = true
            keep_alive_timeout = 1800
          }
        }
      })
      # Preserve Cloudflare's existing rule order; the module appends the 404 rule.
      ingress_order = concat([
        "inventory.whistlebird.co.nz",
        "test-inventory.whistlebird.co.nz",
        "access.whistlebird.co.nz",
        "test.biz-e.app",
        "dev.biz-e.app",
        "admin-test.biz-e.app",
      ], local.production_hostnames)
      # Whistlebird DNS records are outside this Terraform root's scope.
      dns_hostnames = concat(["test.biz-e.app", "admin-test.biz-e.app", "dev.biz-e.app"], local.production_hostnames)
    }
  }
}

module "tunnels" {
  source   = "../modules/cloudflare-tunnel"
  for_each = local.tunnels

  account_id    = var.account_id
  zone_id       = var.zone_id
  name          = each.value.name
  routes        = each.value.routes
  ingress_order = each.value.ingress_order
  dns_hostnames = each.value.dns_hostnames

  # The production hostname must already be behind Access before it gets a route or a
  # DNS record. If the Access application cannot be created, nothing here changes.
  depends_on = [cloudflare_zero_trust_access_application.production]
}
