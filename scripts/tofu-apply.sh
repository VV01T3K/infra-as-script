#!/usr/bin/env bash
# Plans, asks, then applies exactly that plan. Used by `mise run guests` and `mise run network`.
# If the plan destroys anything (a replacement destroys too), every such resource is listed and only typing
# "destroy <number>" applies it; a plain "yes" never does. Keys pressed while it worked are ignored.
# (2026-10-06: a plain "yes" to an unexpected plan destroyed all LXC guests.) Afterwards it forgets the old SSH
# host key of every VM it created, see the end.
# Usage: scripts/tofu-apply.sh <tofu folder> [extra tofu plan options, e.g. -replace=...]
set -euo pipefail
dir="$1"; shift
plan="$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/tofu-plan.XXXXXX")"
trap 'rm -f "$plan"' EXIT

tofu -chdir="$dir" init -input=false > /dev/null
tofu -chdir="$dir" plan -input=false -out="$plan" "$@"

changes="$(tofu -chdir="$dir" show -json "$plan")"
if [ "$(jq '[.resource_changes[]? | select(.change.actions != ["no-op"] and .change.actions != ["read"])] | length' <<< "$changes")" -eq 0 ]; then
  exit 0 # "No changes" was printed above
fi
destroyed="$(jq -r '.resource_changes[]? | select(.change.actions | index("delete")) | "  " + .address' <<< "$changes")"

# Throw away anything typed so far, so only an answer typed after the question counts.
while read -r -s -t 0.1 -n 1000 _; do :; done || true

if [ -n "$destroyed" ]; then
  n="$(wc -l <<< "$destroyed")"
  printf '\n\e[1;31mThis plan DESTROYS %s resource(s) (a replacement destroys, then creates):\e[0m\n%s\n\n' "$n" "$destroyed"
  read -r -p "Type \"destroy $n\" to apply it; anything else cancels: " answer || answer=""
  [ "$answer" = "destroy $n" ] || { echo "Cancelled, nothing was changed."; exit 1; }
else
  read -r -p "Apply this plan? Type \"yes\": " answer || answer=""
  [ "$answer" = yes ] || { echo "Cancelled, nothing was changed."; exit 1; }
fi
tofu -chdir="$dir" apply -input=false "$plan"

# A VM that was just created (new, or rebuilt) has a new SSH host key. Forget the old one recorded in
# secrets/known_hosts for its address, so the next login records the new key instead of being refused.
for vm in $(jq -r '.resource_changes[]? | select(.type == "proxmox_virtual_environment_vm" and (.change.actions | index("create"))) | .index' <<< "$changes"); do
  address="$(ansible-inventory --host "$vm" 2> /dev/null | jq -r '.address // empty')"
  [ -n "$address" ] || continue
  ssh-keygen -R "$address" -f secrets/known_hosts > /dev/null 2>&1 && rm -f secrets/known_hosts.old
  echo "Forgot the old SSH host key of $vm ($address); the next login records its new one."
done
