output "id" {
  value = cloudflare_zero_trust_tunnel_cloudflared.this.id
}

output "hostnames" {
  value = sort(keys(var.routes))
}
