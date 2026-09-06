# Infra as Script

Declarative configuration for the `pve.home.arpa` homelab.

| Folder | Purpose |
| --- | --- |
| `ansible/playbooks/` | Commands you run: setup, deploy, update, backup, secrets, pause, verify, unlock, validate |
| `ansible/roles/` | Reusable implementation grouped by responsibility |
| `inventory/` | Host addresses and shared configuration |
| `opentofu/proxmox/` | Proxmox guests and their CPU, memory, disks, and network allocation |
| `apps/` | Compose projects managed by Arcane |
| `installer/` | Manual USB installer materials, separate from automation |
| `secrets/` | Local credentials and the [rotation guide](secrets/README.md) |
| `tests/` | Isolated tests and their Python helpers |
| `docs/` | [Setup](docs/SETUP.md), [maintenance](docs/MAINTENANCE.md), and [recovery](docs/RECOVERY.md) |

Run commands from the repository root. `ansible.cfg` supplies inventory and role paths.

```bash
ansible-galaxy collection install -r ansible/requirements.yml
ansible-playbook ansible/playbooks/setup.yml
# Follow docs/SETUP.md for the OpenTofu plan/apply step.
ansible-playbook ansible/playbooks/deploy.yml
```

OpenTofu owns guest infrastructure. Ansible configures hosts, installs credentials,
and runs operational workflows. Arcane manages application Compose projects;
Arcane itself remains an Ansible-managed Quadlet. The first application is
Technitium DNS at `10.0.0.60`.

Runtime data, OpenTofu state, completed installer profiles, and credential values
stay outside Git. Credentials are grouped by purpose in `secrets/`; installer
profiles stay with the installer. Only the secrets guide is tracked there.

The operational logic is Ansible YAML and OpenTofu HCL. Custom Python is confined
to the test harness; Ansible itself still uses Python to execute modules.

## Future service shortlist

The previous [`komoda-homelab`](https://github.com/VV01T3K/komoda-homelab)
repository remains a catalogue, not a migration checklist. Useful candidates
include Caddy, Cloudflared, Authelia, CrowdSec, Homepage, Uptime Kuma, Beszel,
Gitea, n8n, Open WebUI, Excalidraw, and IT-Tools. Each future service should get
its own directory under `apps/` and an explicit owner for secrets and data.
