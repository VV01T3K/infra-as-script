#!/usr/bin/env bash
# Plans, asks, then applies exactly that plan. Used by `mise run guests` and `mise run network`.
# If the plan destroys anything (a replacement destroys too), every such resource is listed and only typing
# "destroy <number>" applies it; a plain "yes" never does. Keys pressed while it worked are ignored.
# (2026-10-06: a plain "yes" to an unexpected plan destroyed all LXC guests.)
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
