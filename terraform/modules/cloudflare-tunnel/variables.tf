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

variable "public_paths" {
  description = <<-EOT
    "host/path" entries that skip Access, for clients that cannot sign in through a browser
    (an AI assistant's background calls to an OAuth or MCP endpoint). Each gets its own Access
    application with a bypass policy; a path application wins over its host's founders-only one,
    so the rest of the host stays behind Access. A trailing /* covers everything under a path.
    The host must be published by this module.
  EOT
  type        = list(string)
  default     = []
  validation {
    condition = alltrue([
      for entry in var.public_paths : can(regex("^[a-z0-9.-]+/[A-Za-z0-9._~/-]+(/\\*)?$", entry))
    ])
    error_message = "Each public path is host/path, e.g. test.biz-e.app/oauth/token or mcp.biz-e.app/.well-known/*."
  }
}
