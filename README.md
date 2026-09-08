# Local Proxmox infrastructure

Run each stage manually. Installing a host never starts Ansible, and Ansible never
applies OpenTofu. The initial target is the local laptop, `pve` at `10.0.0.50`.

| Folder | Responsibility | Start |
| --- | --- | --- |
| `stages/01-install/` | Static USB installation; optional installer credential regeneration | Boot the prepared USB |
| `stages/02-post-install/` | Update/configure Proxmox, issue an API token, retire installer passwords and SSH access | `ansible-playbook stages/02-post-install/main.yml` |
| `stages/03-provision/` | Provision guests through OpenTofu or Terraform | `bash stages/03-provision/run.sh plan` then `apply` |
| `jobs/` | Independent operating system package updates | `ansible-playbook jobs/update-system.yml -e system_update_hosts=pve` |
| `ansible/roles/` | Shared host, credential, application and maintenance tasks | Used by playbooks |
| `inventory/` | Host addresses and hardware settings | Edit before running |
| `secrets/` | Local installer and runtime credentials; ignored by Git | See `secrets/README.md` |

Use a Linux controller (WSL works), from the repository root:

```bash
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
ansible-galaxy collection install -r ansible/requirements.yml
```

The controller needs Ansible, Bash, flock, OpenSSH, OpenSSL and OpenTofu (or
Terraform). ISO preparation also needs `proxmox-auto-install-assistant` and its
dependencies on a supported Linux machine. Existing application/backup jobs have
additional requirements such as GPG and the GitHub CLI.

1. Prepare the USB once. Review the address, network-interface and disk selectors
   in `stages/01-install/profiles/old-laptop.example.toml` first: installation
   erases the matching target disk. Generate an answer with
   `bash stages/01-install/prepare.sh`. Repeating this keeps the same credentials;
   `--regenerate` replaces only the installer files under `secrets/installer/pve/`
   and retains previous versions there. Rebuild the ISO after regeneration.

   ```bash
   proxmox-auto-install-assistant validate-answer secrets/installer/pve/answer.toml
   proxmox-auto-install-assistant prepare-iso /path/to/proxmox.iso --fetch-from iso --answer-file secrets/installer/pve/answer.toml --output /path/to/proxmox-auto.iso
   ```

   Copy the resulting ISO to the Ventoy USB and match its path in
   `stages/01-install/ventoy/ventoy.json` (copy that JSON to `/ventoy/ventoy.json`
   on the USB). Boot the laptop from USB and wait for automatic installation to
   power it off. Remove USB and power it on. No network callback or post-install
   hook is included. See the [Proxmox automated installer documentation](https://pve.proxmox.com/wiki/Automated_Installation).

2. Run `ansible-playbook stages/02-post-install/main.yml`. It seeds runtime SSH
   access from the installer key when no runtime key exists, updates packages,
   configures the host and access, downloads the guest template, and replaces the
   root password and SSH key. Credential retirement runs once per installed
   machine. A fresh installation must complete this before creating guests.
   For a reinstall, preserve the old runtime secrets/state for recovery and use
   the matching USB key to seed runtime access; never regenerate runtime keys
   while guests still use them. The previous `ansible/playbooks/setup.yml`
   command forwards to this stage.

3. Review `stages/03-provision/proxmox/variables.tf`, then run:

   ```bash
   bash stages/03-provision/run.sh init
   bash stages/03-provision/run.sh plan -out=local.tfplan
   bash stages/03-provision/run.sh apply local.tfplan
   ```

   Set `IAC_ENGINE=terraform` to use Terraform. The wrapper loads runtime API/SSH
   credentials and requires completed credential retirement. The existing Arcane
   LXC keeps its resource address and local state. This stage creates infrastructure
   only; VM definitions can be added alongside the existing LXC when needed.

The router owns DNS records. Provisioning does not create zones or records and
does not override the guest resolver; it inherits Proxmox settings. Addresses
remain static for now. Configure router DNS/reservations separately, avoiding
overlap with its DHCP pool. The installer currently uses `1.1.1.1` for resolution;
change the profile if the router already provides a working resolver.

Run `jobs/update-system.yml` whenever installed system packages need updating.
It uses the configured repositories, without package-version pins in Git, updates
one host at a time, and reboots after package changes. It needs neither guest state
nor application services nor a clean Git checkout. Use an inventory host/group in
`system_update_hosts`; add guest addresses to inventory before targeting guests.
It is a manual job, with no scheduler. Back up workloads beforehand when needed;
the older `ansible/playbooks/update.yml` remains available for the application
workflow that includes backups and service checks.

All mutating Ansible jobs share a checkout lock. Failures leave it in place;
inspect the failure before running `ansible-playbook ansible/playbooks/unlock.yml`.

Host-specific laptop settings live in `inventory/host_vars/pve.yml`; reusable
defaults live in the Proxmox role. Set `proxmox_cluster_member: true` before using
the baseline on a joined cluster member so it does not disable HA/corosync.
OpenTofu node, VM ID, bridge, storage, gateway and template are inputs. The current
credential/application orchestration still uses the single `pve`/`arcane` pair:
adding simultaneous servers also needs separate credential/state scopes and
inventory orchestration. No cluster joining is automated yet.

Legacy application playbooks are outside the three stages. Technitium operations
are disabled by default (`manage_dns: false`, no managed records). Enable them only
if DNS ownership is deliberately changed later.

Validate without contacting the server:

```bash
bash scripts/check.sh
```

Local operations live in `scripts/`: `check.sh` runs syntax checks and the Bun
integration test suite; `backup-controller.sh /absolute/backup.gpg` prompts
for a passphrase and encrypts controller credentials and provisioning state to a
destination outside the checkout. Stop other operations while making a standalone
backup for a consistent snapshot.
Ansible backup workflows call the same script while holding their checkout lock.
Operational helpers use Bash; tests and command mocks use TypeScript with Bun.
Python remains a dependency of Ansible itself.

Run tests with `bun test` (Bun 1.4.2+), or run all checks with
`bash scripts/check.sh`. There are no npm dependencies to install. Run these
integration tests on Linux or inside WSL with Ansible and its collections,
OpenSSH, OpenSSL, GPG, tar, and `proxmox-auto-install-assistant` installed.
Each test uses a temporary checkout and local inventory; service APIs listen only
on loopback. Tests exercise real Ansible orchestration without contacting the
configured laptop, GitHub, or application services. Each test has a three-minute
timeout to accommodate Ansible subprocesses.
