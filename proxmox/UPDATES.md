# Routine updates

Run maintenance from `proxmox/` on the Linux/WSL controller. The update command
uses existing OpenTofu state to locate the guest and never runs `tofu apply`.
It requires a clean, committed checkout, the existing controller credentials,
and the same tools as deployment plus GPG and `tar`.

## Switch existing installations to explicit updates

Before pushing an application version change for the first time, run:

```bash
ansible-playbook -i ansible/inventory.yml ansible/pause.yml
```

This disables future automatic Technitium syncs without deploying. If a sync
is already running, let it finish in Arcane before publishing the change or
starting maintenance. This command also works with an uncommitted checkout.
New deployments configure manual GitOps sync from the start. Arcane still owns
the Compose project, but a push to `main` no longer automatically deploys it.
Leave automatic sync disabled in the UI when using this backup-first workflow.

## Select one component

Choose an existing Proxmox storage that supports backups, preferably on another
disk or machine, and an existing controller backup directory outside this repo.
The two destinations may be on different machines. For example:

```bash
ansible-playbook -i ansible/inventory.yml ansible/update.yml \
  -e maintenance_target=guest \
  -e backup_storage=YOUR_PROXMOX_BACKUP_STORAGE \
  -e controller_backup_dir=/mnt/backup/infra-as-script
```

Replace both destination placeholders with your actual storage and directory.
Ansible privately prompts for the backup passphrase and confirmation. Set `maintenance_target` to one target at a time:

| Target | Changes |
| --- | --- |
| `guest` | Upgrades Debian 13 guest packages, including Podman, then reboots if packages changed or a reboot was already pending. |
| `host` | Backs up host configuration too, upgrades Proxmox VE 9/Debian 13 packages, and reboots on the same conditions. This affects every guest on the host. |
| `arcane` | Applies the pinned `arcane_image` from `ansible/arcane.yml`; a changed image updates the Quadlet and restarts Arcane. |
| `technitium` | Explicitly syncs published `main`, deploys the pinned Compose image through Arcane, and reapplies managed DNS settings. |

Package updates use the currently configured APT repositories. The workflow
does not change release suites, upgrade to a new OS major version, or permit
package removals. Resolve a required removal as a separate reviewed operation.
A package change triggers a reboot so running processes load updated libraries.

For an application update, choose the desired release after reading its release
notes, edit the pinned image version, review the diff, and run `ansible-playbook ansible/validate.yml`.
Commit the change before maintenance. For Technitium, publish it to `main` too;
the command requires local `HEAD` to match the configured GitHub repository's
`main` and checks Arcane's resulting commit. Do not push other changes during
the run. The repository URL currently matches the hardcoded URL in `gitops.yml`;
change both if you fork the project.

## What the command does

1. Locks out concurrent deployment/update commands on this controller, reads
   inventory from state, and checks application health and DNS.
2. Creates an encrypted controller backup and disables scheduled GitOps syncs.
3. Runs a stop-mode guest backup and checks that services recover afterward.
   DNS and Arcane are unavailable during this backup, even for an Arcane-only
   update. Host updates additionally archive `/etc`, including `/etc/pve`, and
   encrypt that archive on the controller.
4. Updates only the selected component and waits for required restarts.
5. Checks Arcane and Technitium HTTP endpoints and local/external DNS over UDP
   and TCP, including the managed PTR records. The optional blocking query uses
   `dns_blocked_test_name` from the shared variables.

The controller backup directory receives a unique run directory containing the
encrypted archive(s), guest backup task output, and a manifest with the Git
revision, target, storage, and completion status. The guest archive itself is
on the selected Proxmox storage. Failed backups prevent the update from starting;
failed updates or health checks return an error and never mark the run verified.
The directory lock at `secrets/proxmox/maintenance.lock.d` coordinates deployment,
maintenance, credential rotation, pause, and combined backup entry points on this checkout. It does
not coordinate OpenTofu commands, other checkouts, individual component playbooks,
or UI work. Successful workflows release it; failures retain it for inspection.

Boot recovery enables `podman-restart.service` and extends it to include
`unless-stopped` containers, which the Podman 5.4 unit does not select by default.
Both `always` and `unless-stopped` containers start when the guest boots, including
ones manually stopped before shutdown. Remove a project's containers through
Arcane if it must remain absent across reboots.

Host configuration is briefly staged in private temporary directories on the
host and controller; normal completion/failure cleans them up. An abrupt power
loss or forced kill can leave staging files, which contain secrets. The host
configuration backup supports reconstructing the host; it is not a full host
disk image or a backup of other guests. Back up other workloads separately.

## If an update fails

If the pause stage completed, automatic GitOps stays disabled. Read the task error and the run directory's
manifest and guest backup output. Use [RECOVERY.md](RECOVERY.md) to restore the
guest and matching controller files when necessary. Preserve newer state and
secrets before replacing them with backup copies.

There is no automatic downgrade: an application may have migrated its database.
For a compatible image-only rollback, revert the image version in Git and run
the corresponding update target. Otherwise restore the pre-update guest backup
with its matching application data and encryption key. After a host failure,
use the previous bootable kernel where applicable, or reinstall and selectively
recover configuration; do not blindly extract all of `/etc` onto a running host.

Major Proxmox/Debian migrations and OpenTofu/provider upgrades remain separate,
reviewed procedures.

A failed or interrupted run retains its lock. Once you have confirmed that no
workflow is still running and inspected the failure, release it from `proxmox/`:

```bash
ansible-playbook ansible/unlock.yml
```

Then retry the appropriate workflow. The workflows reject `--check` because it
cannot prove backup and update ordering; use `--syntax-check` for static validation.
For unattended backups, supply `backup_passphrase` using an Ansible Vault-encrypted
vars file (`-e @/path/to/backup-vars.yml --ask-vault-pass`), never a literal command-line secret.
