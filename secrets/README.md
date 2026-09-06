# Manage credentials

Run these commands in Linux/WSL from this `secrets/` folder. Ansible performs
changes on the running services as well as updating the local files.

## Everyday commands

Show which managed credentials are present (never prints their values):

```bash
ansible-playbook -i ../proxmox/ansible/inventory.yml ../proxmox/ansible/secrets.yml
```

Generate missing local keys and passwords for a **new installation**:

```bash
ansible-playbook -i ../proxmox/ansible/inventory.yml ../proxmox/ansible/secrets.yml -e secrets_action=generate
```

Rotate all managed credentials on an existing deployment:

```bash
ansible-playbook -i ../proxmox/ansible/inventory.yml ../proxmox/ansible/secrets.yml -e secrets_action=rotate
```

Rotate just one credential by adding, for example, `-e secrets_only=technitium`.
Supported selections: `ssh`, `root`, `proxmox-api`, `arcane-api`, `gitops`,
`technitium`, or `all` (the default).

For a brand-new installer profile, use the generated `proxmox/proxmox_bootstrap.pub`.
For an existing USB, keep its matching installer key and follow the reinstall
command below; generating another key does not change the USB profile.

The controller needs the same Linux/WSL tools as deployment, plus OpenSSL.
GitHub deploy-key rotation requires `gh auth login` with repository administrator
access. Existing hosts and services must be reachable. Rotation reads the guest
address from OpenTofu state; it does not run `tofu apply` or redeploy applications.
Arcane API-key rotation briefly restarts Arcane.

## What is managed

| Selection | Local files | What rotation does |
| --- | --- | --- |
| `ssh` | `proxmox/proxmox_bootstrap` and `.pub` | Adds a new SSH key to host and guest, tests fresh connections with it, then removes the previous key and public keys from completed installer profiles. |
| `root` | `proxmox/root-password`, `arcane/root-password` | Replaces and verifies root console password hashes on host and guest. |
| `proxmox-api` | `proxmox/proxmox.env`, `proxmox/token-id` | Issues and verifies a new token, publishes it locally, then revokes the previous managed token. |
| `arcane-api` | `arcane/arcane-api-key` | Updates the configured static API key, restarts Arcane, tests authentication, and checks the old key is rejected. |
| `gitops` | `arcane/arcane-gitops` and `.pub` | Registers a new read-only GitHub key, updates and tests Arcane's repository connection, then deletes the old GitHub key. |
| `technitium` | `technitium/technitium-admin-password` | Changes the live admin password through the API, verifies login, updates the runtime password file, and revokes previous admin sessions/API tokens. |

`generate` creates only missing SSH keys, the Arcane API key, the GitHub deploy
key, and the Technitium password. It does not replace existing files or issue a
Proxmox token offline. Host setup issues that token. Generate refuses to fill
missing files when this checkout already has OpenTofu state: restore credentials
from a backup or use the relevant live rotation instead.

After rotating, refresh the environment in any shell used for OpenTofu:

```bash
source proxmox/proxmox.env
export TF_VAR_ssh_public_key="$(ssh-keygen -y -f proxmox/proxmox_bootstrap)"
```

For Technitium with 2FA enabled, supply `technitium_totp` through a private
Ansible vars file. A rejected or expired code stops the password-change workflow.

## Installer credentials

`site.yml` automatically performs `post-install` retirement after successful host
setup, before guest provisioning. It changes the installed root password and SSH
key, and records the host machine ID so repeated host setup does not rotate again.
The profile and files already on the USB are left as they are.

The original private SSH key is retained at `installer/profiles/old-laptop.key`
for reinstalling from the existing USB. Completed profiles remain under
`installer/profiles/`, and controller backups include that folder.

For a reinstall, use the installer key explicitly when running host setup:

```bash
ansible-playbook -i ../proxmox/ansible/inventory.yml ../proxmox/ansible/site.yml \
  -e ansible_ssh_private_key_file="$PWD/../installer/profiles/old-laptop.key"
```

For an existing deployment that predates this feature, run the complete `rotate`
command first. It updates both machines and records installer retirement. A first
`post-install` run refuses an already-provisioned checkout so it cannot leave the
guest using an SSH key that was replaced only on the host.

## Failed runs and recovery

Each credential has durable staging in `.pending/NAME/`: the original, candidate,
and any service-specific recovery data. A successful rotation moves that folder
into `history/`. Both locations are private, git-ignored, and included in controller
backups. Keep a controller backup off this machine too.

If a run fails, inspect the error and ensure it has stopped. Release its retained
lock, then rerun rotation for that credential:

```bash
ansible-playbook ../proxmox/ansible/unlock.yml
ansible-playbook -i ../proxmox/ansible/inventory.yml ../proxmox/ansible/secrets.yml \
  -e secrets_action=rotate -e secrets_only=technitium
```

The pending candidate is reused. Do not delete `.pending/` or replace files with
random values: the service may already be using the staged candidate. For a lost
Technitium password or deploy private key, recover the original from history or a
controller backup first. The workflow cannot authenticate with an unknown password.
History is recovery material, not an automatic rollback: retired tokens and keys
remain revoked until deliberately re-authorized.

## Keys with a different lifecycle

Arcane's `ENCRYPTION_KEY` protects stored application data. It is preserved during
API-key rotation, including a private copy of the runtime environment in history.
It is **not** regenerated by `rotate`: changing it requires a supported data
re-encryption/migration procedure and matching backups. Existing backup encryption
passphrases, externally managed GitHub CLI login credentials, and Arcane UI user
passwords are also outside this managed credential set.

Service behavior follows the [Technitium 15.4 API](https://github.com/TechnitiumSoftware/DnsServer/blob/v15.4.0/APIDOCS.md),
[Arcane static API-key configuration](https://getarcane.app/api-reference), and
[Arcane Git repository API](https://github.com/getarcaneapp/arcane/blob/v2.10.1/backend/internal/gitrepo/handler.go).

Only this guide is tracked in Git. Credential values, staging, and history stay local.
