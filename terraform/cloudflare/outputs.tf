output "tunnel" {
  description = "The tunnel and what it serves; connector tokens are not exported."
  value = {
    id          = module.tunnel.id
    published   = module.tunnel.published
    routed_only = module.tunnel.routed_only
  }
}
