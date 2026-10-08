output "tunnels" {
  description = "Tunnel IDs and DNS routes; connector tokens are not exported."
  value = {
    for key, tunnel in module.tunnels : key => {
      id        = tunnel.id
      hostnames = tunnel.hostnames
    }
  }
}
