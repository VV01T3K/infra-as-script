# Proxmox unattended bootstrap

The installer uses these fixed network settings:

- address: `10.0.0.50/24`
- gateway: `10.0.0.1`
- DNS: `1.1.1.1`
- interface: wired Ethernet matching `en*`

The answer file authorizes the dedicated SSH key at
`~/.ssh/proxmox_bootstrap` on the Linux controller.

## Install and configure

1. Connect the laptop to Ethernet.
2. Insert the Ventoy USB and power on the laptop.
3. Wait for the installer to power the laptop off.
4. Remove the USB and power on the laptop.
5. In Ubuntu WSL, run:

   ```bash
   cd /mnt/c/Users/Wojtek/Projects/InfraASService/proxmox/ansible
   ansible-playbook -i inventory.yml ready.yml
   ```

On a normal Linux machine, enter the repository's `proxmox/ansible` directory
and run the same `ansible-playbook` command.

Ansible waits for SSH, then verifies Proxmox and its API. Open
`https://10.0.0.50:8006` when it finishes.

Prepare a new single-node host before creating guests:

```bash
cd /mnt/c/Users/Wojtek/Projects/InfraASService/proxmox/ansible
ansible-playbook -i inventory.yml site.yml
```

The complete playbook verifies access, configures the no-subscription repository, updates Proxmox,
hides the subscription notice, disables unused cluster services, prevents
laptop suspend, enables SSD trimming, restricts SSH to the bootstrap key,
reboots when needed, checks KVM, storage, and SSD health, creates a dedicated
API token, and enables a management firewall.

The API secret is written with mode `0600` to
`~/.config/infra-as-service/proxmox.env` in WSL. It is never stored in this
project. Load it later with:

```bash
source ~/.config/infra-as-service/proxmox.env
```

## Address plan

- Proxmox host: `10.0.0.50`
- Static VM and LXC addresses: `10.0.0.60` through `10.0.0.99`
- Gateway: `10.0.0.1`
- DNS: `1.1.1.1`
- Domain: `home.arpa`
- Bridge: `vmbr0`

Reserve `10.0.0.50` through `10.0.0.99` outside the router's DHCP pool. The
management firewall accepts host traffic from `10.0.0.0/24`; add another
source before moving administration to a VPN or separate VLAN.

## First managed LXC: Arcane on Podman

The first OpenTofu resource is an unprivileged Debian 13 LXC:

- LXC ID: `200`
- address: `10.0.0.60/24`
- resources: 2 CPU cores, 2 GB RAM, 12 GB disk
- application: Arcane on Podman (Docker is not installed)

From the repository's `proxmox` directory on Linux or WSL, create the LXC and
configure the application with one command:

```bash
bash deploy-arcane.sh
```

The command requires `gh` to be logged in as a repository administrator. On
its first run it generates a dedicated SSH key outside the project and adds
only the public half to GitHub as a read-only deploy key. It then loads the
Proxmox API token, lets Ansible ensure the pinned Debian template exists, runs
OpenTofu, waits for SSH, installs Podman, and verifies Arcane. Open
`http://10.0.0.60:3552` when it completes.

The same command also prepares Technitium's local secret and data directories,
then asks Arcane to sync [`apps/technitium/compose.yaml`](../apps/technitium/compose.yaml)
from the private GitHub repository. Its DNS service listens on `10.0.0.60`
TCP/UDP port `53`, and its web console is at `http://10.0.0.60:5380`. Sign in
as `admin`; read the generated password with:

```bash
cat ~/.config/infra-as-service/technitium-admin-password
```

Ansible owns Arcane's Quadlet and the host-side secret/data preparation. Arcane
owns Technitium's Compose lifecycle and checks Git every five minutes. The
repository contains no credentials or DNS data; Technitium keeps settings and
zones in `/var/lib/technitium/config` on the LXC.

OpenTofu state remains local under `tofu/` and is excluded by `.gitignore`.
Keep that state file: it is required for safe updates and destruction. To view
the proposed changes later, run:

```bash
source ~/.config/infra-as-service/proxmox.env
export TF_VAR_ssh_public_key="$(ssh-keygen -y -f ~/.ssh/proxmox_bootstrap)"
tofu -chdir=tofu plan
```

The files and Linux command needed to recreate the Ventoy installer are in
[`usb/`](usb/README.md).
