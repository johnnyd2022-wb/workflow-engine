output "id" {
  value = cloudflare_zero_trust_tunnel_cloudflared.this.id
}

output "hostnames" {
  value = sort(tolist(local.dns_hostnames))
}

output "protected_hostnames" {
  description = "Hostnames with a Cloudflare Access application in front of them."
  value       = sort(keys(local.access))
}
