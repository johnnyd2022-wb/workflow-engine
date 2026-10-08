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
  description = "Public hostname => HTTPS origin settings."
  type = map(object({
    service       = string
    no_tls_verify = optional(bool, true)
  }))
  validation {
    condition     = length(var.routes) > 0 && alltrue([for route in values(var.routes) : startswith(route.service, "https://")])
    error_message = "At least one HTTPS origin route is required."
  }
}
