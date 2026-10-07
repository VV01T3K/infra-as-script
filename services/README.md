# Arcane application GitOps

Application definitions live at `services/<environment>/<stack>/compose.yaml`.
Supporting files belong inside that stack directory. Declare the repository,
branch, path, environment and secret mapping in
`stages/5-services/gitops-config.yml`; Arcane IDs are resolved at runtime.
Manager, agent and Caddy bootstrap stays in `mise run services`.
The playbook propagates manager repository configuration to a target agent
before creating its first mapping; background propagation alone can race
mapping creation in Arcane v2.15.0.

The infrastructure repository is public and uses anonymous HTTPS access.
Commit only nonsecret configuration. Private application repositories such as
Research Cruise need their own access configuration before being added.

`mise run gitops` reconciles declared connections and mappings without fetching
stack content. It does not explicitly delete undeclared manager repositories,
projects or syncs. Arcane resource propagation treats the manager repository
configuration as authoritative on agents. Do not map an existing live project during this initial step.
Each declared stack's `secrets` dictionary maps environment variable names to
keys in `secrets/services.sops.yaml`. The playbook owns that project's complete
environment override content. It sends secrets to Arcane through its API;
Arcane does not decrypt SOPS files or receive the YubiKey. Keep `.env` and
`project.env` out of the public source directories.

## Initial canary verification

The canary now uses five-minute polling by default. For initial setup or a
manual verification, disable polling explicitly:

```sh
mise run gitops -e gitops_canary_auto_sync=false -e gitops_sync_now=true -e gitops_verify_canary=true
```

This generates and preserves a SOPS-backed canary token, creates a manual-only
sync on `engi`, syncs the source, sets project environment overrides, then syncs
again and checks that the overrides survive. It then starts only the canary,
verifies its health, token and revision without printing secrets, and reports
its container ID and source commit. It has no ports, persistent storage,
network access or external integrations. Omit `gitops_verify_canary` to leave
the initially synced project stopped.

Change `CANARY_REVISION`, commit and push, then run the same command.
Confirm Arcane records the new commit, the running canary is recreated with
revision `2`, and it stays healthy with the same secret token. Repeat without a
Git change and confirm no recreation. Run reconciliation again and confirm
`changed=0`. Inspect container environment only through a redacted check; never
print the token. A sync error must be visible in Arcane and must fail the playbook.

After verification, enable five-minute polling:

```sh
mise run gitops -e gitops_canary_auto_sync=true
```

The declared canary mapping preserves polling on future runs. Use
`-e gitops_canary_auto_sync=false` to pause it; declare new application mappings
with polling off until their deployment and secrets have been verified.
Arcane checks the branch periodically; pushes do not immediately deploy.
Changed content can redeploy an already-running project even with
`redeployAfterSync: false`. That flag keeps stopped projects stopped.
Images are pinned; no Git backup/write-back mode is configured.

For rollback, revert the source commit and sync again. To stop the experiment,
restore manual sync, then stop only the canary in Arcane. Deleting a mapping from
the declaration does not delete its live resources; cleanup is explicit.

## Frog cutover

Frog is verified on zoltan with its original SSH key and preserved volume data.
The original is stopped on externum, and both hosts hold protected backups.
Polling remains disabled until automatic build behavior is verified. See
`services/zoltan/frog-keepalive/README.md` for cutover and rollback commands.
`gitops_only_stack=frog-keepalive` limits reconciliation to this stack and rejects
unknown names. CloudBeaver remains stopped until the Research Cruise migration.

The manager's project directory is owned by its application UID/GID 65532, with
mode 0700. Bootstrap and GitOps reconcile this ownership; bootstrap Compose
files remain root-only. The manager's root supervisor is not its filesystem
runtime identity.

## Proxy security preparation

`mise run prepare-proxy-security` creates isolated Valkey and CrowdSec projects on
zoltan. Publish their definitions first. It keeps the originals running, copies a
native Valkey replication snapshot and an online SQLite backup, preserves credentials
in SOPS, and verifies restored contents before starting the GitOps replacements.
The RDB is loaded with AOF disabled, then Valkey initializes AOF before normal
startup; the final key count must match. `mise run check-valkey-restore` exercises
that restart using the real image in disposable Podman containers.
Archives remain mode 0600 under a dated `proxy-security` directory on both backup disks.
Target volumes must be absent. A retry refuses existing data instead of overwriting it.

Both services have no published ports. Valkey is on the internal `caddy_security`
network; CrowdSec also has an outbound network for its community API and collections.
Certificate storage uses `noeviction`. Polling stays disabled during migration.
Caddy integration is a separate step after replacement health is verified.
CloudBeaver remains stopped on externum until Research Cruise migrates.
