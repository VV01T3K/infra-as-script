# Local credentials

`installer/<server>/` contains only the USB installer's `answer.toml`, root password,
SSH private/public key, and retained generations. Stage 01 never creates Arcane,
Technitium or Proxmox API credentials. Regenerating installer credentials requires
rebuilding the USB ISO and does not change a running server.

`proxmox/` contains runtime SSH, root and API credentials from stage 02. `.pending/`
and `history/` support recoverable runtime rotations. Installer keys are retired
from the running host but kept locally for future reinstalls.

Application credentials under `arcane/` and `technitium/` belong to the optional
application workflows, outside the three host/provisioning stages.

Existing credentials are preserved by this repository reorganization. An older
answer file under `stages/01-install/profiles/` remains supported for retirement;
new answers are generated here. Do not replace a working runtime SSH key with a
new installer key unless preparing access to a freshly reinstalled host.
