# =====================================================================
# Per-tenant Cloudflare account bootstrap.
# =====================================================================
# Creates / asserts:
# - the account-owned API token with Tunnel:Edit + DNS:Edit on the listed zones
# - exposes the token in the configured secrets backend (Vault here)
# - records the tenant in the orchestrator DB (out of scope: see ./post-apply.sh)
# =====================================================================

terraform {
  required_version = ">= 1.7.0"
  required_providers {
    cloudflare = { source = "cloudflare/cloudflare", version = "~> 4.40" }
    vault      = { source = "hashicorp/vault",       version = "~> 4.4"  }
    random     = { source = "hashicorp/random",      version = "~> 3.6"  }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_admin_token
}

provider "vault" {
  address = var.vault_address
}

# Discover zone IDs from names (so callers pass friendly names)
data "cloudflare_zones" "managed" {
  for_each = toset(var.zone_names)
  filter { name = each.value }
}

# Build the policy: Tunnel:Edit on account, DNS:Edit on listed zones.
data "cloudflare_api_token_permission_groups" "all" {}

locals {
  zone_ids = [for z in data.cloudflare_zones.managed : z.zones[0].id]
}

resource "cloudflare_api_token" "tenant" {
  name = "tunnel-orchestrator/${var.tenant_slug}"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.account["Cloudflare Tunnel Write"],
      data.cloudflare_api_token_permission_groups.all.account["Account Settings Read"],
    ]
    resources = {
      "com.cloudflare.api.account.${var.cloudflare_account_id}" = "*"
    }
  }

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.zone["DNS Write"],
    ]
    resources = { for zid in local.zone_ids : "com.cloudflare.api.account.zone.${zid}" => "*" }
  }
}

resource "vault_kv_secret_v2" "cf_token" {
  mount = var.vault_kv_mount
  name  = "tenants/${var.tenant_slug}/cf_token"
  data_json = jsonencode({
    token      = cloudflare_api_token.tenant.value
    account_id = var.cloudflare_account_id
    rotated_at = timestamp()
  })
}
