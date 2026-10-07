# Frog keepalive on zoltan

This stack reuses the dedicated SSH key and last-success timestamp from the
original deployment on externum. Its two external volumes must be restored
before deployment. A missing trusted host-key fingerprint stops the entrypoint.
The key's remote restriction must force `/usr/bin/uptime`; validation requests
`false` and succeeds only when Frog overrides it.

After publishing this directory, run `mise run migrate-frog`. The cutover:

- Requires the original to be running and refuses existing target volumes.
- Copies the original environment settings into SOPS-backed Arcane overrides.
- Stops the original, archives both volumes and retains backups on both hosts.
- Restores the volumes and verifies file contents, permissions and ownership.
- Syncs only Frog, builds its image, verifies a restricted SSH login and starts
  the replacement through Arcane.
- Stops the replacement and restarts the original if the cutover fails.

The immediate verification login advances the restored last-success timestamp.
The SSH key stays unchanged. Source volumes and the stopped original container
remain on externum. Local transit archives are removed; host backups are
root-only and contain the private key. CloudBeaver remains stopped and is
handled with the later Research Cruise migration.

Polling starts disabled. For a later manual source update, publish it, run:

```sh
mise run gitops -e gitops_only_stack=frog-keepalive -e gitops_sync_now=true
```

Then rebuild the project's image and recreate Frog through Arcane. Verify build
behavior before enabling polling for this stack.

For a manual rollback, stop Frog on zoltan first, then start the retained
`frog-keepalive-frog-keepalive-1` container on externum. Do not run both schedulers
at once. An interrupted or failed cutover keeps target volumes for inspection;
the cutover refuses to overwrite them on a retry.

Keep the separate two-month reminder until Mikrus confirms that these automated
logins reset the inactivity timer.
