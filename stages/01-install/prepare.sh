#!/usr/bin/env bash
set -euo pipefail
umask 077
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
server=pve
profile="$root/stages/01-install/profiles/old-laptop.example.toml"
regenerate=false
while (($#)); do
  case "$1" in
    --server|--profile)
      (($# >= 2)) || { echo "Missing value for $1" >&2; exit 2; }
      case "$1" in --server) server="$2" ;; --profile) profile="$2" ;; esac
      shift 2 ;;
    --regenerate) regenerate=true; shift ;;
    *) echo 'Usage: bash prepare.sh [--server NAME] [--profile FILE] [--regenerate]' >&2; exit 2 ;;
  esac
done
[[ "$server" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || { echo 'Invalid server name' >&2; exit 2; }
destination="$root/secrets/installer/$server"
mkdir -p -- "$destination"
exec 9>"$destination/.lock"
flock -n 9 || { echo 'Installer preparation is already running' >&2; exit 1; }
if [[ -e "$destination/answer.toml" && "$regenerate" == false ]]; then
  for file in answer.toml bootstrap bootstrap.pub root-password; do
    [[ -s "$destination/$file" ]] || { echo "Incomplete installer credentials: $file" >&2; exit 1; }
  done
  echo "Reusing installer answer: $destination/answer.toml"
  exit 0
fi
command -v proxmox-auto-install-assistant >/dev/null
grep -q 'REPLACE_WITH_SHA512_CRYPT_HASH' "$profile"
grep -q 'REPLACE_WITH_BOOTSTRAP_SSH_PUBLIC_KEY' "$profile"
staging="$(mktemp -d "$destination/.prepare-XXXXXX")"
trap 'rm -rf -- "$staging"' EXIT
ssh-keygen -q -t ed25519 -N '' -C installer -f "$staging/bootstrap"
openssl rand -hex 36 >"$staging/root-password"
hashed="$(openssl passwd -6 -stdin <"$staging/root-password")"
public="$(cat "$staging/bootstrap.pub")"
# Generated values contain no sed replacement metacharacters (&, |, backslash).
sed -e "s|REPLACE_WITH_SHA512_CRYPT_HASH|$hashed|g" \
    -e "s|REPLACE_WITH_BOOTSTRAP_SSH_PUBLIC_KEY|$public|g" \
    "$profile" >"$staging/answer.toml"
# Some assistant releases print errors but still return exit status zero.
if ! validation="$(proxmox-auto-install-assistant validate-answer "$staging/answer.toml" 2>&1)" ||
   [[ "$validation" == *'Error:'* ]]; then
  printf '%s\n' "$validation" >&2
  exit 1
fi
if [[ -e "$destination/answer.toml" ]]; then
  mkdir -p -- "$destination/history"
  history="$(mktemp -d "$destination/history/generation-XXXXXX")"
  for file in answer.toml bootstrap bootstrap.pub root-password; do
    [[ ! -e "$destination/$file" ]] || cp -p -- "$destination/$file" "$history/"
  done
fi
for file in bootstrap bootstrap.pub root-password answer.toml; do
  mv -- "$staging/$file" "$destination/$file"
done
echo "Installer answer: $destination/answer.toml"
echo 'Rebuild the USB ISO after regeneration.'
