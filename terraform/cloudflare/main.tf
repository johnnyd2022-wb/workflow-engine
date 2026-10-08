# Everything Cloudflare serves from the one tunnel on this machine: hostname => origin.
#
# To add a site, add a line and apply. The module puts Cloudflare Access (founders only)
# in front of it, then creates the tunnel route and the DNS record, with the same settings
# as every other site. The whistlebird.co.nz hostnames share the tunnel; their DNS records
# and Access applications are managed outside this root.
module "tunnel" {
  source = "../modules/cloudflare-tunnel"

  account_id = var.account_id
  zone_id    = var.zone_id
  zone_name  = "biz-e.app"
  name       = "wb_inventory_maungaraki"

  routes = {
    "biz-e.app"            = "https://host.docker.internal:8010" # production (scripts/run_prod.sh)
    "test.biz-e.app"       = "https://host.docker.internal:8001" # test
    "admin-test.biz-e.app" = "https://host.docker.internal:8020" # test admin site (scripts/run_admin.sh)
    "dev.biz-e.app"        = "https://172.26.121.16:8005"        # local development

    "inventory.whistlebird.co.nz"      = "https://host.docker.internal:5000"
    "test-inventory.whistlebird.co.nz" = "https://host.docker.internal:5001"
    "access.whistlebird.co.nz"         = "rdp://host.docker.internal:3389"
  }
}
