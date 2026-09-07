variable "ssh_public_key" {
  description = "SSH public key installed for root in the LXC."
  type        = string
  sensitive   = true
}

variable "arcane_ip" {
  description = "Static IPv4 address and prefix for the Arcane LXC."
  type        = string
  default     = "10.0.0.60/24"
}


variable "node_name" {
  type    = string
  default = "pve"
}

variable "vm_id" {
  type    = number
  default = 200
}

variable "gateway" {
  type    = string
  default = "10.0.0.1"
}

variable "bridge" {
  type    = string
  default = "vmbr0"
}

variable "datastore_id" {
  type    = string
  default = "local-lvm"
}

variable "template_file_id" {
  type    = string
  default = "local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst"
}
