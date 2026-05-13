output "tenant_slug"        { value = var.tenant_slug }
output "cf_account_id"      { value = var.cloudflare_account_id }
output "cf_zone_ids"        { value = local.zone_ids }
output "vault_secret_path"  {
  value = "${var.vault_kv_mount}/data/tenants/${var.tenant_slug}/cf_token"
}
