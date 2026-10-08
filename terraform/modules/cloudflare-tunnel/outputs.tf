output "id" {
  value = cloudflare_zero_trust_tunnel_cloudflared.this.id
}

output "published" {
  description = "Hostnames with a DNS record and a Cloudflare Access application."
  value       = sort(tolist(local.published))
}

output "routed_only" {
  description = "Hostnames this tunnel serves whose DNS and Access are managed elsewhere."
  value       = sort(tolist(setsubtract(local.hostnames, local.published)))
}
