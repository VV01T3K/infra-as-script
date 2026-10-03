#!/usr/bin/env bash
# Run a command with the fleet SSH key loaded into a temporary ssh-agent (memory only).
# Asks for the YubiKey once (touch + PIN). When the command ends, the agent and the key are gone
# and every reusable SSH connection is closed: nothing stays logged in.
set -euo pipefail
cleanup() {
  ssh-agent -k >/dev/null 2>&1 || true
  for socket in ~/.ansible/cp/*; do
    [ -S "$socket" ] && ssh -o ControlPath="$socket" -O exit closing >/dev/null 2>&1 || true
  done
}
eval "$(ssh-agent -s)" >/dev/null
trap cleanup EXIT
echo "Unlocking the fleet key: touch your YubiKey and type its PIN." >&2
sops decrypt --extract '["ssh_private_key"]' secrets/fleet-ssh-key.sops.yaml | ssh-add -q -
"$@"
