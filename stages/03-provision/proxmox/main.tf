locals {
  node_name = var.node_name
  vm_id     = var.vm_id
}

resource "proxmox_virtual_environment_container" "arcane" {
  lifecycle {
    prevent_destroy = true
  }

  node_name   = local.node_name
  vm_id       = local.vm_id
  description = "Arcane container management panel on Podman; managed by OpenTofu and Ansible"

  unprivileged  = true
  started       = true
  start_on_boot = true
  tags          = ["arcane", "managed-by-opentofu", "podman"]

  features {
    nesting = true
  }

  cpu {
    cores = 2
  }

  memory {
    dedicated = 2048
    swap      = 512
  }

  disk {
    datastore_id = var.datastore_id
    size         = 12
  }

  initialization {
    hostname = "arcane"

    ip_config {
      ipv4 {
        address = var.arcane_ip
        gateway = var.gateway
      }
    }

    user_account {
      keys = [trimspace(var.ssh_public_key)]
    }
  }

  network_interface {
    name   = "eth0"
    bridge = var.bridge
  }

  operating_system {
    template_file_id = var.template_file_id
    type             = "debian"
  }

  startup {
    order      = 10
    up_delay   = 15
    down_delay = 60
  }
}
