variable "account_id" {
  description = "Cloudflare account ID, loaded from KeePassXC by the wrapper."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-fA-F0-9]{32}$", var.account_id))
    error_message = "account_id must be a 32-character Cloudflare account ID."
  }
}

variable "zone_id" {
  description = "Cloudflare zone ID for biz-e.app, loaded from KeePassXC."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-fA-F0-9]{32}$", var.zone_id))
    error_message = "zone_id must be a 32-character Cloudflare zone ID."
  }
}
