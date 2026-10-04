# Stage 3: the guests listed under "guests" in inventory/hosts.yml, each created on its Proxmox machine.
# Run: mise run guests   (shows the plan, asks, then applies)
# Needs: stage 2 done for every Proxmox machine (API token + its CA certificate in inventory/proxmox-ca/).
# Config is the truth: a guest removed from the inventory is deleted here too (the plan shows it first).

terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.115.0"
    }
  }

  # The state (what OpenTofu created) is committed to git, encrypted with a key made from
  # state_passphrase in secrets/tofu.sops.yaml. Without the YubiKey it can't be read.
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

# Both come from secrets/tofu.sops.yaml through scripts/with-tofu-secrets.sh, only for this run.
variable "api_tokens" {
  description = "API token of each Proxmox machine (automation@pve!tofu=...), by machine name"
  type        = map(string)
  sensitive   = true
}

variable "state_passphrase" {
  description = "Passphrase that encrypts the state"
  type        = string
  sensitive   = true
}

locals {
  inventory = yamldecode(file("${path.module}/../../inventory/hosts.yml"))
  networks  = local.inventory.all.vars.networks
  machines  = local.inventory.all.children.proxmox.hosts
  # Each guest's own settings on top of the group's ("vars"), like Ansible does.
  guest_group = local.inventory.all.children.guests
  guests      = { for name, guest in local.guest_group.hosts : name => merge(local.guest_group.vars, guest) }
  template    = local.guest_group.vars.lxc_template
}

# One connection per machine, each with its own token. TLS is checked against the machine's own
# Proxmox CA (scripts/with-tofu-secrets.sh trusts inventory/proxmox-ca/*.pem), not skipped.
provider "proxmox" {
  alias     = "machine"
  for_each  = local.machines
  endpoint  = "https://${each.value.address}:8006/"
  api_token = var.api_tokens[each.key]
}

# The Alpine template, downloaded by Proxmox itself on each machine that has guests.
resource "proxmox_download_file" "lxc_template" {
  for_each = toset([for guest in local.guests : guest.node])
  provider = proxmox.machine[each.key]

  node_name          = each.key
  datastore_id       = "local"
  content_type       = "vztmpl"
  url                = local.template.url
  checksum           = local.template.sha512
  checksum_algorithm = "sha512"
}

resource "proxmox_virtual_environment_container" "guest" {
  for_each = local.guests
  provider = proxmox.machine[each.value.node]

  node_name     = each.value.node
  vm_id         = each.value.vmid
  description   = "Managed by stage 3 (infra-as-script)."
  unprivileged  = true
  start_on_boot = true
  started       = true

  # Docker needs nesting. Proxmox lets only root@pam set other features (e.g. keyctl).
  features {
    nesting = true
  }

  operating_system {
    template_file_id = proxmox_download_file.lxc_template[each.value.node].id
    type             = "alpine"
  }

  cpu {
    cores = each.value.cores
  }

  memory {
    dedicated = each.value.memory
  }

  disk {
    datastore_id = "local-lvm"
    size         = each.value.disk
  }

  network_interface {
    name    = "eth0"
    bridge  = "vmbr0"
    vlan_id = local.networks[each.value.network].vlan
  }

  # No root password and no SSH server: Ansible reaches guests through their machine (pct exec).
  initialization {
    hostname = each.key

    ip_config {
      ipv4 {
        address = "${each.value.address}/${split("/", local.networks[each.value.network].subnet)[1]}"
        gateway = local.networks[each.value.network].gateway
      }
    }

    # The router, not our own DNS: a guest must be able to look up names even when DNS is down.
    dns {
      servers = [local.networks[each.value.network].gateway]
    }
  }
}
