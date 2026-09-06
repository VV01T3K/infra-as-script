# Proxmox unattended bootstrap

The installer uses these fixed network settings:

- address: `10.0.0.50/24`
- gateway: `10.0.0.1`
- DNS: `1.1.1.1`
- interface: wired Ethernet matching `en*`

The answer file authorizes the dedicated SSH key at
`../secrets/proxmox/proxmox_bootstrap` on the Linux controller.

## Install and configure

Prepare the two USBs manually using [the installer guide](../installer/README.md) first.

1. Connect the laptop to Ethernet.
2. Insert the Ventoy USB and power on the laptop.
3. Wait for the installer to power the laptop off.
4. Remove the USB and power on the laptop.
5. In Ubuntu WSL, run:

   ```bash
   cd /mnt/c/Users/Wojtek/Projects/infra-as-script/proxmox/ansible
   ansible-playbook -i inventory.yml ready.yml
   ```

On a normal Linux machine, enter the repository's `proxmox/ansible` directory
and run the same `ansible-playbook` command.

Ansible waits for SSH, then verifies Proxmox and its API. Open
`https://10.0.0.50:8006` when it finishes.

Prepare a new single-node host before creating guests:

```bash
cd /mnt/c/Users/Wojtek/Projects/infra-as-script/proxmox/ansible
ansible-playbook -i inventory.yml site.yml
```

The complete playbook verifies access, configures the no-subscription repository, updates Proxmox,
hides the subscription notice, disables unused cluster services, prevents
laptop suspend, enables SSD trimming, restricts SSH to the bootstrap key,
reboots when needed, checks KVM, storage, and SSD health, creates a dedicated
API token, and enables a management firewall. It then replaces the installer
root password and SSH key once per installed host, before guest provisioning.
See [credential management](../secrets/README.md) for existing deployments and reinstalls.

The API secret is written with mode `0600` to
`../secrets/proxmox/proxmox.env` in WSL. This folder is ignored by Git. From `proxmox/`, load it with:

```bash
source ../secrets/proxmox/proxmox.env
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

From the repository's `proxmox/` directory on Linux or WSL, provision the guest
with OpenTofu, then configure services with Ansible:

```bash
export PATH="$HOME/.local/bin:$HOME/.local/usr/bin:$PATH"
source ../secrets/proxmox/proxmox.env
export TF_VAR_ssh_public_key="$(ssh-keygen -y -f ../secrets/proxmox/proxmox_bootstrap)"
ansible-playbook -i ansible/inventory.yml ansible/template.yml
tofu -chdir=tofu init
tofu -chdir=tofu apply
ansible-playbook -i ansible/inventory.yml ansible/deploy.yml
```

The controller needs OpenTofu, Ansible, Python 3, GitHub CLI, OpenSSH tools,
and `dig` (`sudo apt install dnsutils` on Ubuntu/WSL). OpenTofu displays its
plan and asks before applying. Its LXC resource has `prevent_destroy` protection.
OpenTofu owns guest resources; Ansible owns configuration and operational workflows.
Do not run OpenTofu changes concurrently with deployment or maintenance.

The deployment playbook requires `gh` to be logged in as a repository
administrator. It generates a dedicated key in `secrets/arcane/` and registers
only its public half with GitHub as a read-only deploy key. It reads the applied
guest address from OpenTofu, installs Podman, and configures Arcane. Open
`http://10.0.0.60:3552` when it completes. Use the [maintenance playbook](UPDATES.md)
for updates to an existing installation so backups run first.

The deployment playbook also prepares Technitium's local secret and data directories,
then asks Arcane to sync [`apps/technitium/compose.yaml`](../apps/technitium/compose.yaml)
from the private GitHub repository. Its DNS service listens on `10.0.0.60`
TCP/UDP port `53`, and its web console is at `http://10.0.0.60:5380`. Sign in
as `admin`; read the generated password with:

```bash
cat ../secrets/technitium/technitium-admin-password
```

Ansible owns Arcane's Quadlet and the host-side secret/data preparation. Arcane
owns Technitium's Compose lifecycle; Git sync is explicitly triggered after backups. The
Git history contains no credentials or DNS data; Technitium keeps settings and
zones in `/var/lib/technitium/config` on the LXC.

Ansible also configures Technitium as the replacement for the previous
AdGuard-and-Unbound pair. It performs recursive resolution directly, validates
DNSSEC, minimizes QNAMEs, serves stale cached answers during upstream trouble,
and permits recursion only from localhost and `10.0.0.0/24`. Blocking uses
HaGeZi Pro++ and the CERT Polska warning list, updated every 24 hours. The
managed local records are:

- `pve.home.arpa` -> `10.0.0.50`
- `arcane.home.arpa` -> `10.0.0.60`
- `dns.home.arpa` -> `10.0.0.60`

Set `10.0.0.60` as the DNS server in the router's DHCP configuration after
testing it from one client. Keep another DNS address out of DHCP if you want
blocking to apply consistently; clients otherwise bypass Technitium at random.

OpenTofu state remains local under `tofu/` and is excluded by `.gitignore`.
Keep that state file: it is required for safe updates and destruction. To view
the proposed changes later, run:

```bash
source ../secrets/proxmox/proxmox.env
export TF_VAR_ssh_public_key="$(ssh-keygen -y -f ../secrets/proxmox/proxmox_bootstrap)"
tofu -chdir=tofu plan
```

Deployment loads an in-memory Ansible inventory from OpenTofu's applied
`arcane` output. Ansible uses that address for Arcane's URL and the DNS records;
the Proxmox address comes from `ansible/inventory.yml`. Shared record definitions
live in `ansible/group_vars/all.yml`. Ansible owns the complete A record sets at
those three names and reapplies their address, TTL, comments, and requested PTR
records on each run. Retired names and old reverse records are not deleted
automatically; remove them explicitly when changing the address plan.

The final deployment step tests local and external DNS over UDP and TCP from
the controller, plus the managed reverse records. To repeat those checks:

```bash
ansible-playbook -i ansible/inventory.yml ansible/verify.yml
```

To check blocking too, set `dns_blocked_test_name` in the shared variables to a
known domain in a downloaded block list, or pass `-e dns_blocked_test_name=DOMAIN`
to the verification playbook. This optional query is explicitly reported as
skipped until configured. The controller must reach the guest from an allowed
LAN address.

## Ansible entry points

Run these from `proxmox/` with `ansible-playbook -i ansible/inventory.yml ansible/NAME.yml`:

| Playbook | Purpose |
| --- | --- |
| `site.yml` | Bootstrap the Proxmox host and retire installer credentials |
| `secrets.yml` | Generate or rotate credentials; see ../secrets/README.md |
| `template.yml` | Prepare the Debian template before OpenTofu apply |
| `deploy.yml` | Configure services after provisioning |
| `update.yml` | Back up and update one component; see UPDATES.md for variables |
| `pause.yml` | Disable automatic application sync |
| `backup-all.yml` | Back up controller and guest; see RECOVERY.md for destinations |
| `verify.yml` | Check service health and DNS using applied inventory |
| `validate.yml` | Validate configuration and run local tests |

Deployment, update, pause, and combined backup share a checkout-local lock.
See [UPDATES.md](UPDATES.md) for inspecting and releasing it after a failed run.
Other playbooks are reusable building blocks; they do not acquire that lock.

## Validation and recovery

For routine host, guest, Arcane, and Technitium updates, use the
[update workflow](UPDATES.md). It backs up before changing the selected component
and checks service health afterward. Existing installations should run its
`pause.yml` step before publishing a new application version.

Run `ansible-playbook ansible/validate.yml` for OpenTofu format/validation,
Ansible syntax, and local integration tests (requires PyYAML and GPG). On a fresh checkout, run `tofu -chdir=tofu init -backend=false`
first to install the pinned provider. These checks do not deploy infrastructure.

Use the [backup and recovery workflow](RECOVERY.md) before putting important
data on this guest. It includes an explicit Proxmox backup playbook, encrypted
controller backups, and an isolated restore drill. A destination and recurring
backup schedule still need to be chosen for your hardware.

Manual installer materials and USB file-placement instructions live separately
in [`installer/`](../installer/README.md). USB preparation is not part of these playbooks.
