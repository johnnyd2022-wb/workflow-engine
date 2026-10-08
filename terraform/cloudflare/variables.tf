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

variable "production_access_emails" {
  description = "Who Cloudflare Access lets through to production (biz-e.app)."
  type        = set(string)
  default     = ["johnny@whistlebird.co.nz", "niko@whistlebird.co.nz"]
  validation {
    condition     = length(var.production_access_emails) > 0
    error_message = "At least one address must be allowed, or nobody can reach production."
  }
}
