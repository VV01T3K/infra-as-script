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

