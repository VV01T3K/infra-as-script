# Backup and recovery

Keep two parts together: a Proxmox guest backup and an encrypted controller
backup. Git does not contain the DNS database, Arcane database/encryption key,
API credentials, SSH key, or OpenTofu state.

## Back up

Choose an existing Proxmox storage that supports backups and resides on another
disk or machine. This repository does not configure a backup destination.
Use access-controlled or encrypted storage: the guest backup contains secrets.

From the repository root on the controller, with no deployment running:

```bash
export PATH="$HOME/.local/bin:$HOME/.local/usr/bin:$PATH"
ansible-playbook ansible/playbooks/backup.yml \
  -e backup_storage=YOUR_BACKUP_STORAGE \
  -e controller_backup_path=/path/on/backup-disk/controller-2026-09-05.tar.gz.gpg
```

Replace the storage name, path, and date. The guest backup uses stop mode, so
DNS and Arcane are unavailable for the duration. Proxmox handles the guest's
stop/restart. The playbook does not prune existing backups. Verify the backup
task succeeded and the guest restarted. The current application bind mounts
are directories inside the LXC root disk, so its backup includes
`/var/lib/technitium`, `/etc/technitium`, `/var/lib/arcane`, and `/etc/arcane`.
Revisit coverage if you add LXC mount points or external volumes.

The controller backup playbook prompts for a GPG passphrase and streams the archive
directly into encryption. It includes the repository's `secrets/` folder (including the bootstrap
private SSH key), `installer/profiles/`, and `terraform.tfstate`. Store the passphrase separately and
keep an additional copy of both backups off the Proxmox machine. Record the
repository commit (`git rev-parse HEAD`) and preserve any uncommitted changes.
The controller archive does not contain the Git-managed repository files.

Schedule recurring guest backups in Proxmox once the destination is chosen;
take a new controller backup after state or credential changes. Set retention
on that storage to match its capacity. No schedule is installed by this change.

## Restore after a failure

1. Recover the controller first. Clone the recorded repository revision, then
   decrypt into a private staging directory, not directly over working files:

   ```bash
   umask 077
   recovery_dir="$(mktemp -d)"
   set -o pipefail
   gpg --decrypt /path/to/controller.tar.gz.gpg | tar -xzf - -C "$recovery_dir"
   ```

   Check decryption and extraction succeeded. Restore `secrets/` and `installer/profiles/` into the repository root, and `terraform.tfstate`
   into `opentofu/proxmox/`. Preserve any existing files separately before replacing
   them. Keep directories mode `0700` and secrets mode `0600`.

2. If the Proxmox host was lost, reinstall and run the host bootstrap. Its API
   credentials will need recreating; retain the newly generated `proxmox.env`
   rather than overwriting it with the old host's token.

3. In Proxmox, restore the guest backup to its original ID (normally `200`),
   storage, and IP. Restore the complete guest so Arcane's database and
   `/etc/arcane/arcane.env` encryption key remain paired. Do not run `tofu apply`
   to create an empty guest before restoring it.

4. Load `proxmox.env`, export `TF_VAR_ssh_public_key` as shown in [SETUP.md](SETUP.md),
   run `tofu -chdir=opentofu/proxmox init`, and inspect `tofu -chdir=opentofu/proxmox plan`. Resolve any
   unexpected changes before applying. `prevent_destroy` intentionally blocks
   replacement; do not remove it just to make a recovery plan pass.

5. Run `ansible-playbook ansible/playbooks/verify.yml`. Check Arcane login, Technitium login, local records, blocking,
   and Git sync before directing clients to the recovered DNS server.

If state was lost but the guest survives, recover state from backup first.
If no state backup exists, import the existing guest using the pinned provider's
documented container import format before planning; do not create a duplicate.

## Restore drill

Restore a guest backup to a spare ID with its network disconnected, then attach
it only to an isolated test bridge. The backup retains the production IP and
Arcane's GitOps automation. Do not connect both copies to the production LAN.
Check that the services start, the DNS records and settings exist, and Arcane
can read its stored configuration. Record the backup date and result. A
successful backup task alone does not demonstrate recoverability.

Backup mode and coverage follow the [Proxmox backup documentation](https://github.com/proxmox/pve-docs/blob/master/vzdump.adoc).

For only a controller backup, run this while no infrastructure changes are running:

```bash
ansible-playbook ansible/playbooks/backup.yml -e backup_scope=controller \
  -e controller_backup_path=/absolute/path/controller.tar.gz.gpg
```

The combined `backup.yml` workflow also checks service
health and disables automatic GitOps before the guest backup. See [MAINTENANCE.md](MAINTENANCE.md)
for releasing the retained lock after a failed or interrupted combined workflow.
