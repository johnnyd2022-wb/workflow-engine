# Everything Cloudflare serves from the one tunnel on this machine: hostname => origin.
#
# To add a site, add a line and apply. The module puts Cloudflare Access (founders only)
# in front of it (minus any public_paths), then creates the tunnel route and the DNS record, with the same settings
# as every other site. The whistlebird.co.nz hostnames share the tunnel; their DNS records
# and Access applications are managed outside this root.
#
# Applied by CI from main, once the plan posted on the merge request has been reviewed
# (terraform/ci.py). Nothing here is applied by hand.
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
    "test-glass.biz-e.app" = "https://host.docker.internal:8003" # Glass prototype, branch proto/glass-theme (scripts/deploy_test_glass.sh there; applied by !772 follow-up)

    # The public MCP server (bize_mcp, scripts/run_mcp.sh): plain HTTP, published on loopback only.
    # Founders-only behind Access like every biz-e.app host, except the paths in public_paths.
    "mcp-test.biz-e.app" = "http://host.docker.internal:8030" # test
    "mcp.biz-e.app"      = "http://host.docker.internal:8031" # production

    "inventory.whistlebird.co.nz"      = "https://host.docker.internal:5000"
    "test-inventory.whistlebird.co.nz" = "https://host.docker.internal:5001"
    "access.whistlebird.co.nz"         = "rdp://host.docker.internal:3389"
  }

  # What an AI assistant calls by itself, with no browser to pass Access (public MCP 8.2; founder,
  # 17 Nov 2026). Each still has its own sign-in: MCP and the OAuth token/registration endpoints
  # are bearer- or PKCE-protected and rate limited. /oauth/authorize (the approve screen) opens in
  # the person's browser, so it stays founders-only for now. Test only; production gets the same
  # when MCP goes public. (Re-planned after main moved on before the first apply.)
  public_paths = [
    "mcp-test.biz-e.app/mcp",
    "mcp-test.biz-e.app/.well-known/*",
    "test.biz-e.app/.well-known/*",
    "test.biz-e.app/oauth/token",
    "test.biz-e.app/oauth/register",
    "test.biz-e.app/oauth/revoke",
  ]
}
