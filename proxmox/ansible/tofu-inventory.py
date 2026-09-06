#!/usr/bin/env python3
"""Print an Ansible YAML-compatible JSON inventory from applied OpenTofu state."""

import ipaddress
import json
from pathlib import Path
import subprocess
import sys


def main():
    tofu_dir = Path(__file__).resolve().parents[1] / "tofu"
    try:
        result = subprocess.run(
            ["tofu", f"-chdir={tofu_dir}", "output", "-json", "arcane"],
            check=True, capture_output=True, text=True,
        )
        guest = json.loads(result.stdout)
        address = str(ipaddress.IPv4Address(guest["ip"]))
        guest_id = int(guest["lxc_id"])
        if guest_id < 100:
            raise ValueError("Invalid LXC ID")
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f"Cannot read Arcane from OpenTofu state ({type(exc).__name__}). "
              "Run tofu apply successfully first.", file=sys.stderr)
        return 1
    print(json.dumps({"all": {"hosts": {"arcane": {
        "ansible_host": address,
        "lxc_id": guest_id,
        "ansible_user": "root",
        "ansible_python_interpreter": "/usr/bin/python3",
        "ansible_ssh_private_key_file": str(Path(__file__).resolve().parents[2] / "secrets/proxmox/proxmox_bootstrap"),
        "ansible_ssh_common_args": "-o StrictHostKeyChecking=accept-new",
    }}}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
