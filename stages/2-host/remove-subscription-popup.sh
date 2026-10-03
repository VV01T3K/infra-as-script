#!/bin/sh
# Managed by stage 2 (infra-as-script). Removes the "No valid subscription" popup from the web UI.
# Updates bring it back, so apt runs this after every package change (90-remove-subscription-popup).
# Turns the popup's condition into `false`; the subscription status shown elsewhere stays as it is.
f=/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js
before="$(md5sum < "$f")"
sed -Ezi "s/res\.data\.status\.toLowerCase\(\) !== 'active'(\s*\)\s*\{\s*Ext\.Msg\.show\(\{\s*title: gettext\('No valid subscription'\))/false\1/" "$f"
[ "$(md5sum < "$f")" = "$before" ] || echo "subscription popup removed"
