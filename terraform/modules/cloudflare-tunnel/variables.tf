variable "account_id" {
  type = string
}

variable "zone_id" {
  type = string
}

variable "name" {
  type = string
}

variable "routes" {
  description = <<-EOT
    Every hostname this tunnel serves => where it goes and how it is exposed.

    service         Origin, as the connector reaches it.
    origin_request  Optional origin settings.
    dns             Whether this root owns the hostname's DNS record. Default true; false
                    for hostnames in zones managed elsewhere.
    access          The Cloudflare Access application in front of the hostname: which
                    policies (keys of access_policy_ids, in order of precedence) and how
                    long a session lasts. Omit it only with public = true.
    public          Must be set to true to publish a hostname this root owns without
                    Access in front of it. Default false.
  EOT
  type = map(object({
    service = string
    origin_request = optional(object({
      connect_timeout          = optional(number)
      disable_chunked_encoding = optional(bool)
      http2_origin             = optional(bool)
      keep_alive_connections   = optional(number)
      keep_alive_timeout       = optional(number)
      no_tls_verify            = optional(bool)
      tcp_keep_alive           = optional(number)
      tls_timeout              = optional(number)
    }))
    dns    = optional(bool, true)
    public = optional(bool, false)
    access = optional(object({
      policies                   = list(string)
      name                       = optional(string)
      session_duration           = optional(string, "24h")
      allowed_idps               = optional(set(string))
      auto_redirect_to_identity  = optional(bool, false)
      http_only_cookie_attribute = optional(bool, true)
    }))
  }))
  validation {
    condition     = length(var.routes) > 0
    error_message = "At least one origin route is required."
  }
  validation {
    condition     = alltrue([for route in values(var.routes) : route.access == null || length(try(route.access.policies, [])) > 0])
    error_message = "An access block must name at least one policy."
  }
}

variable "ingress_order" {
  description = "Hostnames whose ingress rules come first, in this order. Routes not listed follow, sorted by hostname."
  type        = list(string)
  default     = []
  nullable    = false
}

variable "access_policy_ids" {
  description = "Policy key => Cloudflare Access policy ID, for the keys routes refer to."
  type        = map(string)
  default     = {}
  nullable    = false
}
