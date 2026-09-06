# Recreate the Proxmox installer USBs

This directory contains every small file needed to reproduce the Proxmox
installer setup. ISO files and the private SSH key are intentionally absent.
The setup uses two drives so Proxmox can mount the answer filesystem while
Ventoy keeps its own filesystem busy.

## Requirements

- a USB drive with Ventoy installed
- a separate FAT32 USB drive labeled `proxmox-ais`
- `proxmox-auto-install-assistant`
- the original `proxmox-ve_9.2-1.iso`

On Debian 13 or Ubuntu 24.04 and newer, install the same assistant version used
for this USB:

```bash
sudo apt-get update
sudo apt-get install -y curl xorriso
package=/tmp/proxmox-auto-install-assistant_9.0.6_amd64.deb
curl -fLo "$package" http://download.proxmox.com/debian/pve/dists/trixie/pve-no-subscription/binary-amd64/proxmox-auto-install-assistant_9.0.6_amd64.deb
echo "5720c31f5a8fa1b7b471f32f94e262879b276215d27463771db04bc749af8466  $package" | sha256sum -c -
sudo apt-get install -y "$package"
```

Download the original ISO from
`https://enterprise.proxmox.com/iso/proxmox-ve_9.2-1.iso`. The preparation
playbook verifies its official SHA-256 checksum from `SHA256SUMS`.

## Build and populate the USBs

Create the local installer profile once. It is deliberately ignored by Git
because it contains a reusable root password hash:

```bash
mkdir -p ../../secrets
cp profiles/old-laptop.example.toml ../../secrets/proxmox/old-laptop.toml
```

Replace both placeholders in the copied file. Generate the password hash with
`openssl passwd -6`, and derive the public key with
`ssh-keygen -y -f ../../secrets/proxmox/proxmox_bootstrap`.

Run on Linux, or from Ubuntu WSL with the Ventoy drive mounted at `/mnt/d` and
the answer drive mounted at `/mnt/e`:

```bash
cd /mnt/c/Users/Wojtek/Projects/infra-as-script/proxmox/usb
ansible-playbook ../ansible/prepare-usb.yml \
  -e source_iso=/mnt/d/ISO/proxmox-ve_9.2-1.iso \
  -e ventoy_mount=/mnt/d \
  -e answer_mount=/mnt/e
```

For new drives, supply the original ISO and both mounted partitions using the
variables above. Override `answer_profile` to select a different profile. The playbook:

1. validates the source ISO and answer profile;
2. copies `answer.toml` to the separate answer drive;
3. copies `ventoy.json` to the boot drive;
4. creates an automated ISO configured to read `answer.toml` from the partition
   labeled `proxmox-ais`.

It overwrites only these known files:

- answer USB: `answer.toml`
- Ventoy USB: `PROXMOX-CONFIGS/old-laptop.toml`
- Ventoy USB: `ventoy/ventoy.json`
- Ventoy USB: `ISO/proxmox-ve_9.2-1-auto.iso`

To switch profiles without rebuilding the ISO, copy another profile to the
answer USB root as `answer.toml`.

The current setup was built with `proxmox-auto-install-assistant 9.0.6`.
The controller backup includes `secrets/`, including the SSH key and installer profile.
