#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
token_file="${HOME}/.config/infra-as-service/proxmox.env"
ssh_key="${HOME}/.ssh/proxmox_bootstrap"
export PATH="${HOME}/.local/bin:${HOME}/.local/usr/bin:${PATH}"

if ! command -v tofu >/dev/null 2>&1; then
  echo "OpenTofu is required: https://opentofu.org/docs/intro/install/" >&2
  exit 1
fi

if [[ ! -r "${token_file}" ]]; then
  echo "Missing Proxmox API token: ${token_file}" >&2
  exit 1
fi

if [[ ! -r "${ssh_key}" ]]; then
  echo "Missing SSH key: ${ssh_key}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${token_file}"
export TF_VAR_ssh_public_key
TF_VAR_ssh_public_key="$(ssh-keygen -y -f "${ssh_key}")"

ANSIBLE_HOST_KEY_CHECKING=True ansible-playbook \
  -i "${project_dir}/ansible/inventory.yml" \
  "${project_dir}/ansible/template.yml"

tofu -chdir="${project_dir}/tofu" init
tofu -chdir="${project_dir}/tofu" apply -auto-approve

ANSIBLE_HOST_KEY_CHECKING=True ansible-playbook \
  -i "${project_dir}/ansible/arcane-inventory.yml" \
  "${project_dir}/ansible/arcane.yml"

ANSIBLE_HOST_KEY_CHECKING=True ansible-playbook \
  -i "${project_dir}/ansible/arcane-inventory.yml" \
  "${project_dir}/ansible/technitium.yml"

ANSIBLE_HOST_KEY_CHECKING=True ansible-playbook \
  -i "${project_dir}/ansible/arcane-inventory.yml" \
  "${project_dir}/ansible/gitops.yml"

echo
echo "Arcane is ready at http://10.0.0.60:3552"
echo "Technitium is ready at http://10.0.0.60:5380"
echo "Technitium user: admin"
echo "Technitium password: ${HOME}/.config/infra-as-service/technitium-admin-password"
