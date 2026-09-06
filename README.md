# Infra as Script

Declarative configuration for the `pve.home.arpa` homelab.

## Ownership

- OpenTofu owns Proxmox guests and their hardware/network allocation.
- Ansible prepares Proxmox, bootstraps hosts, and installs local secrets.
- Arcane syncs application Compose projects from `apps/` and controls their lifecycle on Podman.
- Runtime data, generated credentials, OpenTofu state, and installer profiles stay outside Git.

The first Git-managed application is Technitium DNS at `10.0.0.60`. Arcane
itself remains an Ansible-managed Quadlet because it must be running before it
can pull this repository.

Prepare installation media manually using [`installer/README.md`](installer/README.md).
Then use [`proxmox/README.md`](proxmox/README.md) for host configuration and deployment.
See [`proxmox/RECOVERY.md`](proxmox/RECOVERY.md) for backups and restore drills.
See [`proxmox/UPDATES.md`](proxmox/UPDATES.md) for routine updates with backups and health checks.

## Future service shortlist

The previous [`komoda-homelab`](https://github.com/VV01T3K/komoda-homelab)
repository remains a catalogue, not a migration checklist. Useful candidates
include Caddy, Cloudflared, Authelia, CrowdSec, Homepage, Uptime Kuma, Beszel,
Gitea, n8n, Open WebUI, Excalidraw, and IT-Tools. Each future service should get
its own directory under `apps/` and an explicit owner for secrets and data.

## Local secrets

Keep passwords, API tokens, and private keys in
[`secrets/`](secrets/) at the repository root. The entire folder is ignored by Git.
Deployment and Ansible read credentials here; controller backups include it.

- `proxmox/`: API token (`proxmox.env`) and bootstrap SSH key
- `arcane/`: API key and GitHub deploy key
- `technitium/`: DNS admin password

Add a folder per service as more credentials are introduced.
See [secrets/README.md](secrets/README.md) for generation, rotation, and recovery.

Service runtime copies remain on their hosts. OpenTofu state remains in
`proxmox/tofu/` and is also ignored and included in controller backups.

Machine-specific installer profiles live in `installer/profiles/` and are also
ignored by Git; placeholder examples remain tracked.
