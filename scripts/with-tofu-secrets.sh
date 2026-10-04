#!/usr/bin/env bash
# Runs one command (OpenTofu) with the Proxmox API tokens and the state passphrase in its environment,
# then they are gone. Nothing is written to disk unencrypted.
#   secrets/tofu.sops.yaml          api_tokens (one per machine) + state_passphrase: one YubiKey touch + PIN
#   secrets/<machine>.api.sops.yaml a new token from stage 2: merged into tofu.sops.yaml once, then deleted
#   secrets/unifi.sops.yaml         the router login (username, password): merged the same way
# TLS: each Proxmox machine is checked against its own CA (inventory/proxmox-ca/*.pem, saved by stage 2).
# Usage: scripts/with-tofu-secrets.sh <command>...
set -euo pipefail
cd "$(dirname "$0")/.."

file=secrets/tofu.sops.yaml
tmp="$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/tofu-secrets.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

if [ -e "$file" ]; then
  echo "Unlocking the OpenTofu secrets: touch your YubiKey and type its PIN." >&2
  secrets="$(sops decrypt --output-type json "$file")"
  save=false
else
  secrets="$(jq -n --arg p "$(openssl rand -base64 32)" '{state_passphrase: $p, api_tokens: {}}')"
  save=true
fi

merged=()
for f in secrets/*.api.sops.yaml; do
  [ -e "$f" ] || continue
  machine="$(basename "$f" .api.sops.yaml)"
  echo "Adding the new API token of $machine: touch your YubiKey and type its PIN." >&2
  token="$(sops decrypt --extract '["api_token"]' "$f")"
  secrets="$(printf '%s' "$secrets" | jq --arg m "$machine" --arg t "$token" '.api_tokens[$m] = $t')"
  merged+=("$f")
  save=true
done

if [ -e secrets/unifi.sops.yaml ]; then
  echo "Adding the router login: touch your YubiKey and type its PIN." >&2
  unifi="$(sops decrypt --output-type json secrets/unifi.sops.yaml | jq -c '{username, password}')"
  secrets="$(printf '%s' "$secrets" | jq --argjson u "$unifi" '.unifi = $u')"
  merged+=(secrets/unifi.sops.yaml)
  save=true
fi

# Encrypting needs no YubiKey. The plain text only passes through a pipe and RAM ($XDG_RUNTIME_DIR).
if $save; then
  printf '%s' "$secrets" > "$tmp/plain.json"
  sops encrypt --input-type json --output-type yaml --filename-override "$file" "$tmp/plain.json" > "$tmp/new.yaml"
  rm "$tmp/plain.json"
  mv "$tmp/new.yaml" "$file"
  [ ${#merged[@]} -eq 0 ] || rm "${merged[@]}"
fi

# Go (OpenTofu and the provider) reads this file instead of the system's CA file, but still reads the
# system's CA folder (/etc/ssl/certs), so downloads from the internet keep working.
cat inventory/proxmox-ca/*.pem > "$tmp/proxmox-ca.pem"

TF_VAR_api_tokens="$(printf '%s' "$secrets" | jq -c .api_tokens)" \
  TF_VAR_unifi="$(printf '%s' "$secrets" | jq -c '.unifi // {username: "", password: ""}')" \
  TF_VAR_state_passphrase="$(printf '%s' "$secrets" | jq -r .state_passphrase)" \
  SSL_CERT_FILE="$tmp/proxmox-ca.pem" \
  "$@"
