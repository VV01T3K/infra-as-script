#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$root"
export ANSIBLE_CONFIG="$root/ansible.cfg"
engine="${IAC_ENGINE:-tofu}"
case "$engine" in tofu|terraform) ;; *) echo 'IAC_ENGINE must be tofu or terraform' >&2; exit 2 ;; esac
"$engine" -chdir=stages/03-provision/proxmox fmt -check
"$engine" -chdir=stages/03-provision/proxmox validate
for file in scripts/*.sh stages/*/*.sh; do
  bash -n "$file"
done
for file in ansible/playbooks/*.yml stages/02-post-install/*.yml jobs/*.yml; do
  ansible-playbook --syntax-check "$file" -e maintenance_target=guest -e system_update_hosts=pve
done
python3 -m unittest discover -s tests/integration -v
