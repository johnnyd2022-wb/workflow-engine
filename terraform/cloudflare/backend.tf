terraform {
  # Connection credentials come from PG_CONN_STR / PGPASSWORD, never HCL.
  # Other Terraform roots must choose their own schema_name.
  backend "pg" {
    schema_name = "cloudflare"
  }
}
