# The router (UniFi UCG Ultra): networks, firewall zones and policies, switch ports and fixed client
# addresses, from inventory/hosts.yml and this file.
# Run: mise run network   (shows the plan, asks, then applies)
# Config is the truth: whatever is managed here and removed from here is removed on the router too.
# Not managed (set by hand, see the handoff doc): UniFi OS itself (updates, admins, remote access),
# the built-in zones and policies, the WAN ports, and controller settings.

terraform {
  required_providers {
    unifi = {
      source  = "filipowm/unifi"
      version = "1.1.0"
    }
  }

  # Same as stage 3: the state is committed, encrypted with state_passphrase from secrets/tofu.sops.yaml.
  encryption {
    key_provider "pbkdf2" "passphrase" {
      passphrase = var.state_passphrase
    }
    method "aes_gcm" "passphrase" {
      keys = key_provider.pbkdf2.passphrase
    }
    state {
      method   = method.aes_gcm.passphrase
      enforced = true
    }
    plan {
      method   = method.aes_gcm.passphrase
      enforced = true
    }
  }
}

# Both from secrets/tofu.sops.yaml through scripts/with-tofu-secrets.sh, only for this run.
variable "unifi" {
  description = "Login of the router's local account infra-as-script (role: Network Site Admin, local only)"
  type        = object({ username = string, password = string })
  sensitive   = true
}

variable "state_passphrase" {
  description = "Passphrase that encrypts the state"
  type        = string
  sensitive   = true
}

locals {
  inventory = yamldecode(file("${path.module}/../inventory/hosts.yml")).all
  networks  = { for key, n in local.inventory.vars.networks : key => n if !try(n.planned, false) }
  # The DNS servers DHCP hands out for dns: technitium.
  technitium = [for name in keys(local.inventory.children.dns.hosts) : local.inventory.children.guests.hosts[name].address]
}

# The router's certificate is issued for "unifi.local" only, not for its address, so Go can't check it
# here. On the local network for now; to be replaced by a proper certificate (handoff doc, open items).
provider "unifi" {
  api_url        = "https://${local.inventory.vars.unifi.address}"
  username       = var.unifi.username
  password       = var.unifi.password
  allow_insecure = true
}

# --- Networks ---

resource "unifi_network" "lan" {
  for_each = local.networks

  name    = each.value.unifi_name
  purpose = "corporate"
  subnet  = "${each.value.gateway}/${split("/", each.value.subnet)[1]}"
  vlan_id = each.value.vlan == 1 ? null : each.value.vlan # VLAN 1 is the untagged default network

  dhcp_enabled = true
  dhcp_start   = each.value.dhcp.start
  dhcp_stop    = each.value.dhcp.stop
  dhcp_lease   = 86400
  dhcp_dns     = each.value.dhcp.dns == "technitium" ? local.technitium : []
  domain_name  = try(each.value.dhcp.domain, local.inventory.vars.domain)

  multicast_dns = true # mDNS between networks (printers, casting)

  # IPv6 is off on these networks; these keep the router's values instead of the provider's defaults.
  dhcp_v6_dns_auto           = false
  dhcp_v6_lease              = 0
  ipv6_ra_preferred_lifetime = 0
  ipv6_ra_valid_lifetime     = 0
}

# --- Firewall zones and policies ---
# The built-in zones (Internal = Default + Personal, External, Gateway, ...) belong to the router.

data "unifi_firewall_zone" "internal" {
  name = "Internal"
}

resource "unifi_firewall_zone" "infra" {
  name     = "Infra"
  networks = [unifi_network.lan["infra"].id]
}

# auto_allow_return_traffic: also allow the replies. Without it, e.g. DNS answers from Infra never
# reach Personal (the provider's default is false).
resource "unifi_firewall_zone_policy" "internal_to_infra" {
  name                      = "Allow Internal to Infra"
  action                    = "ALLOW"
  protocol                  = "all"
  auto_allow_return_traffic = true
  source = {
    zone_id = data.unifi_firewall_zone.internal.id
  }
  destination = {
    zone_id = unifi_firewall_zone.infra.id
  }
}

# --- Switch ports ---
# Every setting is written out (today's values), so a plan shows only what really changes.
# forward "all" + tagged "auto" = the native network untagged plus every VLAN tagged (trunk).
# forget_on_destroy = false: removing a device from this file must never un-adopt it.

resource "unifi_device" "flex_mini" {
  name              = "USW Flex Mini"
  mac               = "58:d6:1f:5a:44:69"
  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    number                = 1
    name                  = "uplink (UCG port 1)"
    native_networkconf_id = unifi_network.lan["management"].id
    forward               = "all"
    tagged_vlan_mgmt      = "auto"
    setting_preference    = "auto"
  }

  port_override {
    number                = 3
    name                  = "torus"
    native_networkconf_id = unifi_network.lan["management"].id
    forward               = "all"
    tagged_vlan_mgmt      = "auto"
    setting_preference    = "auto"
  }

  port_override {
    number                = 4
    name                  = "Port 4"
    native_networkconf_id = unifi_network.lan["personal"].id
    forward               = "native"
    tagged_vlan_mgmt      = "block_all"
    setting_preference    = "auto"
  }

  port_override {
    number                = 5
    name                  = "kestrel"
    native_networkconf_id = unifi_network.lan["management"].id
    forward               = "all"
    tagged_vlan_mgmt      = "auto"
    setting_preference    = "auto"
  }
}

resource "unifi_device" "gateway" {
  name              = "UCG Ultra"
  mac               = "74:fa:29:55:44:53"
  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    number                = 1
    name                  = "Flex Mini"
    native_networkconf_id = unifi_network.lan["management"].id
    forward               = "all"
    tagged_vlan_mgmt      = "auto"
    setting_preference    = "auto"
  }

  port_override {
    number                = 2
    name                  = "Port 2 (Archer AP)"
    native_networkconf_id = unifi_network.lan["personal"].id
    forward               = "native"
    tagged_vlan_mgmt      = "block_all"
    setting_preference    = "manual"
  }

  # forward "customize" with nothing excluded: Personal untagged plus every VLAN tagged.
  port_override {
    number                = 4
    name                  = "desk"
    native_networkconf_id = unifi_network.lan["personal"].id
    forward               = "customize"
    tagged_vlan_mgmt      = "auto"
    setting_preference    = "auto"
  }
}

# --- Fixed client addresses ---
# Every machine in the inventory gets its address by MAC (it also has it set statically), named after it.

resource "unifi_user" "machine" {
  for_each = local.inventory.children.proxmox.hosts

  mac        = each.value.mac
  name       = each.key
  fixed_ip   = each.value.address
  network_id = unifi_network.lan[each.value.network].id
}

moved {
  from = unifi_user.proxmox
  to   = unifi_user.machine["kestrel"]
}

# The Wi-Fi access point (not a machine of the inventory).
resource "unifi_user" "archer" {
  mac        = "3c:52:a1:78:1a:ab"
  name       = "ArcherC6U"
  fixed_ip   = "10.0.0.2"
  network_id = unifi_network.lan["personal"].id
}
