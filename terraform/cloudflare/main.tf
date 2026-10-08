locals {
  # Reusable Cloudflare Access policies, by the key routes refer to them with.
  access_policies = {
    founders = {
      name             = "Founder access"
      decision         = "allow"
      session_duration = "168h"
      # The "founders" Access group (managed in the Cloudflare dashboard).
      include = [{ group = { id = "1ddc91a4-287b-488c-8d7e-529479a9ea64" } }]
    }
  }

  # To add a site: add one block to `routes` with its origin and an `access` block naming
  # the policies that may reach it. That creates the Access application, then the tunnel
  # route and the DNS record. A site with no `access` block is refused unless it also says
  # `public = true`.
  #
  # The existing local connector serves this one shared, remotely managed tunnel.
  # Its complete ingress map includes Whistlebird routes that must be retained; their DNS
  # records and Access applications are outside this root's scope (dns = false).
  tunnels = {
    maungaraki = {
      name = "wb_inventory_maungaraki"
      routes = {
        "inventory.whistlebird.co.nz" = {
          service = "https://host.docker.internal:5000"
          dns     = false
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
          dns     = false
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
          dns            = false
          origin_request = {}
        }
        "test.biz-e.app" = {
          service = "https://host.docker.internal:8001"
          origin_request = {
            http2_origin       = true
            no_tls_verify      = true
            keep_alive_timeout = 1800
          }
          access = {
            policies                   = ["founders"]
            session_duration           = "730h"
            http_only_cookie_attribute = false
          }
        }
        "dev.biz-e.app" = {
          service = "https://172.26.121.16:8005"
          origin_request = {
            http2_origin       = true
            no_tls_verify      = true
            keep_alive_timeout = 1800
          }
          access = {
            policies                   = ["founders"]
            session_duration           = "730h"
            http_only_cookie_attribute = false
          }
        }
        # Test admin site (scripts/run_admin.sh).
        "admin-test.biz-e.app" = {
          service = "https://host.docker.internal:8020"
          origin_request = {
            http2_origin       = true
            no_tls_verify      = true
            keep_alive_timeout = 1800
          }
          access = {
            policies                   = ["founders"]
            session_duration           = "168h"
            allowed_idps               = ["d64aecc5-00f5-439f-a87a-ce249fe4c347"]
            auto_redirect_to_identity  = true
            http_only_cookie_attribute = false
          }
        }
        # Production customer app (scripts/run_prod.sh, published on loopback port 8010).
        "biz-e.app" = {
          service = "https://host.docker.internal:8010"
          origin_request = {
            http2_origin       = true
            no_tls_verify      = true
            keep_alive_timeout = 1800
          }
          access = {
            name     = "biz-e production"
            policies = ["founders"]
          }
        }
      }
      # Cloudflare's existing rule order; routes not listed follow, sorted by hostname.
      ingress_order = [
        "inventory.whistlebird.co.nz",
        "test-inventory.whistlebird.co.nz",
        "access.whistlebird.co.nz",
        "test.biz-e.app",
        "dev.biz-e.app",
        "admin-test.biz-e.app",
      ]
    }
  }
}

resource "cloudflare_zero_trust_access_policy" "this" {
  for_each = local.access_policies

  account_id       = var.account_id
  name             = each.value.name
  decision         = each.value.decision
  session_duration = each.value.session_duration
  include          = each.value.include
}

module "tunnels" {
  source   = "../modules/cloudflare-tunnel"
  for_each = local.tunnels

  account_id        = var.account_id
  zone_id           = var.zone_id
  name              = each.value.name
  routes            = each.value.routes
  ingress_order     = each.value.ingress_order
  access_policy_ids = { for key, policy in cloudflare_zero_trust_access_policy.this : key => policy.id }
}
