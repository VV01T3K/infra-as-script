#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
engine="${IAC_ENGINE:-tofu}"
case "$engine" in tofu|terraform) ;; *) echo 'IAC_ENGINE must be tofu or terraform' >&2; exit 2 ;; esac
if [[ ! -s "$root/secrets/proxmox/installed-machine-id" ]]; then
  echo 'Complete stage 02 before provisioning.' >&2
  exit 1
fi
source "$root/secrets/proxmox/proxmox.env"
export TF_VAR_ssh_public_key
TF_VAR_ssh_public_key="$(cat "$root/secrets/proxmox/proxmox_bootstrap.pub")"
exec "$engine" "-chdir=$root/stages/03-provision/proxmox" "$@"
