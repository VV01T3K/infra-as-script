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
Commit only nonsecret configuration. Research Cruise is also public and uses its own anonymous repository connection;
its Compose and build workflow remain in that repository.

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
unknown names. CloudBeaver remains stopped by the owner's latest decision.

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
CloudBeaver remains stopped on externum; its workspace is preserved.

`mise run integrate-proxy-security -e security_prepare_only=true` builds and tests
an unpublished Caddy candidate, imports current certificates without reissuing them,
and verifies an actual CrowdSec ban and its removal. The cutover checks that the
validated image and files have not changed, switches only Caddy, and checks all four
UI routes, the existing certificate, actual blocking and parsed access logs. Failures
restore the original image and bootstrap. Use `--tags security-cutover` after a
successful private preparation to avoid repeating it.

The one-time integration writes `/opt/caddy/security-enabled` only after verification.
Normal proxy and backend-only updates read this marker and preserve protection;
unhealthy dependencies block updates. A fresh bootstrap has no marker and can start
Caddy/Arcane before restoring application data. Subsequent Caddy changes use the
normal platform bootstrap, rather than importing the old filesystem assets again.

The existing tunnel serves `cruise.wsiwiec.com -> https://caddy` on zoltan.
Research Cruise and its deployment endpoints are verified there. Externum is retired;
CloudBeaver remains stopped with its workspace preserved on the retained disk.

## Research Cruise

The separate public `ResearchCruiseApp` repository owns `docker/compose.staging.yaml`
on `staging`. After both image builds succeed, its deployment script syncs the
Compose file, then applies the project with fresh images and no forced recreation.
Polling is disabled so configuration cannot deploy before the builds finish.
Infrastructure supplies the repository mapping and preserved SOPS-backed overrides.
The workflow uses `STAGING_SYNC_URL` (`/api/environments/0/gitops-syncs/<sync-id>/sync`),
`STAGING_DEPLOY_URL` (`/api/environments/0/projects/<project-id>/up`), and the secrets
`STAGING_DEPLOY_API_KEY` and `CLOUDFLARE_WEBHOOK_SECRET`. Enable
`STAGING_DEPLOY_ENABLED=true` only after the authenticated route and deployment
have been tested and approved.

`mise run prepare-research-cruise` restores a private candidate with no external
network or public route. `mise run migrate-research-cruise` is a guarded one-time
cutover: freeze source writes, test a fresh two-disk native backup, restore and compare
all tables, verify the new origin, then open a TLS-verified old-tunnel relay. Before
traffic opens, failure restores the original writers; after that boundary, keep the
new database authoritative and preserve new writes before any rollback.

The migration is verified, including a subsequent CI-published image deployment.
SQL Server uses the stack's implicit default network and a restored external volume,
with no published port. CloudBeaver remains stopped and unexposed by the owner's latest decision.
`mise run research-cruise-backup` now backs up zoltan by default, requires both mounted
backup disks, and proves the backup with an isolated SQL restore, DBCC CHECKDB and all
table counts. Scheduled and off-site backups remain later work.

Cloudflared runs on zoltan. The legacy Komodo relay and GitHub webhook are disabled.
Komoda, internum and externum are stopped with automatic startup disabled; their
disks are retained for recovery. See the retirement record in `HANDOFF.md`.
