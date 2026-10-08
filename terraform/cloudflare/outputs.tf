output "tunnels" {
  description = "Tunnel IDs, DNS routes and which hostnames sit behind Access; connector tokens are not exported."
  value = {
    for key, tunnel in module.tunnels : key => {
      id        = tunnel.id
      hostnames = tunnel.hostnames
      protected = tunnel.protected_hostnames
    }
  }
}
