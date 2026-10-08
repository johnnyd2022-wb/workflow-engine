variable "account_id" {
  type = string
}

variable "zone_id" {
  type = string
}

variable "zone_name" {
  description = "The zone this root owns, e.g. biz-e.app. Hostnames in it get a DNS record and an Access application."
  type        = string
}

variable "name" {
  description = "Tunnel name."
  type        = string
}

variable "routes" {
  description = <<-EOT
    Hostname => origin, as the connector reaches it. That is all a site needs.

    A hostname in var.zone_name is published by this module: Access application first, then
    the tunnel route and the DNS record. A hostname in any other zone only gets its tunnel
    route; its DNS record and Access application are managed elsewhere.
  EOT
  type        = map(string)
  validation {
    condition     = length(var.routes) > 0
    error_message = "At least one route is required."
  }
}
