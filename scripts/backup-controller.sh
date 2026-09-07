#!/usr/bin/env bash
set -euo pipefail
umask 077
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
destination="${1:-}"
[[ $# == 1 && "$destination" == /* ]] || { echo 'Usage: bash scripts/backup-controller.sh /absolute/backup.gpg' >&2; exit 2; }
[[ ! -e "$destination" && ! -L "$destination" ]] || { echo 'Backup destination already exists' >&2; exit 1; }
parent="$(cd -- "$(dirname -- "$destination")" && pwd -P)"
case "$parent" in "$root"|"$root"/*) echo 'Choose a backup destination outside the checkout' >&2; exit 2 ;; esac
for input in stages/01-install/profiles secrets secrets/proxmox/proxmox_bootstrap stages/03-provision/proxmox/terraform.tfstate; do
  [[ -e "$root/$input" ]] || { echo "Missing backup input: $input" >&2; exit 1; }
done
# Ansible supplies stdin; direct interactive use prompts without echoing the value.
if [[ -t 0 ]]; then
  read -r -s -p 'Backup passphrase: ' passphrase
  printf '\n' >&2
  read -r -s -p 'Confirm passphrase: ' confirmation
  printf '\n' >&2
  [[ "$passphrase" == "$confirmation" ]] || { echo 'Passphrases differ' >&2; exit 1; }
else
  IFS= read -r passphrase || [[ -n "${passphrase:-}" ]]
fi
[[ -n "$passphrase" ]] || { echo 'A backup passphrase is required' >&2; exit 1; }
staging="$(mktemp "$(dirname -- "$destination")/.controller-encrypted-XXXXXX")"
trap 'rm -f -- "$staging"' EXIT
tar -czf - -C "$root" --exclude=secrets/proxmox/maintenance.lock.d \
  secrets stages/01-install/profiles -C "$root/stages/03-provision/proxmox" terraform.tfstate |
  gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 \
    --symmetric --cipher-algo AES256 --output "$staging" 3<<<"$passphrase"
# Hard-link publication cannot overwrite an existing file, even after a race.
ln -T -- "$staging" "$destination"
