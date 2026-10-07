# Arcane application GitOps

Application definitions live at `services/<environment>/<stack>/compose.yaml`.
Supporting files belong inside that stack directory. Declare the repository,
branch, path, environment and secret mapping in
`stages/5-services/gitops-config.yml`; Arcane IDs are resolved at runtime.
Manager, agent and Caddy bootstrap stays in `mise run services`.

The infrastructure repository is public and uses anonymous HTTPS access.
Commit only nonsecret configuration. Private application repositories such as
Research Cruise need their own access configuration before being added.

`mise run gitops` reconciles declared connections and mappings without fetching
stack content. It leaves unrelated repositories, projects and syncs alone and
never removes them. Do not map an existing live project during this initial step.
Each declared stack's `secrets` dictionary maps environment variable names to
keys in `secrets/services.sops.yaml`. The playbook owns that project's complete
environment override content. It sends secrets to Arcane through its API;
Arcane does not decrypt SOPS files or receive the YubiKey. Keep `.env` and
`project.env` out of the public source directories.

## Initial canary verification

After publishing the canary source to `main`, run:

```sh
mise run gitops -e gitops_sync_now=true -e gitops_verify_canary=true
```

This generates and preserves a SOPS-backed canary token, creates a manual-only
sync on `engi`, syncs the source, sets project environment overrides, then syncs
again and checks that the overrides survive. It then starts only the canary,
verifies its health, token and revision without printing secrets, and reports
its container ID and source commit. It has no ports, persistent storage,
network access or external integrations. Omit `gitops_verify_canary` to leave
the initially synced project stopped.

Change `CANARY_REVISION` from `1` to `2`, commit and push, then run the same command.
Confirm Arcane records the new commit, the running canary is recreated with
revision `2`, and it stays healthy with the same secret token. Repeat without a
Git change and confirm no recreation. Run reconciliation again and confirm
`changed=0`. Inspect container environment only through a redacted check; never
print the token. A sync error must be visible in Arcane and must fail the playbook.

After verification, enable five-minute polling:

```sh
mise run gitops -e gitops_canary_auto_sync=true
```

Persist `autoSync: true` in the declared mapping if polling should remain enabled
on future runs. Default reconciliation otherwise restores manual sync.
Arcane checks the branch periodically; pushes do not immediately deploy.
Changed content can redeploy an already-running project even with
`redeployAfterSync: false`. That flag keeps stopped projects stopped.
Images are pinned; no Git backup/write-back mode is configured.

For rollback, revert the source commit and sync again. To stop the experiment,
restore manual sync, then stop only the canary in Arcane. Deleting a mapping from
the declaration does not delete its live resources; cleanup is explicit.
