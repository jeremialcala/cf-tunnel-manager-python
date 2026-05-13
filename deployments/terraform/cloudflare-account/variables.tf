variable "cloudflare_admin_token" {
  type        = string
  sensitive   = true
  description = "Account-level admin token used only at apply time to create per-tenant tokens."
}

variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare account id this tenant belongs to."
}

variable "tenant_slug" {
  type        = string
  description = "DNS-safe tenant slug (used in token name + Vault path)."
  validation {
    condition     = can(regex("^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$", var.tenant_slug))
    error_message = "tenant_slug must match ^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$"
  }
}

variable "zone_names" {
  type        = list(string)
  description = "DNS zone names this tenant may program (e.g. ['example.com', 'svc.example.com'])."
}

variable "vault_address" {
  type        = string
  description = "Vault HTTP(S) endpoint."
}

variable "vault_kv_mount" {
  type        = string
  description = "Vault KV-v2 mount path (e.g. 'secret')."
  default     = "secret"
}
