# Temporary resource to demonstrate MR plan -> approval -> merge -> apply.
# Remove this file in a follow-up MR to demonstrate the destroy workflow.
resource "cloudflare_dns_record" "ci_demo" {
  zone_id = var.zone_id
  name    = "_terraform-ci-demo.biz-e.app"
  type    = "TXT"
  content = "workflow-engine Terraform CI demo"
  ttl     = 60
  proxied = false
  comment = "Temporary Terraform CI demo; remove after testing."
}
