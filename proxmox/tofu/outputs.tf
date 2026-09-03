output "arcane" {
  value = {
    lxc_id = proxmox_virtual_environment_container.arcane.vm_id
    ip     = split("/", var.arcane_ip)[0]
    url    = "http://${split("/", var.arcane_ip)[0]}:3552"
  }
}

