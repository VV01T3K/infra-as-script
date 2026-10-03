#!/usr/bin/env bash
# Run a command with the fleet SSH key loaded into a temporary ssh-agent (memory only).
# Asks for the YubiKey once (touch + PIN); the agent and the key are gone when the command ends.
set -euo pipefail
eval "$(ssh-agent -s)" >/dev/null
trap 'ssh-agent -k >/dev/null' EXIT
echo "Unlocking the fleet key: touch your YubiKey and type its PIN." >&2
sops decrypt --extract '["ssh_private_key"]' secrets/fleet-ssh-key.sops.yaml | ssh-add -q -
"$@"
