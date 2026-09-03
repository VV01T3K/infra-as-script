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
script verifies its official SHA-256 checksum from `SHA256SUMS`.

## Build and populate the USBs

Create the local installer profile once. It is deliberately ignored by Git
because it contains a reusable root password hash:

```bash
cp profiles/old-laptop.example.toml profiles/old-laptop.toml
```

Replace both placeholders in the copied file. Generate the password hash with
`openssl passwd -6`, and copy the public key from
`~/.ssh/proxmox_bootstrap.pub`.

Run on Linux, or from Ubuntu WSL with the Ventoy drive mounted at `/mnt/d` and
the answer drive mounted at `/mnt/e`:

```bash
cd /mnt/c/Users/Wojtek/Projects/InfraASService/proxmox/usb
bash prepare-usb.sh /mnt/d/ISO/proxmox-ve_9.2-1.iso /mnt/d /mnt/e
```

For new drives, give the script the original ISO, mounted Ventoy partition and
mounted answer partition, in that order. The script:

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
Back up `~/.ssh/proxmox_bootstrap` separately. The repository stores only its
public key.
