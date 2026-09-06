# Manual Proxmox installer setup

Prepare the USBs yourself before running the infrastructure automation.
This folder contains the installer configuration and file-placement guide;
Ansible and OpenTofu start after Proxmox is installed.

## Files to keep here

- `proxmox-ve_9.2-1-auto.iso`: the prepared installer image, copied back from
  your existing Ventoy USB. ISO files are ignored by Git. This image is not
  currently present in this checkout.
- `ventoy/ventoy.json`: Ventoy menu configuration.
- `profiles/old-laptop.example.toml`: an example profile for reference. Use the completed
  private profile at `profiles/old-laptop.toml` for installation.
- `SOURCE-SHA256SUMS`: checksum of the original, unmodified ISO for reference;
  it does not verify the prepared `-auto.iso` image.

Use the prepared `-auto.iso`, which is configured to read `answer.toml` from a
partition labeled `proxmox-ais`. The original `proxmox-ve_9.2-1.iso` is not a
replacement for that prepared image. You do not need the original ISO on the USB.

## Where the files go

Use two USB drives: one with Ventoy already installed, and a separate FAT32
answer drive. Set the answer drive's filesystem label to exactly `proxmox-ais`.

| Source in this repo | Destination |
| --- | --- |
| `installer/proxmox-ve_9.2-1-auto.iso` | Ventoy USB: `ISO/proxmox-ve_9.2-1-auto.iso` |
| `installer/ventoy/ventoy.json` | Ventoy USB: `ventoy/ventoy.json` |
| `installer/profiles/old-laptop.toml` | Answer USB: `answer.toml` at the drive root |

Create the `ISO` and `ventoy` folders on the Ventoy drive if needed. Copy the
files using your file manager; rename the private profile to `answer.toml` on
the answer drive. No `PROXMOX-CONFIGS` copy is needed on the Ventoy drive.

```text
Ventoy USB                     Answer USB (label: proxmox-ais)
  ISO/                           answer.toml
    proxmox-ve_9.2-1-auto.iso
  ventoy/
    ventoy.json
```

If the prepared ISO is still on your existing USB, copy it into this folder to
keep a local copy for next time. Changing the host profile only requires
replacing `answer.toml`; the prepared ISO stays the same.

## Install, then automate

1. Review the private profile: it installs to the matching non-USB disk and
   erases that disk. It configures `pve.home.arpa` at `10.0.0.50/24`, gateway
   `10.0.0.1`, and your bootstrap SSH key. Do not use the example placeholders.
2. Connect Ethernet and both USBs to the target laptop, then boot from Ventoy.
3. Select the prepared Proxmox image if it does not start automatically.
4. Wait for the installer to power the laptop off. Remove both USBs and power
   it on again.
5. Continue with the host setup commands in [proxmox/README.md](../proxmox/README.md).

Completed profiles live in `installer/profiles/`. They are git-ignored and included
in controller backups. Placeholder examples remain tracked.
