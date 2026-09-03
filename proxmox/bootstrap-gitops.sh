#!/usr/bin/env bash
set -euo pipefail

repository="${GITHUB_REPOSITORY:-VV01T3K/infra-as-service}"
secret_dir="${HOME}/.config/infra-as-service"
key_file="${secret_dir}/arcane-gitops"
key_title="arcane-gitops"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is required: https://cli.github.com/" >&2
  exit 1
fi

gh auth status --hostname github.com >/dev/null

if [[ "$(gh repo view "${repository}" --json isPrivate --jq .isPrivate)" != "true" ]]; then
  echo "Refusing to configure Arcane against a non-private repository." >&2
  exit 1
fi

install -d -m 700 "${secret_dir}"
if [[ ! -f "${key_file}" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C "${key_title}" -f "${key_file}"
fi
chmod 600 "${key_file}"
chmod 644 "${key_file}.pub"

local_key="$(awk '{ print $1 " " $2 }' "${key_file}.pub")"
remote_key="$(gh api "repos/${repository}/keys" --jq ".[] | select(.title == \"${key_title}\") | .key")"

if [[ -z "${remote_key}" ]]; then
  gh repo deploy-key add "${key_file}.pub" \
    --repo "${repository}" \
    --title "${key_title}"
elif [[ "${remote_key}" != "${local_key}" ]]; then
  echo "GitHub already has a different deploy key named ${key_title}." >&2
  echo "Remove or rename that key before replacing it." >&2
  exit 1
fi

echo "Arcane read-only deploy key is ready for ${repository}."
