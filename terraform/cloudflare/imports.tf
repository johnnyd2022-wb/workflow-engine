# Existing Cloudflare console resources. These blocks also document/reproduce
# adoption when initializing an empty backend; they are no-ops after import.
import {
  to = module.tunnels["maungaraki"].cloudflare_zero_trust_tunnel_cloudflared.this
  id = "${var.account_id}/b1ec55ef-92f4-4322-b72a-13ae0915a54f"
}

import {
  to = module.tunnels["maungaraki"].cloudflare_zero_trust_tunnel_cloudflared_config.this
  id = "${var.account_id}/b1ec55ef-92f4-4322-b72a-13ae0915a54f"
}

import {
  to = module.tunnels["maungaraki"].cloudflare_dns_record.routes["test.biz-e.app"]
  id = "${var.zone_id}/656f5a8f4b995272b8658781d39eba26"
}

import {
  to = module.tunnels["maungaraki"].cloudflare_dns_record.routes["admin-test.biz-e.app"]
  id = "${var.zone_id}/e1f2cdeca1382625dbb1bc3c8668ba9c"
}

import {
  to = module.tunnels["maungaraki"].cloudflare_dns_record.routes["dev.biz-e.app"]
  id = "${var.zone_id}/2ad0bf7194dcb676b13b2237ab399af8"
}
