# Infra as Service

Declarative configuration for the `pve.home.arpa` homelab.

## Ownership

- OpenTofu owns Proxmox guests and their hardware/network allocation.
- Ansible prepares Proxmox, bootstraps hosts, and installs local secrets.
- Arcane syncs application Compose projects from `apps/` and controls their lifecycle on Podman.
- Runtime data, generated credentials, OpenTofu state, and installer profiles stay outside Git.

The first Git-managed application is Technitium DNS at `10.0.0.60`. Arcane
itself remains an Ansible-managed Quadlet because it must be running before it
can pull this repository.

See [`proxmox/README.md`](proxmox/README.md) for installation and deployment.

## Future service shortlist

The previous [`komoda-homelab`](https://github.com/VV01T3K/komoda-homelab)
repository remains a catalogue, not a migration checklist. Useful candidates
include Caddy, Cloudflared, Authelia, CrowdSec, Homepage, Uptime Kuma, Beszel,
Gitea, n8n, Open WebUI, Excalidraw, and IT-Tools. Each future service should get
its own directory under `apps/` and an explicit owner for secrets and data.
