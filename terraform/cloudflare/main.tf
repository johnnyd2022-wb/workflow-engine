locals {
  # Placeholder names: align these with existing tunnels before importing/applying.
  tunnels = {
    test = {
      name = "biz-e-test"
      routes = {
        "test.biz-e.app"       = { service = "https://host.docker.internal:8001" }
        "admin-test.biz-e.app" = { service = "https://host.docker.internal:8020" }
      }
    }
    dev = {
      name = "biz-e-dev"
      routes = {
        "dev.biz-e.app" = { service = "https://172.26.121.16:8005" }
      }
    }
  }
}

module "tunnels" {
  source   = "../modules/cloudflare-tunnel"
  for_each = local.tunnels

  account_id = var.account_id
  zone_id    = var.zone_id
  name       = each.value.name
  routes     = each.value.routes
}
