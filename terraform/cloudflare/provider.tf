terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "5.27.0"
    }
  }
}

# CLOUDFLARE_API_TOKEN is supplied by ../tf.py from KeePassXC.
provider "cloudflare" {}
