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
  description = "Complete hostname => origin settings map, including retained shared routes."
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
  }))
  validation {
    condition     = length(var.routes) > 0
    error_message = "At least one origin route is required."
  }
}

variable "ingress_order" {
  description = "Optional explicit hostname ordering; defaults to sorted route keys."
  type        = list(string)
  default     = []
  nullable    = false
}

variable "dns_hostnames" {
  description = "Hostnames whose DNS records this module owns; null means all route hostnames."
  type        = set(string)
  default     = null
}
