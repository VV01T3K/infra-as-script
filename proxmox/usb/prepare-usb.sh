#!/usr/bin/env bash
set -euo pipefail

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 3 || $# > 4 )); then
    echo "usage: $0 PROXMOX_ISO VENTOY_MOUNT ANSWER_MOUNT [ANSWER_PROFILE]" >&2
    exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_iso=$(realpath -- "$1")
ventoy_mount=$(realpath -- "$2")
answer_mount=$(realpath -- "$3")
profile=$(realpath -- "${4:-$script_dir/profiles/old-laptop.toml}")
source_name=proxmox-ve_9.2-1.iso
auto_name=proxmox-ve_9.2-1-auto.iso

command -v proxmox-auto-install-assistant >/dev/null || \
    die "proxmox-auto-install-assistant is not installed"
command -v sha256sum >/dev/null || die "sha256sum is not installed"
[[ -f "$source_iso" ]] || die "ISO not found: $source_iso"
[[ -f "$profile" ]] || die "profile not found: $profile"
[[ $(basename -- "$source_iso") == "$source_name" ]] || \
    die "expected $source_name"
mountpoint -q -- "$ventoy_mount" || die "not a mount point: $ventoy_mount"
mountpoint -q -- "$answer_mount" || die "not a mount point: $answer_mount"
[[ "$ventoy_mount" != "$answer_mount" ]] || die "boot and answer mounts must differ"
[[ -w "$ventoy_mount" ]] || die "mount is not writable: $ventoy_mount"
[[ -w "$answer_mount" ]] || die "mount is not writable: $answer_mount"

answer_source=$(findmnt -n -o SOURCE --target "$answer_mount")
if [[ "$answer_source" == /dev/* ]]; then
    [[ $(lsblk -n -o LABEL "$answer_source" | head -n 1) == proxmox-ais ]] || \
        die "answer partition must have the label proxmox-ais"
fi

read -r expected_hash _ < "$script_dir/SHA256SUMS"
actual_hash=$(sha256sum "$source_iso" | cut -d ' ' -f 1)
[[ "$actual_hash" == "$expected_hash" ]] || die "source ISO checksum mismatch"

proxmox-auto-install-assistant validate-answer "$profile"
mkdir -p -- "$ventoy_mount/ISO" "$ventoy_mount/ventoy" "$ventoy_mount/PROXMOX-CONFIGS"
install -m 0644 -- "$profile" "$answer_mount/answer.toml"
install -m 0644 -- "$profile" "$ventoy_mount/PROXMOX-CONFIGS/$(basename -- "$profile")"
install -m 0644 -- "$script_dir/ventoy/ventoy.json" "$ventoy_mount/ventoy/ventoy.json"

temporary_iso="$ventoy_mount/ISO/.${auto_name}.building.iso"
trap 'rm -f -- "$temporary_iso"' EXIT
rm -f -- "$temporary_iso"
proxmox-auto-install-assistant prepare-iso \
    "$source_iso" \
    --fetch-from partition \
    --partition-label proxmox-ais \
    --output "$temporary_iso"
mv -f -- "$temporary_iso" "$ventoy_mount/ISO/$auto_name"
trap - EXIT

printf 'Boot USB ready: %s\n' "$ventoy_mount/ISO/$auto_name"
printf 'Answer USB ready: %s\n' "$answer_mount/answer.toml"
