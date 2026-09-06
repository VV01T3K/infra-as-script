locals {
  node_name = "pve"
  vm_id     = 200
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
    datastore_id = "local-lvm"
    size         = 12
  }

  initialization {
    hostname = "arcane"

    dns {
      domain  = "home.arpa"
      servers = ["1.1.1.1"]
    }

    ip_config {
      ipv4 {
        address = var.arcane_ip
        gateway = "10.0.0.1"
      }
    }

    user_account {
      keys = [trimspace(var.ssh_public_key)]
    }
  }

  network_interface {
    name   = "eth0"
    bridge = "vmbr0"
  }

  operating_system {
    template_file_id = "local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst"
    type             = "debian"
  }

  startup {
    order      = 10
    up_delay   = 15
    down_delay = 60
  }
}
