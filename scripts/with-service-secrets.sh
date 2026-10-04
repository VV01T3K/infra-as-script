#!/usr/bin/env bash
# Runs one command (Ansible, stage 5) with secrets/services.sops.yaml unlocked into its environment
# as JSON (SERVICE_SECRETS). One YubiKey touch + PIN; nothing is written to disk unencrypted.
# Needed because Ansible detaches its workers from the terminal, so sops can't ask for the PIN there.
# The first run finds no file: Ansible creates the secrets and saves the file (encrypting needs no YubiKey).
# Usage: scripts/with-service-secrets.sh <command>...
set -euo pipefail
cd "$(dirname "$0")/.."

file=secrets/services.sops.yaml
if [ -e "$file" ]; then
  echo "Unlocking the service secrets: touch your YubiKey and type its PIN." >&2
  SERVICE_SECRETS="$(sops decrypt --output-type json "$file")"
else
  SERVICE_SECRETS="{}"
fi
export SERVICE_SECRETS
"$@"
